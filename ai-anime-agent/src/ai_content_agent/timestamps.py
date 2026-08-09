from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def format_utc(dt: datetime, timespec: str = "seconds") -> str:
    """Format a tz-aware UTC datetime as an ISO-8601 string ending in Z."""
    return dt.isoformat(timespec=timespec).replace("+00:00", "Z")


def utc_now_iso(timespec: str = "microseconds") -> str:
    """Return an ISO-8601 UTC timestamp ending in Z."""
    return format_utc(utc_now(), timespec=timespec)
