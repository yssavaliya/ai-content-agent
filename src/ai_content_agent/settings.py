from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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

    # Optional integrations
    openai_api_key: str | None = None
    opencode_timeout_seconds: int = 60
    openai_model: str = "gpt-image-1"
    openai_max_retries: int = 3
    openai_request_timeout_seconds: int = 60

    # Primary LLM engine for agents: "openai" (fast, via OPENAI_API_KEY) or "opencode".
    # The other engine is used as a fallback when the primary is unavailable or fails.
    llm_provider: str = "openai"

    # OpenAI text fallback (used when opencode is unavailable or fails)
    openai_text_model: str = "gpt-4o-mini"
    openai_text_fallback_enabled: bool = True

    # Instagram publishing
    instagram_access_token: str | None = None
    instagram_account_id: str | None = None
    instagram_api_version: str = "21.0"
    instagram_publish_enabled: bool = False
    instagram_analytics_enabled: bool = False

    # Media hosting (public URL required by the Instagram Graph API)
    media_host: str = "none"
    media_host_repo: str | None = None
    media_host_token: str | None = None
    media_host_branch: str = "main"
    media_host_path: str = "images"

    # Notifications
    notify_channels: tuple[str, ...] = ("dryrun",)
    discord_webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    slack_webhook_url: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_to: str | None = None
    notify_smtp_tls: bool = True

    # Scientist / learning
    scientist_min_sample_size: int = 10
    scientist_min_effect: float = 0.15
    scientist_apply_threshold: float = 0.6
    scientist_max_recommendations: int = 5


def _parse_bool(value: str, name: str = "INSTAGRAM_ENABLED") -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for {name}: '{value}'")


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ("dryrun",)
    items = (item.strip().strip("\"'") for item in value.split(",") if item.strip())
    return tuple(item.lower() for item in items if item)


def _parse_int(value: str | None, default: int, name: str) -> int:
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Invalid integer value for {name}: '{value}'") from None


def _parse_float(value: str | None, default: float, name: str) -> float:
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"Invalid numeric value for {name}: '{value}'") from None


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

    def get(name: str) -> str | None:
        return env.get(name, "").strip() or None

    def get_provider() -> str:
        provider = (get("LLM_PROVIDER") or "openai").strip().lower()
        if provider not in {"openai", "opencode"}:
            raise ValueError(
                f"Invalid value for LLM_PROVIDER: '{provider}' (expected 'openai' or 'opencode')"
            )
        return provider

    return Settings(
        log_level=env["LOG_LEVEL"].strip(),
        database_path=env["DATABASE_PATH"].strip(),
        opencode_command=env["OPENCODE_COMMAND"].strip(),
        instagram_enabled=_parse_bool(env["INSTAGRAM_ENABLED"]),
        image_provider=env["IMAGE_PROVIDER"].strip(),
        openai_api_key=get("OPENAI_API_KEY"),
        llm_provider=get_provider(),
        opencode_timeout_seconds=_parse_int(get("OPENCODE_TIMEOUT_SECONDS"), 60, "OPENCODE_TIMEOUT_SECONDS"),
        openai_model=get("OPENAI_MODEL") or "gpt-image-1",
        openai_max_retries=_parse_int(get("OPENAI_MAX_RETRIES"), 3, "OPENAI_MAX_RETRIES"),
        openai_request_timeout_seconds=_parse_int(
            get("OPENAI_REQUEST_TIMEOUT_SECONDS"), 60, "OPENAI_REQUEST_TIMEOUT_SECONDS"
        ),
        openai_text_model=get("OPENAI_TEXT_MODEL") or "gpt-4o-mini",
        openai_text_fallback_enabled=_parse_bool(
            get("OPENAI_TEXT_FALLBACK_ENABLED") or "true", "OPENAI_TEXT_FALLBACK_ENABLED"
        ),
        instagram_access_token=get("INSTAGRAM_ACCESS_TOKEN"),
        instagram_account_id=get("INSTAGRAM_ACCOUNT_ID"),
        instagram_api_version=get("INSTAGRAM_API_VERSION") or "21.0",
        instagram_publish_enabled=_parse_bool(
            get("INSTAGRAM_PUBLISH_ENABLED") or "false", "INSTAGRAM_PUBLISH_ENABLED"
        ),
        instagram_analytics_enabled=_parse_bool(
            get("INSTAGRAM_ANALYTICS_ENABLED") or "false", "INSTAGRAM_ANALYTICS_ENABLED"
        ),
        media_host=(get("MEDIA_HOST") or "none").strip().lower(),
        media_host_repo=get("MEDIA_HOST_REPO"),
        media_host_token=get("MEDIA_HOST_TOKEN"),
        media_host_branch=get("MEDIA_HOST_BRANCH") or "main",
        media_host_path=get("MEDIA_HOST_PATH") or "images",
        notify_channels=_parse_csv(get("NOTIFY_CHANNELS")),
        discord_webhook_url=get("DISCORD_WEBHOOK_URL"),
        telegram_bot_token=get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=get("TELEGRAM_CHAT_ID"),
        slack_webhook_url=get("SLACK_WEBHOOK_URL"),
        smtp_host=get("SMTP_HOST"),
        smtp_port=_parse_int(get("SMTP_PORT"), 587, "SMTP_PORT"),
        smtp_user=get("SMTP_USER"),
        smtp_password=get("SMTP_PASSWORD"),
        smtp_from=get("SMTP_FROM"),
        smtp_to=get("SMTP_TO"),
        notify_smtp_tls=_parse_bool(get("NOTIFY_SMTP_TLS") or "true", "NOTIFY_SMTP_TLS"),
        scientist_min_sample_size=_parse_int(
            get("SCIENTIST_MIN_SAMPLE_SIZE"), 10, "SCIENTIST_MIN_SAMPLE_SIZE"
        ),
        scientist_min_effect=_parse_float(get("SCIENTIST_MIN_EFFECT"), 0.15, "SCIENTIST_MIN_EFFECT"),
        scientist_apply_threshold=_parse_float(
            get("SCIENTIST_APPLY_THRESHOLD"), 0.6, "SCIENTIST_APPLY_THRESHOLD"
        ),
        scientist_max_recommendations=_parse_int(
            get("SCIENTIST_MAX_RECOMMENDATIONS"), 5, "SCIENTIST_MAX_RECOMMENDATIONS"
        ),
    )


def current_settings() -> Settings:
    return load_settings()
