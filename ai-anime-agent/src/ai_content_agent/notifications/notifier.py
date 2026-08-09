from __future__ import annotations

import logging
from typing import Any, Sequence

from ..settings import Settings
from .channels import NotificationChannel, build_channels

logger = logging.getLogger(__name__)


class Notifier:
    """Sends notifications across all configured channels, never raising on failure."""

    def __init__(self, channels: Sequence[NotificationChannel]) -> None:
        self.channels = list(channels)

    @classmethod
    def from_settings(cls, settings: Settings) -> "Notifier":
        return cls(build_channels(settings))

    def notify(self, event: str, subject: str, body: str, metadata: dict[str, Any] | None = None) -> dict[str, bool]:
        metadata = metadata or {}
        results: dict[str, bool] = {}
        for channel in self.channels:
            try:
                channel.send(subject, body, metadata)
                results[channel.name] = True
            except Exception as exc:
                logger.error("Notification channel %s failed for event %s: %s", channel.name, event, exc)
                results[channel.name] = False
        logger.info("Notification event=%s delivered=%s", event, results)
        return results

    def send_success(self, subject: str, body: str, metadata: dict[str, Any] | None = None) -> dict[str, bool]:
        return self.notify("success", subject, body, metadata or {"color": 3066993})

    def send_failure(
        self,
        subject: str,
        body: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, bool]:
        return self.notify("failure", subject, body, metadata or {"color": 15158332})
