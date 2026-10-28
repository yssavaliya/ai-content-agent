from __future__ import annotations

import logging
from typing import Any

import requests

from ..redaction import redact
from ..timestamps import utc_now_iso
from .base import AnalyticsProvider, PostMetrics

logger = logging.getLogger(__name__)

BUFFER_GRAPHQL_URL = "https://api.buffer.com"

GET_POST_METRICS_QUERY = """
query GetPostMetrics($id: String!) {
  post(input: { id: $id }) {
    id
    metrics {
      type
      name
      value
      unit
    }
    metricsUpdatedAt
  }
}
"""


class BufferAnalyticsClient(AnalyticsProvider):
    """Fetches social media post insights from Buffer GraphQL API."""

    @property
    def name(self) -> str:
        return "buffer"

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    def fetch_post_metrics(self, media_id: str) -> PostMetrics:
        """Fetch metrics for a given Buffer post ID."""
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        variables = {"id": media_id}

        try:
            resp = requests.post(
                BUFFER_GRAPHQL_URL,
                json={"query": GET_POST_METRICS_QUERY, "variables": variables},
                headers=headers,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Buffer Analytics API error: {redact(str(exc), self.access_token)}"
            ) from None

        if resp.status_code >= 400:
            raise RuntimeError(f"Buffer Analytics HTTP error ({resp.status_code}): {resp.text[:500]}")

        payload = resp.json()
        if payload.get("errors"):
            errors = payload["errors"]
            error_msg = "; ".join(e.get("message", "Unknown error") for e in errors)
            raise RuntimeError(f"Buffer Analytics GraphQL error: {error_msg}")

        post_data = payload.get("data", {}).get("post") or {}
        raw_metrics = post_data.get("metrics") or []

        metrics_map: dict[str, float] = {}
        for m in raw_metrics:
            m_type = m.get("type", "").lower()
            val = m.get("value")
            if val is not None:
                metrics_map[m_type] = float(val)

        impressions = int(metrics_map["impressions"]) if "impressions" in metrics_map else None
        reach = int(metrics_map["reach"]) if "reach" in metrics_map else impressions
        likes = int(metrics_map.get("reactions") or metrics_map.get("likes") or 0)
        comments = int(metrics_map.get("comments", 0))
        shares = int(metrics_map.get("shares", 0))
        saves = int(metrics_map.get("saves", 0))
        total_engagement = likes + comments + shares + saves

        engagement_rate: float | None = None
        if reach and reach > 0:
            engagement_rate = round(total_engagement / reach, 4)
        elif impressions and impressions > 0:
            engagement_rate = round(total_engagement / impressions, 4)

        return PostMetrics(
            media_id=media_id,
            impressions=impressions,
            reach=reach,
            likes=likes,
            comments=comments,
            shares=shares,
            saves=saves,
            engagement=total_engagement,
            engagement_rate=engagement_rate,
            collected_at=utc_now_iso(),
            raw=payload,
        )

    def fetch_account_insights(self, period_days: int) -> dict[str, Any]:
        """Aggregate insights across the channel."""
        return {
            "period_days": period_days,
            "provider": self.name,
            "collected_at": utc_now_iso(),
        }

