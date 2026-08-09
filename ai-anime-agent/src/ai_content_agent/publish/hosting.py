from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

_MAX_JPEG_BYTES = 8 * 1024 * 1024  # Instagram rejects media above 8 MB
_JPEG_QUALITY = 90


class MediaHostingError(RuntimeError):
    pass


@dataclass(frozen=True)
class HostedImage:
    url: str
    path: str
    branch: str
    sha: str | None


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "image"


def convert_to_jpeg(source_path: str | Path, output_path: str | Path) -> Path:
    """Convert an image file to a JPEG suitable for Instagram (RGB, <=8 MB).

    Raises MediaHostingError if the source cannot be decoded.
    """
    try:
        from PIL import Image
    except ImportError as exc:
        raise MediaHostingError("Pillow is required for JPEG conversion; run: pip install Pillow") from exc

    try:
        with Image.open(source_path) as image:
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            quality = _JPEG_QUALITY
            while True:
                image.save(output, "JPEG", quality=quality, optimize=True)
                if output.stat().st_size <= _MAX_JPEG_BYTES or quality <= 40:
                    break
                quality -= 10
    except OSError as exc:
        raise MediaHostingError(f"Could not convert image to JPEG: {exc}") from exc

    if output.stat().st_size > _MAX_JPEG_BYTES:
        raise MediaHostingError(
            f"Converted JPEG still exceeds 8 MB ({output.stat().st_size} bytes): {output}"
        )
    return output


def parse_repo(repo: str) -> tuple[str, str]:
    parts = repo.strip().strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        raise MediaHostingError(f"MEDIA_HOST_REPO must be 'owner/repo', got: {repo!r}")
    return parts[0], parts[1]


class GitHubRawImageHost:
    """Uploads images to a GitHub repo and returns raw.githubusercontent.com URLs."""

    API_BASE = "https://api.github.com"
    RAW_BASE = "https://raw.githubusercontent.com"

    def __init__(
        self,
        repo: str,
        token: str,
        branch: str = "main",
        base_path: str = "images",
    ) -> None:
        self.owner, self.repo = parse_repo(repo)
        self.token = token
        self.branch = branch
        self.base_path = base_path.strip("/")

    def public_url(self, path_in_repo: str) -> str:
        return f"{self.RAW_BASE}/{self.owner}/{self.repo}/{self.branch}/{path_in_repo}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _remote_path(self, relative_path: str) -> str:
        relative_path = relative_path.strip("/")
        return f"{self.base_path}/{relative_path}" if self.base_path else relative_path

    def _get_existing_sha(self, remote_path: str) -> str | None:
        response = requests.get(
            f"{self.API_BASE}/repos/{self.owner}/{self.repo}/contents/{remote_path}",
            headers=self._headers(),
            params={"ref": self.branch},
            timeout=30,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return None
        return payload.get("sha")

    def upload(self, file_path: str | Path, remote_relative_path: str, message: str | None = None) -> HostedImage:
        remote_path = self._remote_path(remote_relative_path)
        file_path = Path(file_path)
        if not file_path.exists():
            raise MediaHostingError(f"Image file not found: {file_path}")

        content = base64.b64encode(file_path.read_bytes()).decode("ascii")
        existing_sha = self._get_existing_sha(remote_path)
        body: dict[str, Any] = {
            "message": message or f"chore: upload {file_path.name}",
            "content": content,
            "branch": self.branch,
        }
        if existing_sha:
            body["sha"] = existing_sha

        response = requests.put(
            f"{self.API_BASE}/repos/{self.owner}/{self.repo}/contents/{remote_path}",
            headers=self._headers(),
            json=body,
            timeout=60,
        )
        if response.status_code not in (200, 201):
            raise MediaHostingError(
                f"GitHub upload failed ({response.status_code}): {response.text[:500]}"
            )
        payload = response.json()
        sha = payload.get("content", {}).get("sha")
        logger.info("Uploaded image to %s (branch=%s)", self.public_url(remote_path), self.branch)
        return HostedImage(
            url=self.public_url(remote_path),
            path=remote_path,
            branch=self.branch,
            sha=sha,
        )
