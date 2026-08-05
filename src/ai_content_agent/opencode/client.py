from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..settings import current_settings


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
    def __init__(self, timeout_seconds: int = 60) -> None:
        self.timeout_seconds = timeout_seconds
        self.command = current_settings().opencode_command

    def run(self, args: Sequence[str], input_text: str | None = None) -> OpenCodeResult:
        command_line = [self.command, *args]
        start = time.monotonic()
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
            raise OpenCodeError(
                "OpenCode command timed out",
                -1,
                stdout or "",
                stderr or "",
            )
        elapsed = time.monotonic() - start
        if process.returncode != 0:
            raise OpenCodeError(
                f"OpenCode command failed with exit code {process.returncode}",
                process.returncode,
                stdout or "",
                stderr or "",
            )
        return OpenCodeResult(
            stdout=stdout or "",
            stderr=stderr or "",
            exit_code=process.returncode,
            elapsed_seconds=elapsed,
        )
