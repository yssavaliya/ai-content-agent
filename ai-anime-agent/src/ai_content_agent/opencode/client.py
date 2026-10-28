from __future__ import annotations

import json
import logging
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ..settings import Settings, current_settings
from .context import get_run_id
from .recorder import PromptRecorder

logger = logging.getLogger(__name__)

_EXHAUSTED_PROVIDERS: set[str] = set()


def reset_exhausted_providers() -> None:
    _EXHAUSTED_PROVIDERS.clear()


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


def extract_json_text(text: str) -> str:
    """Parse leniently: strip fences, then fall back to the first {...} block."""
    text = strip_markdown_fences(text)
    try:
        json.loads(text)
        return text
    except (json.JSONDecodeError, ValueError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            json.loads(candidate)
            return candidate
        except (json.JSONDecodeError, ValueError):
            pass
    return text


class OpenCodeClient:
    def __init__(
        self,
        timeout_seconds: int | None = None,
        command: str | None = None,
        recorder: PromptRecorder | None = None,
        openai_client: Any | None = None,
        gemini_client: Any | None = None,
    ) -> None:
        try:
            self._settings: Settings | None = current_settings()
        except ValueError:
            self._settings = None
        self.timeout_seconds = timeout_seconds or (self._settings.opencode_timeout_seconds if self._settings else 60)
        self.command = command or (self._settings.opencode_command if self._settings else "opencode")
        self.recorder = recorder or PromptRecorder()
        self._openai_client = openai_client
        self._gemini_client = gemini_client

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
                "::notice::[LLM:%s] Prompt sent (%d chars): %s...",
                label or "agent",
                len(input_text),
                prompt_preview,
            )
            prompt_path = self.recorder.start(input_text, label or "agent", run_id)

        tried_api = False
        try:
            if input_text is not None:
                provider = self._settings.llm_provider if self._settings else "opencode"
                if provider in ("openai", "gemini"):
                    tried_api = True
                    result = self._try_chat_api(provider, input_text, label, start, prompt_path, primary=True)
                    if result is not None:
                        return result
                    other = "gemini" if provider == "openai" else "openai"
                    result = self._try_chat_api(other, input_text, label, start, prompt_path, primary=False)
                    if result is not None:
                        return result
                    logger.warning("API LLM providers unavailable; falling back to opencode")
                    return self._run_opencode(args, input_text, start, prompt_path)
            return self._run_opencode(args, input_text, start, prompt_path)
        except OpenCodeError:
            if not tried_api and input_text is not None:
                fallback = self._try_chat_api("openai", input_text, label, start, prompt_path, primary=False)
                if fallback is not None:
                    return fallback
                fallback = self._try_chat_api("gemini", input_text, label, start, prompt_path, primary=False)
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
        if "opencode" in _EXHAUSTED_PROVIDERS:
            raise OpenCodeError("OpenCode provider circuit broken due to previous failure", -1, "", "")
        # Use 'run' subcommand for non-interactive execution (much faster than TUI)
        # If input_text provided, use it as the prompt; otherwise use args.
        # On Windows the prompt is piped via stdin because cmd.exe shims mangle
        # long or quoted prompt arguments.
        use_stdin = input_text is not None and sys.platform == "win32"
        if input_text is not None:
            command_line = [self.command, "run"] if use_stdin else [self.command, "run", input_text]
        else:
            command_line = [self.command, *args]
        logger.debug("Running opencode: %s", shlex.join(command_line))
        command_line = self._resolve_windows_command(command_line)
        popen_command = command_line if isinstance(command_line, str) else [str(part) for part in command_line]

        try:
            process = subprocess.Popen(
                popen_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
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
            stdout, stderr = process.communicate(
                input=input_text if use_stdin else None,
                timeout=self.timeout_seconds,
            )
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
            err_lower = (stderr or stdout or "").lower()
            if any(term in err_lower for term in ("unexpected server error", "listen eaddrinuse", "econnrefused", "unknownerror")):
                _EXHAUSTED_PROVIDERS.add("opencode")
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

    def _resolve_windows_command(self, command_line: list[str]) -> list[str] | str:
        """Resolve npm-style .cmd/.bat shims so they launch on Windows."""
        if sys.platform != "win32":
            return command_line
        resolved = shutil.which(self.command)
        if resolved is None:
            return command_line
        if resolved.lower().endswith((".cmd", ".bat")):
            rest = subprocess.list2cmdline(command_line[1:]) if len(command_line) > 1 else ""
            return f'cmd.exe /d /c call "{resolved}"' + (f" {rest}" if rest else "")
        return [resolved, *command_line[1:]]

    def _chat_client_for(self, provider: str) -> Any:
        settings = self._settings
        if provider == "openai":
            if self._openai_client is not None:
                return self._openai_client
            from openai import OpenAI

            return OpenAI(
                api_key=settings.openai_api_key,
                timeout=settings.openai_request_timeout_seconds,
                max_retries=settings.openai_max_retries,
            )
        if provider == "gemini":
            if self._gemini_client is not None:
                return self._gemini_client
            from openai import OpenAI

            return OpenAI(
                api_key=settings.gemini_api_key,
                base_url=settings.gemini_base_url,
                timeout=settings.openai_request_timeout_seconds,
                max_retries=settings.openai_max_retries,
            )
        raise ValueError(f"Unknown chat API provider: {provider!r}")

    def _try_chat_api(
        self,
        provider: str,
        input_text: str | None,
        label: str | None,
        start: float,
        prompt_path: Path | None,
        primary: bool,
    ) -> OpenCodeResult | None:
        if input_text is None:
            return None
        if provider in _EXHAUSTED_PROVIDERS:
            logger.warning("LLM provider %s is marked exhausted / out of quota; skipping", provider)
            return None
        settings = self._settings
        if settings is None or not settings.openai_text_fallback_enabled:
            logger.warning("LLM chat APIs are disabled (OPENAI_TEXT_FALLBACK_ENABLED=false)")
            return None
        if provider == "openai" and not settings.openai_api_key:
            logger.warning("OPENAI_API_KEY is unset; OpenAI chat unavailable")
            return None
        if provider == "gemini" and not settings.gemini_api_key:
            logger.warning("GEMINI_API_KEY is unset; Gemini chat unavailable")
            return None
        model = settings.openai_text_model if provider == "openai" else settings.gemini_model
        display = "OpenAI" if provider == "openai" else "Gemini"

        try:
            client = self._chat_client_for(provider)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": input_text}],
            )
            content = (response.choices[0].message.content or "").strip()
        except Exception as exc:
            err_msg = str(exc).lower()
            if any(term in err_msg for term in ("insufficient_quota", "credits remaining", "billing", "quota_exceeded", "resource_exhausted", "credit_balance_exhausted", "rate_limit", "429")):
                logger.error("%s quota exhausted or out of credits (%s); disabling for session", display, exc)
                _EXHAUSTED_PROVIDERS.add(provider)
            else:
                logger.error("%s chat failed for %s: %s", display, label or "agent", exc)
            return None

        elapsed = time.monotonic() - start
        if primary:
            logger.info(
                "::notice::[%s] %s answered via %s (%d chars, %.1fs)",
                display,
                label or "agent",
                model,
                len(content),
                elapsed,
            )
        else:
            logger.info(
                "::notice::[Fallback] primary LLM failed; used %s %s for %s (%d chars)",
                display,
                model,
                label or "agent",
                len(content),
            )
        if prompt_path is not None:
            self.recorder.finish(
                prompt_path,
                elapsed_seconds=elapsed,
                exit_code=0,
                error=provider if primary else f"fallback:{provider}",
                stdout_chars=len(content),
            )
        return OpenCodeResult(
            stdout=strip_markdown_fences(content),
            stderr="",
            exit_code=0,
            elapsed_seconds=elapsed,
        )
