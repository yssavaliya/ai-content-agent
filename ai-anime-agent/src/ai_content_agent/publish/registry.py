from __future__ import annotations

import logging

from ..settings import Settings
from .instagram import InstagramPublisher
from .provider import Publisher
from .providers.dry_run import DryRunPublisher
from .providers.email import EmailPublisher

logger = logging.getLogger(__name__)


class PublishRegistry:
    """Selects the concrete Publisher based on configuration."""

    @staticmethod
    def build_publisher(settings: Settings | None = None) -> Publisher:
        if settings is None:
            from ..settings import current_settings

            settings = current_settings()

        if settings.instagram_publish_enabled:
            if not settings.instagram_access_token or not settings.instagram_account_id:
                logger.warning(
                    "INSTAGRAM_PUBLISH_ENABLED is true but token/account are unset; falling back to dry-run"
                )
                return DryRunPublisher()
            return InstagramPublisher(
                access_token=settings.instagram_access_token,
                account_id=settings.instagram_account_id,
                api_version=settings.instagram_api_version,
            )

        if settings.notify_channels and "email" in settings.notify_channels:
            if not all([settings.smtp_host, settings.smtp_user, settings.smtp_password, settings.smtp_from, settings.smtp_to]):
                logger.warning(
                    "Email notify channel enabled but SMTP settings incomplete; falling back to dry-run"
                )
                return DryRunPublisher()
            return EmailPublisher(
                smtp_host=settings.smtp_host,
                smtp_port=settings.smtp_port,
                smtp_user=settings.smtp_user,
                smtp_password=settings.smtp_password,
                smtp_from=settings.smtp_from,
                smtp_to=settings.smtp_to,
                use_tls=settings.notify_smtp_tls,
            )

        return DryRunPublisher()
