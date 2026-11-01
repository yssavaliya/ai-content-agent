from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..database.connection import DatabaseConnection
from ..redaction import redact
from ..settings import Settings
from ..timestamps import utc_now_iso
from .milestones import Snapshot, parse_timestamp

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com"


class FollowerSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class FollowerCount:
    followers: int
    media_count: int | None
    source: str


class InstagramFollowerSource:
    """Reads followers_count through the official Instagram Graph API.

    Needs an Instagram Business or Creator account linked to a Facebook Page and a token that can read it
    (INSTAGRAM_ACCESS_TOKEN + INSTAGRAM_ACCOUNT_ID). No scraping is involved.
    """

    name = "instagram"

    def __init__(self, access_token: str, account_id: str, api_version: str = "21.0", timeout_seconds: int = 30) -> None:
        self.access_token = access_token
        self.account_id = account_id
        self.base = f"{GRAPH_API_BASE}/v{api_version}"
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> FollowerCount:
        try:
            response = requests.get(
                f"{self.base}/{self.account_id}",
                params={"fields": "followers_count,media_count", "access_token": self.access_token},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise FollowerSourceError(
                f"Instagram follower request failed: {redact(str(exc), self.access_token)}"
            ) from None
        if response.status_code >= 400:
            raise FollowerSourceError(f"Instagram Graph API error ({response.status_code}): {response.text[:300]}")
        payload: dict[str, Any] = response.json()
        followers = payload.get("followers_count")
        if not isinstance(followers, int) or followers < 0:
            raise FollowerSourceError(f"Instagram response has no usable followers_count: {payload}")
        media_count = payload.get("media_count")
        return FollowerCount(followers, media_count if isinstance(media_count, int) else None, self.name)


def build_follower_source(settings: Settings) -> InstagramFollowerSource | None:
    if settings.instagram_access_token and settings.instagram_account_id:
        return InstagramFollowerSource(
            settings.instagram_access_token, settings.instagram_account_id, settings.instagram_api_version
        )
    return None


def record_snapshot(db: DatabaseConnection, count: FollowerCount, captured_at: str | None = None) -> int:
    if count.followers < 0:
        raise ValueError("followers must not be negative")
    cursor = db.execute(
        "INSERT INTO follower_snapshots(captured_at, followers, media_count, source) VALUES (?, ?, ?, ?)",
        (captured_at or utc_now_iso(), count.followers, count.media_count, count.source),
    )
    return cursor.lastrowid


def load_snapshots(db: DatabaseConnection) -> list[Snapshot]:
    rows = db.fetch_all("SELECT captured_at, followers FROM follower_snapshots ORDER BY captured_at, id")
    return [(parse_timestamp(row["captured_at"]), int(row["followers"])) for row in rows]


def daily_series(snapshots: list[Snapshot]) -> list[tuple[str, int]]:
    """Last snapshot of each UTC day, oldest first."""
    by_day: dict[str, int] = {}
    for moment, value in sorted(snapshots, key=lambda item: item[0]):
        by_day[moment.date().isoformat()] = value
    return list(by_day.items())


def starting_point(db: DatabaseConnection) -> tuple[datetime, int] | None:
    rows = db.fetch_all("SELECT captured_at, followers FROM follower_snapshots ORDER BY captured_at, id LIMIT 1")
    if not rows:
        return None
    return parse_timestamp(rows[0]["captured_at"]), int(rows[0]["followers"])
