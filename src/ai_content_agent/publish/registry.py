from __future__ import annotations

import logging

from ..settings import Settings
from .buffer import BufferPublisher
from .instagram import InstagramPublisher
from .provider import Publisher
from .providers.dry_run import DryRunPublisher

logger = logging.getLogger(__name__)


class PublishRegistry:
    """Selects the concrete Publisher based on configuration."""

    @staticmethod
    def build_publisher(settings: Settings | None = None) -> Publisher:
        if settings is None:
            from ..settings import current_settings

            settings = current_settings()

        if settings.buffer_access_token and settings.buffer_profile_id:
            logger.info("Buffer publishing enabled (profile_id=%s)", settings.buffer_profile_id)
            return BufferPublisher(
                access_token=settings.buffer_access_token,
                profile_id=settings.buffer_profile_id,
            )

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

        return DryRunPublisher()
