from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import requests

from ..redaction import redact
from ..settings import Settings

logger = logging.getLogger(__name__)

MAX_BODY_LENGTH = 3000


def _truncate(text: str, limit: int = MAX_BODY_LENGTH) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


class NotificationError(RuntimeError):
    pass


class NotificationChannel(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def send(self, subject: str, body: str, metadata: dict[str, Any]) -> None:
        raise NotImplementedError


class DryRunChannel(NotificationChannel):
    @property
    def name(self) -> str:
        return "dryrun"

    def send(self, subject: str, body: str, metadata: dict[str, Any]) -> None:
        logger.info("NOTIFY[dryrun] %s\n%s", subject, _truncate(body))


class DiscordChannel(NotificationChannel):
    @property
    def name(self) -> str:
        return "discord"

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(self, subject: str, body: str, metadata: dict[str, Any]) -> None:
        color = metadata.get("color", 3447003)
        payload = {
            "embeds": [
                {
                    "title": _truncate(subject, 256),
                    "description": _truncate(body),
                    "color": color,
                }
            ]
        }
        try:
            response = requests.post(self.webhook_url, json=payload, timeout=30)
        except requests.RequestException as exc:
            raise NotificationError(f"Discord request failed: {redact(str(exc), self.webhook_url)}") from None
        if response.status_code >= 400:
            raise NotificationError(f"Discord webhook error ({response.status_code}): {response.text[:300]}")


class TelegramChannel(NotificationChannel):
    @property
    def name(self) -> str:
        return "telegram"

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, subject: str, body: str, metadata: dict[str, Any]) -> None:
        text = f"{subject}\n\n{_truncate(body)}"
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise NotificationError(f"Telegram request failed: {redact(str(exc), self.bot_token)}") from None
        if response.status_code >= 400:
            raise NotificationError(f"Telegram error ({response.status_code}): {response.text[:300]}")


class SlackChannel(NotificationChannel):
    @property
    def name(self) -> str:
        return "slack"

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(self, subject: str, body: str, metadata: dict[str, Any]) -> None:
        try:
            response = requests.post(
                self.webhook_url,
                json={"text": f"*{subject}*\n{_truncate(body)}"},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise NotificationError(f"Slack request failed: {redact(str(exc), self.webhook_url)}") from None
        if response.status_code >= 400:
            raise NotificationError(f"Slack webhook error ({response.status_code}): {response.text[:300]}")


def build_channels(settings: Settings) -> list[NotificationChannel]:
    channels: list[NotificationChannel] = []
    for channel_name in settings.notify_channels:
        if channel_name == "dryrun":
            channels.append(DryRunChannel())
        elif channel_name == "discord":
            if settings.discord_webhook_url:
                channels.append(DiscordChannel(settings.discord_webhook_url))
            else:
                logger.warning("NOTIFY_CHANNELS includes discord but DISCORD_WEBHOOK_URL is unset")
        elif channel_name == "telegram":
            if settings.telegram_bot_token and settings.telegram_chat_id:
                channels.append(TelegramChannel(settings.telegram_bot_token, settings.telegram_chat_id))
            else:
                logger.warning("NOTIFY_CHANNELS includes telegram but TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are unset")
        elif channel_name == "slack":
            if settings.slack_webhook_url:
                channels.append(SlackChannel(settings.slack_webhook_url))
            else:
                logger.warning("NOTIFY_CHANNELS includes slack but SLACK_WEBHOOK_URL is unset")
        else:
            logger.warning("Unknown notification channel in NOTIFY_CHANNELS: %s", channel_name)
    if not channels:
        logger.warning("No usable notification channel configured; falling back to dryrun (log only)")
        channels.append(DryRunChannel())
    return channels
