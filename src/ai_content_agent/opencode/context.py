from __future__ import annotations

import contextvars
from typing import Optional

_run_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "ai_content_agent_run_id", default=None
)


def set_run_id(run_id: Optional[str]) -> None:
    """Set the current pipeline run id for prompt/log correlation."""
    _run_id.set(run_id)


def get_run_id() -> Optional[str]:
    """Return the current pipeline run id, or None when unset."""
    return _run_id.get()
