from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..provider import PublishResult, Publisher


class DryRunPublisher(Publisher):
    @property
    def name(self) -> str:
        return "dry-run"

    def publish(self, package_path: str) -> PublishResult:
        now = datetime.utcnow()
        metadata = {
            "package_path": package_path,
            "simulated": True,
            "created_at": now.isoformat() + "Z",
        }
        return PublishResult(
            provider=self.name,
            status="dry-run",
            published_id=f"dry-{now.strftime('%Y%m%d%H%M%S')}",
            metadata=metadata,
        )
