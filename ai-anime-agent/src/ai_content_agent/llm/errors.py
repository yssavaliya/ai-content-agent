from __future__ import annotations

from dataclasses import dataclass

# Failure classes and what the chain does about them:
#   transient          network error, timeout, HTTP 5xx          -> retry with backoff, then next provider
#   rate_limit         HTTP 429 that clears quickly              -> wait (capped), retry, then next provider
#   quota              daily/monthly quota or credits exhausted  -> skip provider for the rest of the run
#   auth               HTTP 401/403, missing/invalid key         -> skip provider for the rest of the run
#   bad_request        HTTP 400/404 (e.g. model not found)       -> skip provider for the rest of the run
#   json_mode          provider rejects response_format          -> retry once without JSON mode
#   bad_output         empty or non-JSON answer                  -> next provider (same provider is not retried)
TRANSIENT = "transient"
RATE_LIMIT = "rate_limit"
QUOTA = "quota"
AUTH = "auth"
BAD_REQUEST = "bad_request"
JSON_MODE = "json_mode"
BAD_OUTPUT = "bad_output"


class ProviderError(RuntimeError):
    def __init__(self, kind: str, message: str, status: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True)
class Attempt:
    provider: str
    kind: str
    message: str


class AllProvidersFailed(RuntimeError):
    """Every provider in the chain failed or was skipped. Callers fall back to local templates."""

    def __init__(self, attempts: list[Attempt]) -> None:
        self.attempts = attempts
        detail = "; ".join(f"{a.provider}: {a.kind} ({a.message})" for a in attempts) or "no provider configured"
        super().__init__(f"All LLM providers failed: {detail}")
