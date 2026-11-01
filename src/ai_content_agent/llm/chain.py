from __future__ import annotations

import json
import logging
import random
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from ..growth.usage import record_usage
from .cache import LLMCache, prompt_key
from .errors import (
    AUTH,
    BAD_OUTPUT,
    BAD_REQUEST,
    JSON_MODE,
    QUOTA,
    RATE_LIMIT,
    TRANSIENT,
    AllProvidersFailed,
    Attempt,
    ProviderError,
)
from .providers import Completion, Provider

logger = logging.getLogger(__name__)

MAX_RETRY_AFTER_SECONDS = 60.0
COOLDOWN_AFTER_FAILED_CALLS = 2
COOLDOWN_SECONDS = 300.0


@dataclass
class _State:
    disabled_reason: str | None = None
    disabled_until: float | None = None  # monotonic deadline; None = rest of the process
    failed_calls: int = 0
    json_mode_ok: bool = True


class ProviderHealth:
    """In-process memory of which providers are unusable right now.

    Shared by every chain in the process (each agent builds its own client), so one agent discovering a
    dead provider saves the next agent from paying the same timeout again.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._states: dict[str, _State] = {}

    def _state(self, name: str) -> _State:
        return self._states.setdefault(name, _State())

    def disabled_reason(self, name: str) -> str | None:
        state = self._state(name)
        if state.disabled_reason is None:
            return None
        if state.disabled_until is not None and self._clock() >= state.disabled_until:
            state.disabled_reason = state.disabled_until = None
            state.failed_calls = 0
            return None
        return state.disabled_reason

    def disable(self, name: str, reason: str, seconds: float | None = None) -> None:
        state = self._state(name)
        state.disabled_reason = reason
        state.disabled_until = None if seconds is None else self._clock() + seconds
        logger.warning("::warning::LLM provider %s disabled: %s", name, reason)

    def record_success(self, name: str) -> None:
        self._state(name).failed_calls = 0

    def record_failed_call(self, name: str, reason: str) -> None:
        state = self._state(name)
        state.failed_calls += 1
        if state.failed_calls >= COOLDOWN_AFTER_FAILED_CALLS:
            self.disable(name, f"{state.failed_calls} failed calls in a row ({reason})", COOLDOWN_SECONDS)

    def json_mode_ok(self, name: str) -> bool:
        return self._state(name).json_mode_ok

    def disable_json_mode(self, name: str) -> None:
        self._state(name).json_mode_ok = False

    def reset(self) -> None:
        self._states.clear()


HEALTH = ProviderHealth()


def reset_health() -> None:
    HEALTH.reset()


@dataclass(frozen=True)
class ChainResult:
    text: str
    provider: str
    model: str
    cached: bool = False
    attempts: list[Attempt] = field(default_factory=list)


def is_json_object(text: str) -> bool:
    from ..opencode.client import extract_json_text

    try:
        return isinstance(json.loads(extract_json_text(text)), dict)
    except ValueError:
        return False


def demote_recently_failing(providers: Sequence[Provider], database_path: str, hours: int = 48) -> list[Provider]:
    """Move providers whose latest calls all failed behind the ones that work.

    Reads ``api_usage`` (written by every call). A provider is demoted when its 3 most recent calls in the
    window all failed, so one bad call never reorders the chain, but a provider that has gone dead (an earlier
    success does not matter) stops costing a timeout at the start of every run.
    """
    if database_path == ":memory:" or not Path(database_path).exists():
        return list(providers)
    try:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True, timeout=3)
        try:
            rows = connection.execute(
                "SELECT provider, ok FROM api_usage WHERE service = 'llm' "
                "AND created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?) ORDER BY id DESC",
                (f"-{hours} hours",),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return list(providers)
    latest: dict[str, list[int]] = {}
    for name, ok in rows:
        bucket = latest.setdefault(name, [])
        if len(bucket) < 3:
            bucket.append(ok)
    failing = {name for name, oks in latest.items() if len(oks) == 3 and not any(oks)}
    return [p for p in providers if p.name not in failing] + [p for p in providers if p.name in failing]


class ProviderChain:
    """Tries providers in order until one returns a valid answer.

    Guarantees: ``complete`` either returns a result or raises AllProvidersFailed, never anything else,
    and never takes much longer than ``call_budget_seconds`` (plus one request timeout).
    """

    def __init__(
        self,
        providers: Sequence[Provider],
        *,
        max_attempts: int = 2,
        request_timeout: float = 45.0,
        call_budget_seconds: float = 240.0,
        backoff_seconds: float = 1.5,
        cache: LLMCache | None = None,
        health: ProviderHealth | None = None,
        expect_json: bool = True,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.providers = list(providers)
        self.max_attempts = max(1, max_attempts)
        self.request_timeout = request_timeout
        self.call_budget_seconds = call_budget_seconds
        self.backoff_seconds = backoff_seconds
        self.cache = cache
        self.health = health or HEALTH
        self.expect_json = expect_json
        self._sleep = sleep
        self._clock = clock
        self._jitter = jitter
        self._served_from_cache: set[str] = set()

    # ------------------------------------------------------------------ public
    def complete(self, prompt: str, label: str | None = None) -> ChainResult:
        key = prompt_key(prompt, self.expect_json)
        cached = self._read_cache(key)
        if cached is not None:
            return cached

        deadline = self._clock() + self.call_budget_seconds
        attempts: list[Attempt] = []
        for provider in self.providers:
            reason = self.health.disabled_reason(provider.name)
            if reason:
                attempts.append(Attempt(provider.name, "skipped", reason))
                continue
            if self._clock() >= deadline:
                attempts.append(Attempt(provider.name, "skipped", "call time budget used up"))
                continue
            completion = self._try_provider(provider, prompt, label, deadline, attempts)
            if completion is not None:
                if self.cache is not None and (not self.expect_json or is_json_object(completion.text)):
                    self.cache.put(key, completion.text, provider.name, completion.model)
                failed = [a for a in attempts if a.kind != "skipped"]
                logger.info(
                    "::notice::[LLM:%s] answered by %s (%s)%s",
                    label or "agent",
                    provider.name,
                    completion.model,
                    f" after {len(failed)} failed attempt(s)" if failed else "",
                )
                return ChainResult(completion.text, provider.name, completion.model, False, attempts)
        raise AllProvidersFailed(attempts)

    # ----------------------------------------------------------------- internals
    def _read_cache(self, key: str) -> ChainResult | None:
        if self.cache is None:
            return None
        if key in self._served_from_cache:
            # The same prompt again means the caller rejected the cached answer: never serve it twice.
            self.cache.evict(key)
            self._served_from_cache.discard(key)
            return None
        entry = self.cache.get(key)
        if entry is None:
            return None
        self._served_from_cache.add(key)
        logger.info("::notice::[LLM] cache hit (answered earlier by %s)", entry.get("provider"))
        return ChainResult(entry["text"], str(entry.get("provider") or "cache"), str(entry.get("model") or ""), True)

    def _try_provider(
        self,
        provider: Provider,
        prompt: str,
        label: str | None,
        deadline: float,
        attempts: list[Attempt],
    ) -> Completion | None:
        attempt = 0
        while attempt < self.max_attempts:
            attempt += 1
            remaining = deadline - self._clock()
            if remaining <= 0:
                attempts.append(Attempt(provider.name, "skipped", "call time budget used up"))
                return None
            json_mode = self.expect_json and provider.supports_json_mode and self.health.json_mode_ok(provider.name)
            started = self._clock()
            try:
                try:
                    timeout = getattr(provider, "timeout_seconds", None) or self.request_timeout
                    completion = provider.complete(prompt, json_mode, min(timeout, remaining))
                except ProviderError:
                    raise
                except Exception as unexpected:  # noqa: BLE001 - a provider bug must not escape the chain
                    raise ProviderError(TRANSIENT, f"unexpected {type(unexpected).__name__}: {unexpected}") from None
            except ProviderError as exc:
                self._track(provider, None, False, started)
                attempts.append(Attempt(provider.name, exc.kind, str(exc)))
                logger.warning("LLM provider %s failed (%s): %s", provider.name, exc.kind, exc)
                if exc.kind == JSON_MODE and json_mode:
                    self.health.disable_json_mode(provider.name)
                    attempt -= 1  # not a real failure: retry immediately without JSON mode
                    continue
                if exc.kind in (AUTH, BAD_REQUEST, QUOTA):
                    self.health.disable(provider.name, f"{exc.kind}: {exc}")
                    return None
                if exc.kind == BAD_OUTPUT:
                    return None
                if exc.kind in (TRANSIENT, RATE_LIMIT) and attempt < self.max_attempts:
                    self._sleep(self._backoff(attempt, exc.retry_after, deadline))
                    continue
                self.health.record_failed_call(provider.name, exc.kind)
                return None
            self._track(provider, completion, True, started)
            if self.expect_json and not is_json_object(completion.text):
                preview = " ".join(completion.text.split())[:80]
                attempts.append(Attempt(provider.name, BAD_OUTPUT, f"answer was not a JSON object: {preview!r}"))
                logger.warning("LLM provider %s returned non-JSON output; trying the next provider", provider.name)
                return None
            self.health.record_success(provider.name)
            return completion
        return None

    def _backoff(self, attempt: int, retry_after: float | None, deadline: float) -> float:
        if retry_after is not None:
            wait = min(retry_after, MAX_RETRY_AFTER_SECONDS)
        else:
            wait = self.backoff_seconds * (2 ** (attempt - 1)) * (0.75 + 0.5 * self._jitter())
        return max(0.0, min(wait, deadline - self._clock()))

    def _track(self, provider: Provider, completion: Completion | None, ok: bool, started: float) -> None:
        if provider.records_own_usage:
            return
        record_usage(
            "llm",
            "chat",
            provider=provider.name,
            model=completion.model if completion else None,
            ok=ok,
            input_tokens=completion.input_tokens if completion else None,
            output_tokens=completion.output_tokens if completion else None,
            duration_ms=int((self._clock() - started) * 1000),
        )
