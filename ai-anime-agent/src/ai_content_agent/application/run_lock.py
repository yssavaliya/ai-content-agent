from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from ..timestamps import utc_now_iso

logger = logging.getLogger(__name__)


class RunLockError(RuntimeError):
    pass


class RunLock:
    """Cross-platform advisory lock via an exclusive lock file.

    Prevents overlapping scheduled runs from racing on the shared SQLite
    database. A lock left behind by a crashed process is broken after
    ``stale_seconds`` using the file's modification time.
    """

    def __init__(
        self,
        lock_path: str | Path,
        timeout_seconds: float = 30,
        stale_seconds: float = 600,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.timeout_seconds = timeout_seconds
        self.stale_seconds = stale_seconds
        self._held = False

    def acquire(self) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        delay = 0.25
        while True:
            try:
                fd = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
            except FileExistsError:
                if self._is_stale():
                    logger.warning("Removing stale run lock %s", self.lock_path)
                    self._remove()
                    continue
                if time.monotonic() >= deadline:
                    raise RunLockError(
                        f"Another run is in progress (lock {self.lock_path} held beyond "
                        f"{self.timeout_seconds:.0f}s)"
                    ) from None
                time.sleep(delay)
                continue
            except OSError as exc:
                raise RunLockError(f"Could not create run lock {self.lock_path}: {exc}") from exc

            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"pid={os.getpid()} created_at={utc_now_iso()}\n")
            self._held = True
            logger.debug("Acquired run lock %s", self.lock_path)
            return

    def release(self) -> None:
        if not self._held:
            return
        self._remove()
        self._held = False
        logger.debug("Released run lock %s", self.lock_path)

    def _remove(self) -> None:
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _is_stale(self) -> bool:
        try:
            age = time.time() - self.lock_path.stat().st_mtime
            return age > self.stale_seconds
        except OSError:
            return False

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()


def lock_path_for_database(database_path: str) -> Path:
    """Places the lock next to the database file so concurrent runners contend."""
    path = Path(database_path)
    return path.parent / f"{path.name}.lock"
