from __future__ import annotations

import logging
import sys

from .settings import current_settings


def setup_logging(level: str | None = None) -> None:
    """Configure root logging once using the configured LOG_LEVEL."""
    if level is None:
        try:
            level = current_settings().log_level
        except ValueError:
            level = "INFO"
    numeric_level = getattr(logging, level.strip().upper(), None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    root = logging.getLogger()
    root.setLevel(numeric_level)
    if any(isinstance(handler, logging.StreamHandler) and handler.stream is sys.stderr for handler in root.handlers):
        return

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    handler.setLevel(numeric_level)
    root.addHandler(handler)
