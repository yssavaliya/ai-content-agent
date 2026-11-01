from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from ..database.connection import DatabaseConnection
from ..timestamps import format_utc
from .followers import load_snapshots
from .milestones import MilestonePlan, evaluate


def check_health(
    db: DatabaseConnection,
    plan: MilestonePlan | None = None,
    now: datetime | None = None,
    stale_days: int = 3,
) -> list[str]:
    """Conditions that need a human. An empty list means the engine looks healthy."""
    now = now or datetime.now(timezone.utc)
    issues: list[str] = []

    last_post = db.fetch_all("SELECT MAX(created_at) AS latest FROM posts")[0]["latest"]
    cutoff = format_utc(now - timedelta(days=stale_days), "microseconds")
    if last_post is None:
        issues.append("No post has been recorded yet; confirm a live publisher (Buffer/Instagram) is configured.")
    elif last_post < cutoff:
        issues.append(f"No post recorded in the last {stale_days} days (latest: {last_post[:10]}).")

    recent = db.fetch_all("SELECT status, metadata FROM publish_packages ORDER BY id DESC LIMIT 3")
    fallback_runs = 0
    for row in recent:
        try:
            if json.loads(row["metadata"] or "{}").get("fallbacks"):
                fallback_runs += 1
        except ValueError:
            pass
    if len(recent) >= 2 and fallback_runs >= 2:
        issues.append(f"{fallback_runs} of the last {len(recent)} runs used template fallback content (LLM unavailable).")
    blocked = sum(1 for row in recent if str(row["status"]).startswith("blocked_"))
    if len(recent) >= 2 and blocked >= 2:
        issues.append(f"{blocked} of the last {len(recent)} runs were blocked (review or duplicate content).")

    failing = db.fetch_all(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END), 0) AS failures "
        "FROM api_usage WHERE created_at >= ?",
        (format_utc(now - timedelta(days=1), "microseconds"),),
    )[0]
    if failing["calls"] >= 4 and failing["failures"] / failing["calls"] > 0.5:
        issues.append(f"{failing['failures']} of {failing['calls']} API calls failed in the last 24h.")

    snapshots = load_snapshots(db)
    if not snapshots:
        issues.append("No follower count recorded yet; run `ai-content-agent followers` or set the Instagram token.")
    elif snapshots[-1][0] < now - timedelta(days=stale_days):
        issues.append(f"Follower count has not been refreshed since {snapshots[-1][0].date().isoformat()}.")
    elif plan is not None:
        status = evaluate(plan, snapshots, today=date(now.year, now.month, now.day), starting_followers=snapshots[0][1])
        if status.status in {"behind", "overdue"}:
            issues.append(
                f"Follower growth is {status.status} for the {status.target}-follower milestone "
                f"({status.followers} now, {status.days_left} days left)."
            )
    return issues
