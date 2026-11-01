from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def prompt_key(prompt: str, expect_json: bool) -> str:
    return hashlib.sha256(f"{prompt}\x00json={expect_json}".encode("utf-8")).hexdigest()


class LLMCache:
    """Disk cache of *validated* completions, keyed by prompt hash.

    It exists to make workflow re-runs and retries free: re-running a failed daily job the same day
    re-sends identical prompts. Entries expire after ``ttl_hours`` and are never written for output
    that failed validation. Every operation is best effort and never raises.
    """

    def __init__(self, directory: str | Path, ttl_hours: float = 24, enabled: bool = True, clock=time.time) -> None:
        self.directory = Path(directory)
        self.ttl_seconds = ttl_hours * 3600
        self.enabled = enabled
        self._clock = clock

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> dict | None:
        if not self.enabled:
            return None
        path = self._path(key)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            if self._clock() - float(entry["created_at"]) > self.ttl_seconds:
                path.unlink(missing_ok=True)
                return None
            return entry if isinstance(entry.get("text"), str) else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def put(self, key: str, text: str, provider: str, model: str) -> None:
        if not self.enabled:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            tmp = self._path(key).with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"created_at": self._clock(), "text": text, "provider": provider, "model": model}),
                encoding="utf-8",
            )
            os.replace(tmp, self._path(key))
        except OSError as exc:
            logger.debug("LLM cache write skipped: %s", exc)

    def evict(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError:
            pass

    def purge_expired(self) -> int:
        """Delete expired entries; returns how many were removed."""
        removed = 0
        if not self.directory.exists():
            return 0
        for path in self.directory.glob("*.json"):
            try:
                if self._clock() - float(json.loads(path.read_text(encoding="utf-8"))["created_at"]) > self.ttl_seconds:
                    path.unlink(missing_ok=True)
                    removed += 1
            except (OSError, ValueError, KeyError, TypeError):
                path.unlink(missing_ok=True)
                removed += 1
        return removed
