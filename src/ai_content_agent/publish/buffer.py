from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from ..redaction import redact
from ..timestamps import utc_now_iso
from .instagram import build_caption
from .provider import PublishResult, Publisher

logger = logging.getLogger(__name__)

BUFFER_GRAPHQL_URL = "https://api.buffer.com"

CREATE_POST_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess {
      post {
        id
        status
      }
    }
    ... on MutationError {
      message
    }
  }
}
"""

GET_ORGANIZATIONS_QUERY = """
query GetOrganizations {
  account {
    organizations {
      id
      name
    }
  }
}
"""

GET_CHANNELS_QUERY = """
query GetChannels($input: ChannelsInput!) {
  channels(input: $input) {
    id
    name
    displayName
    service
  }
}
"""


MIN_LEAD_MINUTES = 5


def parse_schedule_time(value: str) -> tuple[int, int]:
    """Parse an 'HH:MM' (24h, UTC) string."""
    try:
        hour_text, minute_text = value.strip().split(":")
        hour, minute = int(hour_text), int(minute_text)
    except ValueError:
        raise ValueError(f"Invalid schedule time {value!r}; expected HH:MM in UTC, e.g. 12:30") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid schedule time {value!r}; expected HH:MM in UTC, e.g. 12:30")
    return hour, minute


def next_due_at(now: datetime, schedule_time_utc: str) -> str:
    """Next occurrence of HH:MM UTC that is at least MIN_LEAD_MINUTES away, as an ISO-8601 string."""
    hour, minute = parse_schedule_time(schedule_time_utc)
    due = now.astimezone(timezone.utc).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due < now.astimezone(timezone.utc) + timedelta(minutes=MIN_LEAD_MINUTES):
        due += timedelta(days=1)
    return due.isoformat(timespec="seconds").replace("+00:00", "Z")


class BufferPublisher(Publisher):
    @property
    def name(self) -> str:
        return "buffer"

    def __init__(self, access_token: str, profile_id: str = "", schedule_time_utc: str | None = None) -> None:
        self.access_token = access_token
        self.profile_id = profile_id
        # When set, posts are scheduled for the next HH:MM UTC instead of being shared immediately.
        self.schedule_time_utc = schedule_time_utc
        if schedule_time_utc:
            parse_schedule_time(schedule_time_utc)

    def _resolve_channel_id(self) -> str:
        """Return configured profile_id or auto-discover Instagram channel ID from Buffer API."""
        if self.profile_id:
            return self.profile_id

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                BUFFER_GRAPHQL_URL,
                json={"query": GET_ORGANIZATIONS_QUERY},
                headers=headers,
                timeout=20,
            )
            if resp.status_code == 200:
                payload = resp.json()
                orgs = payload.get("data", {}).get("account", {}).get("organizations", [])
                for org in orgs:
                    org_id = org.get("id")
                    if not org_id:
                        continue
                    ch_resp = requests.post(
                        BUFFER_GRAPHQL_URL,
                        json={"query": GET_CHANNELS_QUERY, "variables": {"input": {"organizationId": org_id}}},
                        headers=headers,
                        timeout=20,
                    )
                    if ch_resp.status_code == 200:
                        channels = ch_resp.json().get("data", {}).get("channels", [])
                        for ch in channels:
                            if ch.get("service") == "instagram":
                                logger.info(
                                    "Discovered Buffer Instagram channel id=%s (@%s)",
                                    ch.get("id"),
                                    ch.get("name") or ch.get("displayName"),
                                )
                                return ch.get("id", "")
                        if channels:
                            return channels[0].get("id", "")
        except requests.RequestException as exc:
            logger.warning("Failed to auto-discover Buffer channel: %s", redact(str(exc), self.access_token))

        return self.profile_id

    def publish(self, package_path: str) -> PublishResult:
        package = json.loads(Path(package_path).read_text(encoding="utf-8"))
        image = package.get("image") or {}
        media_url = image.get("media_url")
        if not media_url:
            raise RuntimeError("Package image is missing a public media_url for Buffer publishing")

        creation = package.get("creation") or {}
        caption = build_caption(creation.get("caption", ""), creation.get("hashtags"))

        # Conversation-seeding first comment to build early engagement
        first_comment = creation.get("first_comment")
        if not first_comment:
            cta = creation.get("cta") or ""
            if cta:
                first_comment = f"Drop your thoughts below 👇 {cta}"
            else:
                first_comment = (
                    "Drop your thoughts below 👇 What is the #1 project or skill you are locking into this week? ⚔️"
                )

        channel_id = self._resolve_channel_id()
        if not channel_id:
            raise RuntimeError("No Buffer channelId / profile_id available for publishing")

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        # Default: shareNow (instant), falling back to addToQueue if immediate sharing is restricted.
        # With a schedule time: customScheduled at the next HH:MM UTC, falling back to addToQueue.
        due_at = next_due_at(datetime.now(timezone.utc), self.schedule_time_utc) if self.schedule_time_utc else None
        modes = ["customScheduled", "addToQueue"] if due_at else ["shareNow", "addToQueue"]
        last_error = ""
        post_data: dict[str, Any] = {}

        for mode in modes:
            instagram_meta: dict[str, Any] = {
                "type": "post",
                "shouldShareToFeed": True,
            }
            if first_comment:
                instagram_meta["firstComment"] = first_comment

            variables = {
                "input": {
                    "channelId": channel_id,
                    "text": caption,
                    "schedulingType": "automatic",
                    "mode": mode,
                    "assets": [
                        {
                            "image": {
                                "url": media_url,
                            }
                        }
                    ],
                    "metadata": {
                        "instagram": instagram_meta,
                    },
                }
            }
            if mode == "customScheduled" and due_at:
                variables["input"]["dueAt"] = due_at

            try:
                resp = requests.post(
                    BUFFER_GRAPHQL_URL,
                    json={"query": CREATE_POST_MUTATION, "variables": variables},
                    headers=headers,
                    timeout=30,
                )
            except requests.RequestException as exc:
                raise RuntimeError(
                    f"Buffer API request failed: {redact(str(exc), self.access_token)}"
                ) from None

            if resp.status_code >= 400:
                raise RuntimeError(f"Buffer API HTTP error ({resp.status_code}): {resp.text[:500]}")

            payload = resp.json()
            if payload.get("errors"):
                errors = payload["errors"]
                error_msg = "; ".join(e.get("message", "Unknown error") for e in errors)
                last_error = error_msg
                # If first comment is locked to paid plans, retry without it
                if "first comment" in error_msg.lower() and first_comment:
                    first_comment = None
                    continue
                if "mode" in error_msg.lower() or "sharenow" in error_msg.lower():
                    continue
                raise RuntimeError(f"Buffer GraphQL error: {error_msg}")

            create_result = payload.get("data", {}).get("createPost", {})
            if "message" in create_result and "post" not in create_result:
                msg = create_result["message"]
                last_error = msg
                # If first comment is locked to paid plans, retry without it
                if "first comment" in msg.lower() and first_comment:
                    logger.info("Buffer plan does not support firstComment; continuing with standard post...")
                    first_comment = None
                    continue
                if "mode" in msg.lower() or "sharenow" in msg.lower():
                    continue
                raise RuntimeError(f"Buffer GraphQL mutation error: {msg}")

            post_data = create_result.get("post") or {}
            break
        else:
            raise RuntimeError(f"Buffer publication failed: {last_error}")

        update_id = post_data.get("id") or ""
        status = post_data.get("status") or "published"

        logger.info(
            "Published to Instagram via Buffer GraphQL (post_id=%s, status=%s, first_comment=%s)",
            update_id,
            status,
            bool(first_comment),
        )
        return PublishResult(
            provider=self.name,
            status=status,
            published_id=str(update_id),
            metadata={
                "post_id": update_id,
                "update_id": update_id,
                "channel_id": channel_id,
                "profile_id": channel_id,
                "first_comment": first_comment,
                "due_at": due_at if mode == "customScheduled" else None,
                "status": status,
                "published_at": utc_now_iso(),
            },
        )
