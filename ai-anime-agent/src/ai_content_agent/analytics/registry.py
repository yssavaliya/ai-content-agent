from __future__ import annotations

import logging

from ..settings import Settings
from .base import AnalyticsProvider
from .buffer import BufferAnalyticsClient
from .instagram import InstagramAnalyticsClient

logger = logging.getLogger(__name__)


class AnalyticsRegistry:
    """Builds an AnalyticsProvider from configuration, or None if disabled."""

    @staticmethod
    def build_provider(settings: Settings | None = None) -> AnalyticsProvider | None:
        if settings is None:
            from ..settings import current_settings

            settings = current_settings()

        # If Buffer access token is present, use Buffer analytics client
        if settings.buffer_access_token:
            logger.info("Buffer analytics enabled")
            return BufferAnalyticsClient(access_token=settings.buffer_access_token)

        if not settings.instagram_analytics_enabled:
            return None

        if not settings.instagram_access_token or not settings.instagram_account_id:
            logger.warning(
                "INSTAGRAM_ANALYTICS_ENABLED is true but token/account are unset; analytics disabled"
            )
            return None

        return InstagramAnalyticsClient(
            access_token=settings.instagram_access_token,
            account_id=settings.instagram_account_id,
            api_version=settings.instagram_api_version,
        )
