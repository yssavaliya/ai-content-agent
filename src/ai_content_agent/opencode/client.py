from __future__ import annotations

import logging
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Sequence

from ..settings import current_settings

logger = logging.getLogger(__name__)


class OpenCodeError(RuntimeError):
    def __init__(self, message: str, exit_code: int, stdout: str, stderr: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


@dataclass(frozen=True)
class OpenCodeResult:
    stdout: str
    stderr: str
    exit_code: int
    elapsed_seconds: float


class OpenCodeClient:
    def __init__(self, timeout_seconds: int | None = None, command: str | None = None) -> None:
        settings = current_settings()
        self.timeout_seconds = timeout_seconds or settings.opencode_timeout_seconds
        self.command = command or settings.opencode_command

    def run(self, args: Sequence[str], input_text: str | None = None) -> OpenCodeResult:
        command_line = [self.command, *args]
        start = time.monotonic()
        logger.debug("Running opencode: %s", shlex.join(command_line))
        process = subprocess.Popen(
            [str(part) for part in command_line],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(input=input_text, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            elapsed = time.monotonic() - start
            logger.error("opencode timed out after %ss (exit=%s)", self.timeout_seconds, -1)
            raise OpenCodeError(
                "OpenCode command timed out",
                -1,
                stdout or "",
                stderr or "",
            )
        elapsed = time.monotonic() - start
        if process.returncode != 0:
            logger.error(
                "opencode failed (exit=%s) after %.2fs: %s",
                process.returncode,
                elapsed,
                (stderr or stdout or "")[:500],
            )
            raise OpenCodeError(
                f"OpenCode command failed with exit code {process.returncode}",
                process.returncode,
                stdout or "",
                stderr or "",
            )
        logger.debug("opencode succeeded (exit=0) after %.2fs", elapsed)
        return OpenCodeResult(
            stdout=stdout or "",
            stderr=stderr or "",
            exit_code=process.returncode,
            elapsed_seconds=elapsed,
        )
