from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Sequence

Snapshot = tuple[datetime, int]


def parse_timestamp(value: str) -> datetime:
    """Parse the ISO-8601 'Z' timestamps stored in SQLite into aware UTC datetimes."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class MilestonePlan:
    """Follower targets: base_target, then x multiplier for every following period.

    With the defaults the targets are 1000, 2500, 6250, 15625 ... and target k is due
    (k + 1) * period_days after start_date.
    """

    start_date: date
    base_target: int = 1000
    multiplier: float = 2.5
    period_days: int = 90

    def target(self, index: int) -> int:
        return int(math.ceil(self.base_target * self.multiplier**index))

    def deadline(self, index: int) -> date:
        return self.start_date + timedelta(days=self.period_days * (index + 1))


@dataclass(frozen=True)
class MilestoneStatus:
    status: str  # no_data | on_track | at_risk | behind | overdue
    target: int
    target_index: int
    previous_target: int
    deadline: date
    followers: int | None
    progress: float  # 0..1 between the previous target (or the starting count) and this target
    days_left: int
    remaining: int
    required_per_day: float | None
    recent_per_day: float | None
    projected_at_deadline: int | None
    achieved_targets: tuple[int, ...]


def delta_over(snapshots: Sequence[Snapshot], days: float, now: datetime | None = None) -> tuple[int, float] | None:
    """Follower change over roughly ``days``: (gain, actual_span_days), or None without enough data.

    Compares the latest snapshot with the newest one at least ``days`` older; when history is shorter
    than ``days`` the oldest snapshot is used so young accounts still get a rate.
    """
    ordered = sorted(snapshots, key=lambda item: item[0])
    if len(ordered) < 2:
        return None
    latest_time, latest_value = ordered[-1]
    cutoff = (now or latest_time) - timedelta(days=days)
    base = ordered[0]
    for item in ordered[:-1]:
        if item[0] <= cutoff:
            base = item
    span = (latest_time - base[0]).total_seconds() / 86400
    if span <= 0:
        return None
    return latest_value - base[1], span


def evaluate(
    plan: MilestonePlan,
    snapshots: Sequence[Snapshot],
    today: date,
    starting_followers: int = 0,
) -> MilestoneStatus:
    """Where the account stands against the active milestone and whether the pace reaches it."""
    ordered = sorted(snapshots, key=lambda item: item[0])
    followers = ordered[-1][1] if ordered else None

    index = 0
    while followers is not None and followers >= plan.target(index):
        index += 1
    target = plan.target(index)
    previous = plan.target(index - 1) if index > 0 else starting_followers
    achieved = tuple(plan.target(i) for i in range(index))
    deadline = plan.deadline(index)
    days_left = (deadline - today).days
    remaining = max(target - (followers or 0), 0)

    span = target - previous
    progress = 0.0 if followers is None or span <= 0 else min(max((followers - previous) / span, 0.0), 1.0)

    recent = delta_over(ordered, 7)
    recent_per_day = None if recent is None else recent[0] / recent[1]
    required_per_day = remaining / days_left if days_left > 0 else None
    projected = None
    if followers is not None and recent_per_day is not None and days_left > 0:
        projected = int(round(followers + max(recent_per_day, 0.0) * days_left))

    if followers is None:
        status = "no_data"
    elif days_left <= 0:
        status = "overdue"
    elif projected is None:
        status = "no_data"
    elif projected >= target:
        status = "on_track"
    elif projected >= 0.6 * target:
        status = "at_risk"
    else:
        status = "behind"

    return MilestoneStatus(
        status=status,
        target=target,
        target_index=index,
        previous_target=previous,
        deadline=deadline,
        followers=followers,
        progress=progress,
        days_left=days_left,
        remaining=remaining,
        required_per_day=required_per_day,
        recent_per_day=recent_per_day,
        projected_at_deadline=projected,
        achieved_targets=achieved,
    )
