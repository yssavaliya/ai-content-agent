from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_LOGS_DIR = "logs/prompts"


class PromptRecorder:
    """Persists rendered prompts and run metadata for inspection/debugging."""

    def __init__(self, logs_dir: str | Path = DEFAULT_LOGS_DIR) -> None:
        self.logs_dir = Path(logs_dir)

    @staticmethod
    def _sanitize(value: str) -> str:
        cleaned = "".join(c if c.isalnum() or c in "-_" else "_" for c in value)
        return cleaned or "unknown"

    def _stamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")

    def start(self, prompt: str, label: str, run_id: str | None = None) -> Path:
        """Write the prompt to disk and return the prompt file path."""
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        stamp = self._stamp()
        safe_label = self._sanitize(label or "agent")
        safe_run = self._sanitize(run_id or "no-run")
        path = self.logs_dir / f"{stamp}_{safe_run}_{safe_label}.txt"
        path.write_text(prompt, encoding="utf-8")
        return path

    def finish(
        self,
        prompt_path: Path,
        *,
        elapsed_seconds: float,
        exit_code: int,
        error: str | None = None,
        stdout_chars: int = 0,
        stderr_chars: int = 0,
    ) -> Path:
        """Write a JSON metadata sidecar next to the prompt file."""
        metadata: dict[str, Any] = {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "prompt_file": prompt_path.name,
            "prompt_chars": prompt_path.stat().st_size if prompt_path.exists() else 0,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "exit_code": exit_code,
            "stdout_chars": stdout_chars,
            "stderr_chars": stderr_chars,
            "error": error,
        }
        metadata_path = prompt_path.with_suffix(".json")
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return metadata_path
