from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_SETTINGS = [
    "LOG_LEVEL",
    "DATABASE_PATH",
    "OPENCODE_COMMAND",
    "INSTAGRAM_ENABLED",
    "IMAGE_PROVIDER",
]


@dataclass(frozen=True)
class Settings:
    log_level: str
    database_path: str
    opencode_command: str
    instagram_enabled: bool
    image_provider: str


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for INSTAGRAM_ENABLED: '{value}'")


def _load_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    with env_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, value = map(str.strip, stripped.split("=", 1))
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            values[key] = value
    return values


def load_settings(env: dict[str, str] | None = None, env_file: str | Path | None = None) -> Settings:
    if env is None:
        env = dict(os.environ)

    if env_file is None:
        env_file = Path(".env")

    env_path = Path(env_file)
    if env_path.exists():
        env = {**_load_env_file(env_path), **env}

    missing = [key for key in REQUIRED_SETTINGS if key not in env or env[key] == ""]
    if missing:
        raise ValueError(f"Missing required configuration values: {', '.join(missing)}")

    return Settings(
        log_level=env["LOG_LEVEL"].strip(),
        database_path=env["DATABASE_PATH"].strip(),
        opencode_command=env["OPENCODE_COMMAND"].strip(),
        instagram_enabled=_parse_bool(env["INSTAGRAM_ENABLED"]),
        image_provider=env["IMAGE_PROVIDER"].strip(),
    )


def current_settings() -> Settings:
    return load_settings()
