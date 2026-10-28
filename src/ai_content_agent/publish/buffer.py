from __future__ import annotations

import json
import logging
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


class BufferPublisher(Publisher):
    @property
    def name(self) -> str:
        return "buffer"

    def __init__(self, access_token: str, profile_id: str = "") -> None:
        self.access_token = access_token
        self.profile_id = profile_id

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

        channel_id = self._resolve_channel_id()
        if not channel_id:
            raise RuntimeError("No Buffer channelId / profile_id available for publishing")

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        # Attempt shareNow first (instant publishing), fallback to addToQueue if immediate sharing is restricted
        modes = ["shareNow", "addToQueue"]
        last_error = ""
        post_data: dict[str, Any] = {}

        for mode in modes:
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
                        "instagram": {
                            "type": "post",
                            "shouldShareToFeed": True,
                        }
                    },
                }
            }

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
                if "mode" in error_msg.lower() or "sharenow" in error_msg.lower():
                    continue
                raise RuntimeError(f"Buffer GraphQL error: {error_msg}")

            create_result = payload.get("data", {}).get("createPost", {})
            if "message" in create_result and "post" not in create_result:
                msg = create_result["message"]
                last_error = msg
                if "mode" in msg.lower() or "sharenow" in msg.lower():
                    continue
                raise RuntimeError(f"Buffer GraphQL mutation error: {msg}")

            post_data = create_result.get("post") or {}
            break
        else:
            raise RuntimeError(f"Buffer publication failed: {last_error}")

        update_id = post_data.get("id") or ""
        status = post_data.get("status") or "published"

        logger.info("Published to Instagram via Buffer GraphQL (post_id=%s, status=%s)", update_id, status)
        return PublishResult(
            provider=self.name,
            status=status,
            published_id=str(update_id),
            metadata={
                "post_id": update_id,
                "update_id": update_id,
                "channel_id": channel_id,
                "profile_id": channel_id,
                "status": status,
                "published_at": utc_now_iso(),
            },
        )
