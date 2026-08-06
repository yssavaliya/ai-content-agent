from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

from ..settings import current_settings
from ..timestamps import utc_now_iso
from .provider import PublishResult, Publisher

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com"
GRAPH_API_VERSION = "21.0"
MAX_CAPTION_LENGTH = 2200
MAX_POLL_SECONDS = 300
POLL_INTERVAL_SECONDS = 5


class InstagramAPIError(RuntimeError):
    def __init__(self, message: str, code: int | None = None, subcode: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.subcode = subcode


class InstagramGraphClient:
    """Minimal client for the Instagram Graph API content-publishing endpoints."""

    def __init__(
        self,
        access_token: str,
        api_version: str = "21.0",
        timeout_seconds: int = 30,
    ) -> None:
        self.access_token = access_token
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds
        self.base = f"{GRAPH_API_BASE}/v{api_version}"

    def _post(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = dict(params)
        query["access_token"] = self.access_token
        response = requests.post(f"{self.base}/{path}", data=query, timeout=self.timeout_seconds)
        return self._handle_response(response)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = dict(params)
        query["access_token"] = self.access_token
        response = requests.get(f"{self.base}/{path}", params=query, timeout=self.timeout_seconds)
        return self._handle_response(response)

    @staticmethod
    def _handle_response(response: requests.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            error = InstagramAPIError(
                f"Instagram Graph API error ({response.status_code}): {response.text[:500]}",
                code=response.status_code,
            )
            try:
                payload = response.json()
                inner = payload.get("error", {})
                error.code = inner.get("code")
                error.subcode = inner.get("error_subcode")
            except ValueError:
                pass
            raise error
        return response.json()

    def create_image_container(
        self,
        account_id: str,
        image_url: str,
        caption: str | None = None,
        alt_text: str | None = None,
    ) -> str:
        params: dict[str, Any] = {"image_url": image_url}
        if caption:
            params["caption"] = caption
        if alt_text:
            params["alt_text"] = alt_text
        payload = self._post(f"{account_id}/media", params)
        container_id = payload.get("id")
        if not container_id:
            raise InstagramAPIError(f"Media container creation returned no id: {payload}")
        logger.info("Created Instagram media container %s", container_id)
        return str(container_id)

    def container_status(self, container_id: str) -> str:
        payload = self._get(container_id, {"fields": "status_code"})
        return str(payload.get("status_code") or "")

    def wait_for_container(
        self,
        container_id: str,
        timeout_seconds: int = MAX_POLL_SECONDS,
        poll_interval_seconds: int = POLL_INTERVAL_SECONDS,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            status = self.container_status(container_id)
            if status == "FINISHED":
                logger.info("Instagram media container %s finished processing", container_id)
                return
            if status == "ERROR":
                raise InstagramAPIError(
                    f"Instagram media container {container_id} failed to process (status=ERROR)"
                )
            if status == "EXPIRED":
                raise InstagramAPIError(
                    f"Instagram media container {container_id} expired before publishing"
                )
            if time.monotonic() >= deadline:
                raise InstagramAPIError(
                    f"Instagram media container {container_id} still {status!r} after {timeout_seconds}s"
                )
            time.sleep(poll_interval_seconds)

    def publish_container(self, account_id: str, container_id: str) -> str:
        payload = self._post(f"{account_id}/media_publish", {"creation_id": container_id})
        media_id = payload.get("id")
        if not media_id:
            raise InstagramAPIError(f"Media publish returned no id: {payload}")
        logger.info("Published Instagram media %s from container %s", media_id, container_id)
        return str(media_id)


def build_caption(caption: str, hashtags: list[str] | None = None) -> str:
    parts = [caption]
    if hashtags:
        parts.append(" ".join(hashtags))
    joined = "\n\n".join(part for part in parts if part)
    return joined[:MAX_CAPTION_LENGTH]


class InstagramPublisher(Publisher):
    @property
    def name(self) -> str:
        return "instagram"

    def __init__(
        self,
        access_token: str | None = None,
        account_id: str | None = None,
        api_version: str | None = None,
        client: InstagramGraphClient | None = None,
    ) -> None:
        settings = self._resolve_settings()
        self.access_token = access_token or (settings.instagram_access_token if settings else None) or ""
        self.account_id = account_id or (settings.instagram_account_id if settings else None) or ""
        self.api_version = api_version or (settings.instagram_api_version if settings else GRAPH_API_VERSION)
        self._client = client

    @staticmethod
    def _resolve_settings() -> Any:
        try:
            return current_settings()
        except ValueError:
            return None

    def _get_client(self) -> InstagramGraphClient:
        if self._client is not None:
            return self._client
        if not self.access_token or not self.account_id:
            raise InstagramAPIError(
                "Instagram publishing requires INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_ACCOUNT_ID"
            )
        return InstagramGraphClient(access_token=self.access_token, api_version=self.api_version)

    def publish(self, package_path: str) -> PublishResult:
        package = json.loads(Path(package_path).read_text(encoding="utf-8"))
        image = package.get("image") or {}
        media_url = image.get("media_url")
        if not media_url:
            raise InstagramAPIError("Package image is missing a public media_url to publish")

        creation = package.get("creation") or {}
        caption = build_caption(creation.get("caption", ""), creation.get("hashtags"))
        alt_text = (creation.get("alt_text") or "")[:100]

        client = self._get_client()
        container_id = client.create_image_container(self.account_id, media_url, caption, alt_text)
        client.wait_for_container(container_id)
        media_id = client.publish_container(self.account_id, container_id)

        return PublishResult(
            provider=self.name,
            status="published",
            published_id=media_id,
            metadata={
                "container_id": container_id,
                "media_id": media_id,
                "caption_length": len(caption),
                "published_at": utc_now_iso(),
            },
        )
