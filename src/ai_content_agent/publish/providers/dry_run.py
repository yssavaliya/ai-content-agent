from __future__ import annotations

from ...timestamps import format_utc, utc_now
from ..provider import PublishResult, Publisher


class DryRunPublisher(Publisher):
    @property
    def name(self) -> str:
        return "dry-run"

    def publish(self, package_path: str) -> PublishResult:
        now = utc_now()
        metadata = {
            "package_path": package_path,
            "simulated": True,
            "created_at": format_utc(now),
        }
        return PublishResult(
            provider=self.name,
            status="dry-run",
            published_id=f"dry-{now.strftime('%Y%m%d%H%M%S')}",
            metadata=metadata,
        )
