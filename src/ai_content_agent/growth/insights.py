from __future__ import annotations

from ..database.connection import DatabaseConnection


def _first_line(text: str, limit: int = 90) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


def top_and_bottom_posts(db: DatabaseConnection, count: int = 3) -> tuple[list[dict], list[dict]]:
    """Measured posts ranked by their latest engagement rate (best first, worst first)."""
    rows = db.fetch_all(
        "SELECT p.id, p.caption, p.topic, pm.engagement_rate, pm.reach, pm.saves, pm.shares, ep.arm "
        "FROM posts p JOIN post_metrics pm ON pm.post_id = p.id "
        "LEFT JOIN experiment_posts ep ON ep.post_id = p.id "
        "WHERE pm.engagement_rate IS NOT NULL "
        "AND pm.id = (SELECT MAX(id) FROM post_metrics WHERE post_id = p.id AND engagement_rate IS NOT NULL) "
        "ORDER BY pm.engagement_rate DESC"
    )
    # Never list the same post as both best and weakest: with few posts, split them down the middle.
    total = len(rows)
    size = min(count, max(total // 2, 1)) if total else 0
    best = rows[:size]
    worst = list(reversed(rows[total - size :])) if total >= 2 * size and size else []
    return best, worst


def performance_insights(db: DatabaseConnection, count: int = 3) -> str:
    """Short plain-text summary of what has and has not worked, for the content prompts.

    Returns an empty string when nothing has been measured yet so the prompt carries no filler.
    """
    best, worst = top_and_bottom_posts(db, count)
    if not best:
        return ""

    def describe(post: dict) -> str:
        rate = post["engagement_rate"] * 100
        arm = f", experiment arm: {post['arm']}" if post.get("arm") else ""
        return f'- "{_first_line(post["caption"])}" (engagement {rate:.1f}%, saves {post["saves"]}, shares {post["shares"]}{arm})'

    lines = ["Best performing recent posts (repeat what made these work, never copy them):"]
    lines += [describe(post) for post in best]
    if worst:
        lines += ["", "Weakest recent posts (avoid what made these fail):"]
        lines += [describe(post) for post in worst]
    return "\n".join(lines)
