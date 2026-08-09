from __future__ import annotations

import logging
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
from typing import Any

import requests

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
        response = requests.post(self.webhook_url, json=payload, timeout=30)
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
        response = requests.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={"chat_id": self.chat_id, "text": text},
            timeout=30,
        )
        if response.status_code >= 400:
            raise NotificationError(f"Telegram error ({response.status_code}): {response.text[:300]}")


class SlackChannel(NotificationChannel):
    @property
    def name(self) -> str:
        return "slack"

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(self, subject: str, body: str, metadata: dict[str, Any]) -> None:
        response = requests.post(
            self.webhook_url,
            json={"text": f"*{subject}*\n{_truncate(body)}"},
            timeout=30,
        )
        if response.status_code >= 400:
            raise NotificationError(f"Slack webhook error ({response.status_code}): {response.text[:300]}")


class EmailChannel(NotificationChannel):
    @property
    def name(self) -> str:
        return "email"

    def __init__(
        self,
        host: str,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        from_address: str | None = None,
        to_addresses: str | None = None,
        use_tls: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_address = from_address or username or ""
        self.to_addresses = [addr.strip() for addr in (to_addresses or "").split(",") if addr.strip()]
        self.use_tls = use_tls

    def send(self, subject: str, body: str, metadata: dict[str, Any]) -> None:
        if not self.from_address or not self.to_addresses:
            raise NotificationError("Email channel requires SMTP_FROM and SMTP_TO")
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.from_address
        message["To"] = ", ".join(self.to_addresses)
        message.set_content(body)

        with smtplib.SMTP(self.host, self.port, timeout=30) as server:
            if self.use_tls:
                server.starttls()
            if self.username:
                server.login(self.username, self.password or "")
            server.send_message(message)


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
        elif channel_name == "email":
            if settings.smtp_host and settings.smtp_from and settings.smtp_to:
                channels.append(
                    EmailChannel(
                        host=settings.smtp_host,
                        port=settings.smtp_port,
                        username=settings.smtp_user,
                        password=settings.smtp_password,
                        from_address=settings.smtp_from,
                        to_addresses=settings.smtp_to,
                        use_tls=settings.notify_smtp_tls,
                    )
                )
            else:
                logger.warning("NOTIFY_CHANNELS includes email but SMTP_HOST/SMTP_FROM/SMTP_TO are unset")
        else:
            logger.warning("Unknown notification channel in NOTIFY_CHANNELS: %s", channel_name)
    return channels
