from __future__ import annotations

import logging
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ..settings import Settings, current_settings
from .context import get_run_id
from .recorder import PromptRecorder

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


def strip_markdown_fences(text: str) -> str:
    """Remove a surrounding ```json ... ``` code fence, if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


class OpenCodeClient:
    def __init__(
        self,
        timeout_seconds: int | None = None,
        command: str | None = None,
        recorder: PromptRecorder | None = None,
        openai_client: Any | None = None,
    ) -> None:
        try:
            self._settings: Settings | None = current_settings()
        except ValueError:
            self._settings = None
        self.timeout_seconds = timeout_seconds or (self._settings.opencode_timeout_seconds if self._settings else 60)
        self.command = command or (self._settings.opencode_command if self._settings else "opencode")
        self.recorder = recorder or PromptRecorder()
        self._openai_client = openai_client

    def run(
        self,
        args: Sequence[str],
        input_text: str | None = None,
        label: str | None = None,
    ) -> OpenCodeResult:
        start = time.monotonic()
        run_id = get_run_id()
        prompt_path: Path | None = None
        if input_text is not None:
            prompt_preview = " ".join(input_text.split())[:300]
            logger.info(
                "::notice::[OpenCode:%s] Prompt sent (%d chars): %s...",
                label or "agent",
                len(input_text),
                prompt_preview,
            )
            prompt_path = self.recorder.start(input_text, label or "agent", run_id)

        try:
            if input_text is not None:
                provider = self._settings.llm_provider if self._settings else "opencode"
                if provider == "openai":
                    result = self._try_openai(input_text, label, start, prompt_path, primary=True)
                    if result is not None:
                        return result
                    logger.warning("OpenAI chat unavailable; falling back to opencode")
                    return self._run_opencode(args, input_text, start, prompt_path)
            return self._run_opencode(args, input_text, start, prompt_path)
        except OpenCodeError:
            fallback = self._try_openai(input_text, label, start, prompt_path, primary=False)
            if fallback is not None:
                return fallback
            raise

    def _run_opencode(
        self,
        args: Sequence[str],
        input_text: str | None,
        start: float,
        prompt_path: Path | None,
    ) -> OpenCodeResult:
        # Use 'run' subcommand for non-interactive execution (much faster than TUI)
        # If input_text provided, use it as the prompt; otherwise use args
        if input_text is not None:
            command_line = [self.command, "run", input_text]
        else:
            command_line = [self.command, *args]
        logger.debug("Running opencode: %s", shlex.join(command_line))

        try:
            process = subprocess.Popen(
                [str(part) for part in command_line],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            logger.error("opencode binary not found at %r", self.command)
            if prompt_path is not None:
                self.recorder.finish(
                    prompt_path,
                    elapsed_seconds=time.monotonic() - start,
                    exit_code=-1,
                    error=f"opencode binary not found: {self.command}",
                )
            raise OpenCodeError(
                f"OpenCode binary not found: {self.command!r}",
                -1,
                "",
                str(exc),
            ) from exc

        heartbeat_stop = threading.Event()

        def heartbeat():
            while not heartbeat_stop.is_set():
                heartbeat_stop.wait(30)
                if not heartbeat_stop.is_set():
                    elapsed = time.monotonic() - start
                    logger.info(
                        "::notice::[OpenCode] Still running... %.0fs elapsed (timeout=%ds)",
                        elapsed,
                        self.timeout_seconds,
                    )

        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()

        try:
            stdout, stderr = process.communicate(input=None, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1)
            process.kill()
            stdout, stderr = process.communicate()
            elapsed = time.monotonic() - start
            logger.error("opencode timed out after %ss (exit=%s)", self.timeout_seconds, -1)
            if prompt_path is not None:
                self.recorder.finish(
                    prompt_path,
                    elapsed_seconds=elapsed,
                    exit_code=-1,
                    error="timeout",
                    stdout_chars=len(stdout or ""),
                    stderr_chars=len(stderr or ""),
                )
            raise OpenCodeError(
                "OpenCode command timed out",
                -1,
                stdout or "",
                stderr or "",
            )
        else:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1)

        elapsed = time.monotonic() - start
        if process.returncode != 0:
            logger.error(
                "opencode failed (exit=%s) after %.2fs: %s",
                process.returncode,
                elapsed,
                (stderr or stdout or "")[:500],
            )
            if prompt_path is not None:
                self.recorder.finish(
                    prompt_path,
                    elapsed_seconds=elapsed,
                    exit_code=process.returncode,
                    error=(stderr or stdout or "")[:500],
                    stdout_chars=len(stdout or ""),
                    stderr_chars=len(stderr or ""),
                )
            raise OpenCodeError(
                f"OpenCode command failed with exit code {process.returncode}",
                process.returncode,
                stdout or "",
                stderr or "",
            )
        logger.debug("opencode succeeded (exit=0) after %.2fs", elapsed)
        if prompt_path is not None:
            self.recorder.finish(
                prompt_path,
                elapsed_seconds=elapsed,
                exit_code=process.returncode,
                stdout_chars=len(stdout or ""),
                stderr_chars=len(stderr or ""),
            )
        return OpenCodeResult(
            stdout=stdout or "",
            stderr=stderr or "",
            exit_code=process.returncode,
            elapsed_seconds=elapsed,
        )

    def _try_openai(
        self,
        input_text: str | None,
        label: str | None,
        start: float,
        prompt_path: Path | None,
        primary: bool,
    ) -> OpenCodeResult | None:
        if input_text is None:
            return None
        settings = self._settings
        if settings is None or not settings.openai_text_fallback_enabled:
            logger.warning("OpenAI chat is disabled (OPENAI_TEXT_FALLBACK_ENABLED=false)")
            return None
        if not settings.openai_api_key:
            logger.warning("OPENAI_API_KEY is unset; OpenAI chat unavailable")
            return None

        try:
            if self._openai_client is not None:
                client = self._openai_client
            else:
                from openai import OpenAI

                client = OpenAI(
                    api_key=settings.openai_api_key,
                    timeout=settings.openai_request_timeout_seconds,
                    max_retries=settings.openai_max_retries,
                )
            response = client.chat.completions.create(
                model=settings.openai_text_model,
                messages=[{"role": "user", "content": input_text}],
            )
            content = (response.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.error("OpenAI chat failed for %s: %s", label or "agent", exc)
            return None

        elapsed = time.monotonic() - start
        if primary:
            logger.info(
                "::notice::[OpenAI] %s answered via %s (%d chars, %.1fs)",
                label or "agent",
                settings.openai_text_model,
                len(content),
                elapsed,
            )
        else:
            logger.info(
                "::notice::[Fallback] opencode failed; used OpenAI %s for %s (%d chars)",
                settings.openai_text_model,
                label or "agent",
                len(content),
            )
        if prompt_path is not None:
            self.recorder.finish(
                prompt_path,
                elapsed_seconds=elapsed,
                exit_code=0,
                error="openai" if primary else "fallback:openai",
                stdout_chars=len(content),
            )
        return OpenCodeResult(
            stdout=strip_markdown_fences(content),
            stderr="",
            exit_code=0,
            elapsed_seconds=elapsed,
        )
