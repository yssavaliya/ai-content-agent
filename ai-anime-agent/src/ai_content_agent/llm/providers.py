from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

from ..redaction import redact
from .errors import (
    AUTH,
    BAD_OUTPUT,
    BAD_REQUEST,
    JSON_MODE,
    QUOTA,
    RATE_LIMIT,
    TRANSIENT,
    ProviderError,
)

_THINK = re.compile(r"<think>.*?</think>", flags=re.S | re.I)
_RETRY_HINT = re.compile(r"retry after\s+(\d+(?:\.\d+)?)\s*s", flags=re.I)
_QUOTA_HINTS = ("quota", "daily", "exhausted", "insufficient", "credits", "billing", "per day", "limit exceeded")
_JSON_MODE_HINTS = ("response_format", "json_object", "json mode", "json_schema")


# A rate limit that clears sooner than this is waited out; a longer one is treated as an exhausted quota.
MAX_RETRY_WAIT_SECONDS = 60.0


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class Provider(Protocol):
    name: str
    supports_json_mode: bool
    records_own_usage: bool

    def complete(self, prompt: str, json_mode: bool, timeout: float) -> Completion: ...


@dataclass(frozen=True)
class ProviderSpec:
    """An OpenAI-compatible chat-completions endpoint."""

    name: str
    chat_url: str
    model: str
    api_key: str | None = None
    requires_key: bool = True
    json_mode: bool = True
    temperature: float = 0.7
    # Reasoning models spend part of this on hidden thinking; a provider's own default can be as low as
    # 1500 and silently truncates JSON mid-string, so always ask for enough.
    max_tokens: int = 8192
    # A random seed per request defeats shared response caches (Pollinations answers identical requests from
    # one, which would hand every retry the same broken answer).
    send_seed: bool = False
    # Overrides the chain's request timeout for providers that are slow by nature (reasoning models).
    timeout_seconds: float | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(self.api_key) or not self.requires_key


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _retry_after_seconds(response: requests.Response) -> float | None:
    """Seconds to wait, from the Retry-After header or a 'Retry after 16s' hint in the body."""
    raw = response.headers.get("Retry-After")
    if raw:
        try:
            return max(float(raw), 0.0)
        except ValueError:
            pass
    match = _RETRY_HINT.search(response.text or "")
    return float(match.group(1)) if match else None


class HttpProvider:
    """Calls any OpenAI-compatible /chat/completions endpoint with ``requests``.

    No vendor SDK is needed: Groq, Gemini, Cloudflare Workers AI, OpenRouter and Pollinations all accept
    the same request. Errors are classified (see errors.py) so the chain can decide what to do next.
    """

    records_own_usage = False

    def __init__(self, spec: ProviderSpec, session: requests.Session | None = None) -> None:
        self.spec = spec
        self.name = spec.name
        self.supports_json_mode = spec.json_mode
        self.timeout_seconds = spec.timeout_seconds
        self._session = session or requests

    def complete(self, prompt: str, json_mode: bool, timeout: float) -> Completion:
        spec = self.spec
        headers = {"Content-Type": "application/json", **spec.extra_headers}
        if spec.api_key:
            headers["Authorization"] = f"Bearer {spec.api_key}"
        body: dict[str, Any] = {
            "model": spec.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": spec.temperature,
            "max_tokens": spec.max_tokens,
        }
        if spec.send_seed:
            body["seed"] = random.randint(1, 2**31 - 1)
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        try:
            response = self._session.post(spec.chat_url, headers=headers, json=body, timeout=(5, max(timeout, 1)))
        except requests.Timeout:
            raise ProviderError(TRANSIENT, f"timed out after {timeout:.0f}s") from None
        except requests.RequestException as exc:
            raise ProviderError(TRANSIENT, f"network error: {redact(str(exc), spec.api_key)[:200]}") from None

        if response.status_code >= 400:
            raise self._http_error(response)

        try:
            payload = response.json()
            choice = payload["choices"][0]
            text = choice["message"].get("content")
            finish_reason = choice.get("finish_reason")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ProviderError(BAD_OUTPUT, "response had no choices[0].message.content") from None
        if not isinstance(text, str) or not text.strip():
            raise ProviderError(BAD_OUTPUT, "empty completion")
        if finish_reason == "length":
            raise ProviderError(
                BAD_OUTPUT, f"answer truncated at {spec.max_tokens} tokens (finish_reason=length); raise LLM_MAX_OUTPUT_TOKENS"
            )

        usage = payload.get("usage") if isinstance(payload, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        return Completion(
            text=_THINK.sub("", text).strip(),
            model=str(payload.get("model") or spec.model),
            input_tokens=_int_or_none(usage.get("prompt_tokens")),
            output_tokens=_int_or_none(usage.get("completion_tokens")),
        )

    def _http_error(self, response: requests.Response) -> ProviderError:
        status = response.status_code
        snippet = redact(response.text or "", self.spec.api_key)[:200].replace("\n", " ")
        lowered = snippet.lower()
        if status in (401, 403):
            return ProviderError(AUTH, f"HTTP {status}: {snippet}", status)
        if status in (402, 429):
            # 429 is a rate limit. Some free tiers (Pollinations) answer 402 "FREE_LIMIT ... retry after 16s"
            # for the same thing, while a 402 with no retry hint really means "payment required".
            retry_after = _retry_after_seconds(response)
            quota_words = any(hint in lowered for hint in _QUOTA_HINTS)
            if retry_after is None and status == 402:
                return ProviderError(QUOTA, f"HTTP 402 payment required: {snippet}", status)
            if quota_words or (retry_after is not None and retry_after > MAX_RETRY_WAIT_SECONDS):
                return ProviderError(QUOTA, f"HTTP {status} quota: {snippet}", status, retry_after)
            return ProviderError(RATE_LIMIT, f"HTTP {status}: {snippet}", status, retry_after)
        if status == 400 and any(hint in lowered for hint in _JSON_MODE_HINTS):
            return ProviderError(JSON_MODE, f"HTTP 400: {snippet}", status)
        if status in (408, 409, 425) or status >= 500:
            return ProviderError(TRANSIENT, f"HTTP {status}: {snippet}", status, _retry_after_seconds(response))
        return ProviderError(BAD_REQUEST, f"HTTP {status}: {snippet}", status)


class OpenCodeCliProvider:
    """Adapter that lets the existing ``opencode`` CLI sit in the chain (the last, keyless resort)."""

    supports_json_mode = False
    records_own_usage = True  # OpenCodeClient._run_opencode already writes api_usage rows

    def __init__(self, client: Any) -> None:
        self.name = "opencode"
        self._client = client

    def complete(self, prompt: str, json_mode: bool, timeout: float) -> Completion:
        import time

        from ..opencode.client import OpenCodeError

        try:
            result = self._client._run_opencode([], prompt, time.monotonic(), None)
        except OpenCodeError as exc:
            detail = (exc.stderr or exc.stdout or str(exc))[:200].replace("\n", " ")
            raise ProviderError(TRANSIENT, f"{exc} {detail}".strip()) from None
        if not result.stdout.strip():
            raise ProviderError(BAD_OUTPUT, "empty completion")
        return Completion(text=result.stdout.strip(), model="opencode")
