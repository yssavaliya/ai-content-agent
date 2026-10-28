from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

from ..redaction import redact
from ..timestamps import utc_now_iso
from .instagram import build_caption
from .provider import PublishResult, Publisher

logger = logging.getLogger(__name__)

BUFFER_API_URL = "https://api.bufferapp.com/1/updates/create.json"


class BufferPublisher(Publisher):
    @property
    def name(self) -> str:
        return "buffer"

    def __init__(self, access_token: str, profile_id: str) -> None:
        self.access_token = access_token
        self.profile_id = profile_id

    def publish(self, package_path: str) -> PublishResult:
        package = json.loads(Path(package_path).read_text(encoding="utf-8"))
        image = package.get("image") or {}
        media_url = image.get("media_url")
        if not media_url:
            raise RuntimeError("Package image is missing a public media_url for Buffer publishing")

        creation = package.get("creation") or {}
        caption = build_caption(creation.get("caption", ""), creation.get("hashtags"))

        data = {
            "access_token": self.access_token,
            "profile_ids[]": self.profile_id,
            "text": caption,
            "now": "true",
            "media[photo]": media_url,
        }

        try:
            resp = requests.post(BUFFER_API_URL, data=data, timeout=30)
        except requests.RequestException as exc:
            raise RuntimeError(f"Buffer API request failed: {redact(str(exc), self.access_token)}") from None

        if resp.status_code >= 400:
            raise RuntimeError(f"Buffer API error ({resp.status_code}): {resp.text[:500]}")

        payload = resp.json()
        update_id = ""
        if isinstance(payload.get("updates"), list) and payload["updates"]:
            update_id = payload["updates"][0].get("id", "")
        elif payload.get("buffer_update_id"):
            update_id = payload["buffer_update_id"]

        logger.info("Published to Instagram via Buffer (update_id=%s)", update_id)
        return PublishResult(
            provider=self.name,
            status="published",
            published_id=str(update_id),
            metadata={
                "update_id": update_id,
                "profile_id": self.profile_id,
                "published_at": utc_now_iso(),
            },
        )
