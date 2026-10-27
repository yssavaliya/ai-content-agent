from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ...timestamps import format_utc, utc_now
from ..provider import PublishResult, Publisher

logger = logging.getLogger(__name__)


def render_post_kit(package: dict[str, Any]) -> str:
    """Render a package as a copy-paste-ready Markdown kit for manual publishing."""
    creation = package.get("creation") or {}
    image = package.get("image") or {}
    research = package.get("research") or {}
    review = package.get("review") or {}

    hashtags = creation.get("hashtags") or []
    outline = creation.get("carousel_outline") or []
    media = image.get("media_url") or image.get("file_path") or "(no image generated)"
    lines = [
        f"# Instagram post kit: {research.get('recommended_topic') or 'untitled'}",
        "",
        f"Run: {package.get('run_id', 'unknown')}  ",
        f"Review: {review.get('status', 'n/a')}",
        "",
        "## Caption",
        "",
        creation.get("caption", ""),
        "",
        "## Call to action",
        "",
        creation.get("cta", "") or "(none)",
        "",
        "## Hashtags",
        "",
        " ".join(hashtags) if hashtags else "(none)",
        "",
        "## Alt text",
        "",
        creation.get("alt_text", "") or "(none)",
        "",
        "## Image",
        "",
        str(media),
        "",
    ]
    if image.get("provider") == "local":
        lines += ["Image prompt (the local provider does not render images):", "", creation.get("image_prompt", ""), ""]
    if outline:
        lines += ["## Carousel outline", ""] + [f"{i}. {slide}" for i, slide in enumerate(outline, 1)] + [""]
    return "\n".join(lines)


class DryRunPublisher(Publisher):
    """Does not call Instagram. Writes a post kit so a person can publish manually."""

    @property
    def name(self) -> str:
        return "dry-run"

    def publish(self, package_path: str) -> PublishResult:
        now = utc_now()
        metadata: dict[str, Any] = {
            "package_path": package_path,
            "simulated": True,
            "created_at": format_utc(now),
        }
        kit_path = self._write_kit(Path(package_path))
        if kit_path is not None:
            metadata["kit_path"] = str(kit_path)
        return PublishResult(
            provider=self.name,
            status="dry-run",
            published_id=f"dry-{now.strftime('%Y%m%d%H%M%S')}",
            metadata=metadata,
        )

    @staticmethod
    def _write_kit(package_path: Path) -> Path | None:
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
            kit_path = package_path.with_name(package_path.stem.replace("publish_package_", "post_kit_") + ".md")
            kit_path.write_text(render_post_kit(package), encoding="utf-8")
            return kit_path
        except (OSError, ValueError) as exc:
            logger.warning("Could not write post kit for %s: %s", package_path, exc)
            return None
