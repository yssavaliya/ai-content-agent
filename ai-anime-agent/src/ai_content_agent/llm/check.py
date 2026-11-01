from __future__ import annotations

import time
from dataclasses import dataclass

from .chain import is_json_object
from .errors import JSON_MODE, ProviderError
from .providers import Provider
from .registry import ProviderStatus

PING_PROMPT = 'Reply with only this JSON object and nothing else: {"ok": true}'


@dataclass(frozen=True)
class CheckRow:
    provider: str
    model: str
    status: str  # ok | failed | not configured
    latency_ms: int | None
    detail: str


def check_provider(provider: Provider, timeout: float = 30.0) -> CheckRow:
    """One real request to the provider (no fallback), so a broken key or model shows up by name."""
    json_mode = provider.supports_json_mode
    started = time.monotonic()
    for _ in range(2):
        try:
            completion = provider.complete(PING_PROMPT, json_mode, timeout)
        except ProviderError as exc:
            if exc.kind == JSON_MODE and json_mode:
                json_mode = False
                continue
            return CheckRow(provider.name, "-", "failed", int((time.monotonic() - started) * 1000), f"{exc.kind}: {exc}")
        latency = int((time.monotonic() - started) * 1000)
        valid = is_json_object(completion.text)
        return CheckRow(
            provider.name,
            completion.model,
            "ok" if valid else "failed",
            latency,
            "valid JSON" if valid else f"answered but not JSON: {completion.text[:60]!r}",
        )
    return CheckRow(provider.name, "-", "failed", None, "json mode retry loop")


def run_check(
    providers: list[Provider],
    statuses: list[ProviderStatus],
    timeout: float = 30.0,
    skipped: dict[str, str] | None = None,
) -> list[CheckRow]:
    skipped = skipped or {}
    rows = [CheckRow(s.name, s.model, "not configured", None, s.reason) for s in statuses if not s.configured]
    rows += [CheckRow(s.name, s.model, "skipped", None, skipped[s.name]) for s in statuses if s.name in skipped]
    by_name = {p.name: p for p in providers}
    for status in statuses:
        if status.configured and status.name in by_name and status.name not in skipped:
            rows.append(check_provider(by_name[status.name], timeout))
    order = {s.name: i for i, s in enumerate(statuses)}
    return sorted(rows, key=lambda row: order.get(row.provider, 99))


def render_text(rows: list[CheckRow]) -> str:
    lines = [f"{'provider':<13}{'status':<16}{'latency':>9}  model / detail"]
    for row in rows:
        latency = "-" if row.latency_ms is None else f"{row.latency_ms} ms"
        lines.append(f"{row.provider:<13}{row.status:<16}{latency:>9}  {row.model if row.status == 'ok' else row.detail}")
    return "\n".join(lines)


def render_markdown(rows: list[CheckRow]) -> str:
    lines = ["| Provider | Status | Latency | Model | Detail |", "| --- | --- | --- | --- | --- |"]
    for row in rows:
        icon = {"ok": "✅", "failed": "❌", "not configured": "➖", "skipped": "⏭️"}[row.status]
        latency = "-" if row.latency_ms is None else f"{row.latency_ms} ms"
        detail = row.detail.replace("|", "/")[:140]
        lines.append(f"| {row.provider} | {icon} {row.status} | {latency} | {row.model} | {detail} |")
    return "\n".join(lines)
