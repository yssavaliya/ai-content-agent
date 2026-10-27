from __future__ import annotations

import logging
import time
from typing import Any

import requests

from ..redaction import redact
from ..timestamps import utc_now_iso
from .base import AnalyticsProvider, PostMetrics

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com"

# Metrics are returned lazily and are partially available per media type;
# a missing metric is never treated as zero.
INSIGHTS_METRICS = ("impressions", "reach", "likes", "comments", "shares", "saved", "engagement")


class InstagramAnalyticsError(RuntimeError):
    pass


class InstagramAnalyticsClient(AnalyticsProvider):
    @property
    def name(self) -> str:
        return "instagram"

    def __init__(
        self,
        access_token: str,
        account_id: str,
        api_version: str = "21.0",
        timeout_seconds: int = 30,
    ) -> None:
        self.access_token = access_token
        self.account_id = account_id
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds
        self.base = f"{GRAPH_API_BASE}/v{api_version}"

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = dict(params)
        query["access_token"] = self.access_token
        try:
            response = requests.get(f"{self.base}/{path}", params=query, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise InstagramAnalyticsError(
                f"Instagram Graph API request failed: {redact(str(exc), self.access_token)}"
            ) from None
        if response.status_code >= 400:
            raise InstagramAnalyticsError(
                f"Instagram Graph API error ({response.status_code}): {response.text[:500]}"
            )
        return response.json()

    @staticmethod
    def _metric_values(payload: dict[str, Any]) -> dict[str, int | float | None]:
        result: dict[str, int | float | None] = {}
        for entry in payload.get("data", []):
            name = entry.get("name")
            values = entry.get("values") or []
            if not name or not values:
                continue
            value = values[-1].get("value")
            if value is None:
                continue
            if isinstance(value, dict):
                value = value.get("total_count") or value.get("value")
            result[name] = value
        return result

    def fetch_post_metrics(self, media_id: str) -> PostMetrics:
        payload = self._get(
            f"{media_id}/insights",
            {"metric": ",".join(INSIGHTS_METRICS), "period": "lifetime"},
        )
        values = self._metric_values(payload)
        impressions = values.get("impressions")
        reach = values.get("reach")
        likes = values.get("likes")
        comments = values.get("comments")
        shares = values.get("shares")
        saves = values.get("saved")
        engagement = values.get("engagement")

        engagement_rate: float | None = None
        if engagement is not None and impressions:
            engagement_rate = round(float(engagement) / float(impressions), 4)

        metrics = PostMetrics(
            media_id=media_id,
            impressions=int(impressions) if impressions is not None else None,
            reach=int(reach) if reach is not None else None,
            likes=int(likes) if likes is not None else None,
            comments=int(comments) if comments is not None else None,
            shares=int(shares) if shares is not None else None,
            saves=int(saves) if saves is not None else None,
            engagement=int(engagement) if engagement is not None else None,
            engagement_rate=engagement_rate,
            collected_at=utc_now_iso(),
            raw=payload,
        )
        logger.info("Collected Instagram insights for media %s", media_id)
        return metrics

    def fetch_account_insights(self, period_days: int = 30) -> dict[str, Any]:
        metric = "follower_count,reach,impressions,accounts_engaged,profile_views"
        until = int(time.time())
        since = until - period_days * 86400
        payload = self._get(
            f"{self.account_id}/insights",
            {"metric": metric, "period": "day", "since": since, "until": until},
        )
        return payload
