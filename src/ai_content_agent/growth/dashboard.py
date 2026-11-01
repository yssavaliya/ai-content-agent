from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any, Sequence

from ..database.connection import DatabaseConnection
from ..science.experiments import ExperimentRepository, compute_experiment_result
from ..settings import Settings
from ..timestamps import format_utc
from .followers import daily_series, load_snapshots, starting_point
from .health import check_health
from .insights import top_and_bottom_posts
from .milestones import MilestonePlan, MilestoneStatus, delta_over, evaluate
from .usage import usage_summary


def build_plan(settings: Settings, db: DatabaseConnection, today: date) -> MilestonePlan:
    if settings.growth_start_date:
        start = date.fromisoformat(settings.growth_start_date)
    else:
        first = starting_point(db)
        start = first[0].date() if first else today
    return MilestonePlan(
        start_date=start,
        base_target=settings.growth_base_target,
        multiplier=settings.growth_multiplier,
        period_days=settings.growth_period_days,
    )


def collect_dashboard_data(db: DatabaseConnection, settings: Settings, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    today = now.date()
    snapshots = load_snapshots(db)
    plan = build_plan(settings, db, today)
    first = starting_point(db)
    milestone = evaluate(plan, snapshots, today, starting_followers=first[1] if first else 0)

    day_gain = delta_over(snapshots, 1, now)
    week_gain = delta_over(snapshots, 7, now)

    totals = db.fetch_all(
        "SELECT COUNT(*) AS posts, COALESCE(SUM(pm.impressions), 0) AS impressions, COALESCE(SUM(pm.reach), 0) AS reach, "
        "COALESCE(SUM(pm.shares), 0) AS shares, COALESCE(SUM(pm.saves), 0) AS saves, "
        "COALESCE(SUM(pm.comments), 0) AS comments, COALESCE(SUM(pm.likes), 0) AS likes, "
        "AVG(pm.engagement_rate) AS engagement_rate FROM post_metrics pm WHERE pm.id = "
        "(SELECT MAX(id) FROM post_metrics WHERE post_id = pm.post_id)"
    )[0]
    published = db.fetch_all("SELECT COUNT(*) AS n FROM posts")[0]["n"]
    best, worst = top_and_bottom_posts(db, 5)

    experiments = []
    repository = ExperimentRepository(db)
    for row in db.fetch_all("SELECT id, name, variable, status, control_description, variant_description FROM experiments ORDER BY id"):
        try:
            result = compute_experiment_result(row["id"], db).to_dict()
        except Exception:  # noqa: BLE001 - an experiment without data must not break the dashboard
            result = None
        experiments.append({**row, "result": result, "n_posts": len(repository.posts_for_arm(row["id"], "control")) + len(repository.posts_for_arm(row["id"], "variant"))})

    runs = db.fetch_all("SELECT status, metadata, created_at FROM publish_packages ORDER BY id DESC LIMIT 14")
    run_summary = {"total": len(runs), "fallback_runs": 0, "blocked": 0, "statuses": {}}
    for run in runs:
        run_summary["statuses"][run["status"]] = run_summary["statuses"].get(run["status"], 0) + 1
        run_summary["blocked"] += 1 if str(run["status"]).startswith("blocked_") else 0
        try:
            run_summary["fallback_runs"] += 1 if json.loads(run["metadata"] or "{}").get("fallbacks") else 0
        except ValueError:
            pass

    return {
        "generated_at": format_utc(now),
        "milestone": milestone,
        "series": daily_series(snapshots),
        "day_gain": day_gain[0] if day_gain else None,
        "week_gain": week_gain[0] if week_gain else None,
        "totals": totals,
        "published": published,
        "best": best,
        "worst": worst,
        "experiments": experiments,
        "runs": run_summary,
        "usage": usage_summary(db, format_utc(now - timedelta(days=30), "microseconds")),
        "issues": check_health(db, plan, now),
    }


def _line_chart(points: Sequence[tuple[str, int]], width: int = 640, height: int = 180) -> str:
    if len(points) < 2:
        return '<p class="muted">Not enough follower history for a chart yet (needs two days of snapshots).</p>'
    values = [value for _, value in points]
    low, high = min(values), max(values)
    span = max(high - low, 1)
    pad = 28
    step = (width - 2 * pad) / (len(points) - 1)
    coords = [(pad + i * step, height - pad - (value - low) / span * (height - 2 * pad)) for i, (_, value) in enumerate(points)]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Followers over time, '
        f'{escape(points[0][0])} to {escape(points[-1][0])}, from {low} to {high}">'
        f'<polyline fill="none" stroke="var(--accent)" stroke-width="2.5" points="{path}"/>'
        f'<circle cx="{coords[-1][0]:.1f}" cy="{coords[-1][1]:.1f}" r="4" fill="var(--accent)"/>'
        f'<text x="{pad}" y="{height - 6}" class="axis">{escape(points[0][0])}</text>'
        f'<text x="{width - pad}" y="{height - 6}" class="axis" text-anchor="end">{escape(points[-1][0])}</text>'
        f'<text x="{pad}" y="14" class="axis">{high}</text><text x="{pad}" y="{height - pad - 4}" class="axis">{low}</text>'
        "</svg>"
    )


def _fmt(value: object, digits: int = 0) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    if isinstance(value, int):
        return f"{value:,}"
    return escape(str(value))


def _gain(value: int | None) -> str:
    return "—" if value is None else f"{value:+,}"


_STATUS_LABEL = {
    "no_data": ("No data yet", "neutral"),
    "on_track": ("On track", "good"),
    "at_risk": ("At risk", "warn"),
    "behind": ("Behind pace", "bad"),
    "overdue": ("Overdue", "bad"),
}


def _milestone_card(m: MilestoneStatus) -> str:
    label, tone = _STATUS_LABEL[m.status]
    pct = round(m.progress * 100)
    rows = [
        ("Followers now", _fmt(m.followers)),
        ("Active target", f"{m.target:,}"),
        ("Deadline", f"{m.deadline.isoformat()} ({m.days_left} days left)"),
        ("Still needed", f"{m.remaining:,}"),
        ("Needed per day", _fmt(m.required_per_day, 1)),
        ("Pace (last 7 days)", _fmt(m.recent_per_day, 1) + (" / day" if m.recent_per_day is not None else "")),
        ("Projected at deadline", _fmt(m.projected_at_deadline)),
    ]
    achieved = ", ".join(f"{t:,}" for t in m.achieved_targets) or "none yet"
    table = "".join(f"<tr><th>{escape(k)}</th><td>{v}</td></tr>" for k, v in rows)
    return (
        f'<section class="card wide"><h2>Milestone progress <span class="pill {tone}">{label}</span></h2>'
        f'<div class="bar" role="progressbar" aria-valuenow="{pct}" aria-valuemin="0" aria-valuemax="100" '
        f'aria-label="Progress to {m.target} followers"><span style="width:{pct}%"></span></div>'
        f'<p class="muted">{pct}% of the way from {m.previous_target:,} to {m.target:,}. Reached targets: {escape(achieved)}.</p>'
        f"<table>{table}</table></section>"
    )


def _post_rows(posts: list[dict]) -> str:
    if not posts:
        return '<tr><td colspan="5" class="muted">No measured posts yet.</td></tr>'
    out = []
    for post in posts:
        caption = " ".join(str(post["caption"]).split())
        caption = caption if len(caption) <= 80 else caption[:79] + "…"
        out.append(
            f"<tr><td>{escape(caption)}</td><td>{post['engagement_rate'] * 100:.1f}%</td>"
            f"<td>{_fmt(post['reach'])}</td><td>{_fmt(post['saves'])} / {_fmt(post['shares'])}</td>"
            f"<td>{escape(str(post['arm'] or '—'))}</td></tr>"
        )
    return "".join(out)


def render_dashboard(data: dict[str, Any], title: str = "Growth dashboard") -> str:
    m: MilestoneStatus = data["milestone"]
    t = data["totals"]
    runs = data["runs"]
    issues = data["issues"]

    issue_html = (
        "<ul>" + "".join(f"<li>{escape(issue)}</li>" for issue in issues) + "</ul>"
        if issues
        else '<p class="good-text">No action needed: publishing, follower tracking and APIs look healthy.</p>'
    )
    experiment_rows = ""
    for exp in data["experiments"]:
        res = exp["result"]
        outcome = (
            f"{res['winner']} (control {res['control_mean'] * 100:.2f}% vs variant {res['variant_mean'] * 100:.2f}%, "
            f"n={res['n_control']}/{res['n_variant']}, p={res['p_value']:.3f})"
            if res and res["n_control"] + res["n_variant"] > 0
            else "collecting data"
        )
        experiment_rows += (
            f"<tr><td>{escape(exp['name'])}</td><td>{escape(str(exp['variable'] or '—'))}</td>"
            f"<td>{escape(exp['status'])}</td><td>{exp['n_posts']}</td><td>{escape(outcome)}</td></tr>"
        )
    experiment_rows = experiment_rows or '<tr><td colspan="5" class="muted">No experiments yet.</td></tr>'

    usage_rows = "".join(
        f"<tr><td>{escape(u['service'])}</td><td>{escape(u['provider'])}</td><td>{u['calls']}</td><td>{u['failures']}</td>"
        f"<td>{u['input_tokens'] + u['output_tokens']:,}</td><td>${u['est_cost_usd']:.4f}</td></tr>"
        for u in data["usage"]
    ) or '<tr><td colspan="6" class="muted">No API calls recorded in the last 30 days.</td></tr>'

    status_text = ", ".join(f"{escape(str(k))}: {v}" for k, v in sorted(runs["statuses"].items())) or "no runs yet"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
:root {{ --bg:#f6f7fb; --card:#fff; --text:#161a23; --muted:#5d6678; --line:#e3e6ee; --accent:#6d4aff; --good:#0e8a4f; --warn:#b36b00; --bad:#c62828; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0f1117; --card:#181b24; --text:#eceff6; --muted:#9aa3b5; --line:#2a2f3c; --accent:#9a82ff; --good:#4cd08a; --warn:#f0b04a; --bad:#ff7b7b; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:1.5rem; margin:0 0 4px; }} h2 {{ font-size:1.05rem; margin:0 0 12px; }}
.muted {{ color:var(--muted); }} .good-text {{ color:var(--good); }}
.grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); margin-top:16px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; overflow-x:auto; }}
.wide {{ grid-column:1/-1; }}
.stat {{ font-size:1.8rem; font-weight:700; }}
.pill {{ font-size:.75rem; padding:2px 8px; border-radius:99px; border:1px solid currentColor; vertical-align:middle; }}
.pill.good {{ color:var(--good); }} .pill.warn {{ color:var(--warn); }} .pill.bad {{ color:var(--bad); }} .pill.neutral {{ color:var(--muted); }}
.bar {{ height:12px; background:var(--line); border-radius:99px; overflow:hidden; }} .bar span {{ display:block; height:100%; background:var(--accent); }}
table {{ width:100%; border-collapse:collapse; font-size:.9rem; }} th,td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ color:var(--muted); font-weight:600; }}
svg {{ width:100%; height:auto; }} .axis {{ fill:var(--muted); font-size:11px; }}
ul {{ margin:0; padding-left:20px; }}
</style>
</head>
<body>
<main>
<h1>{escape(title)}</h1>
<p class="muted">Generated {escape(data['generated_at'])}. Built from the agent's own database: nothing here is estimated by an LLM.</p>

<div class="grid">
  <section class="card"><h2>Followers</h2><div class="stat">{_fmt(m.followers)}</div>
    <p class="muted">Today {_gain(data['day_gain'])} · last 7 days {_gain(data['week_gain'])}</p></section>
  <section class="card"><h2>Reach &amp; impressions</h2><div class="stat">{_fmt(int(t['reach']))}</div>
    <p class="muted">{_fmt(int(t['impressions']))} impressions across {t['posts']} measured of {data['published']} recorded posts</p></section>
  <section class="card"><h2>Engagement rate</h2><div class="stat">{(t['engagement_rate'] or 0) * 100:.1f}%</div>
    <p class="muted">Average of each post's latest rate</p></section>
  <section class="card"><h2>Saves · shares · comments</h2><div class="stat">{_fmt(int(t['saves']))} · {_fmt(int(t['shares']))} · {_fmt(int(t['comments']))}</div>
    <p class="muted">Lifetime totals across measured posts</p></section>
</div>

<div class="grid">
{_milestone_card(m)}
  <section class="card wide"><h2>Follower growth</h2>{_line_chart(data['series'])}</section>
  <section class="card wide"><h2>Needs attention</h2>{issue_html}</section>
  <section class="card wide"><h2>Best performing posts</h2>
    <table><tr><th>Caption</th><th>Engagement</th><th>Reach</th><th>Saves / shares</th><th>Arm</th></tr>{_post_rows(data['best'])}</table></section>
  <section class="card wide"><h2>Weakest posts</h2>
    <table><tr><th>Caption</th><th>Engagement</th><th>Reach</th><th>Saves / shares</th><th>Arm</th></tr>{_post_rows(data['worst'])}</table></section>
  <section class="card wide"><h2>Experiments</h2>
    <table><tr><th>Name</th><th>Variable</th><th>Status</th><th>Posts</th><th>Outcome</th></tr>{experiment_rows}</table></section>
  <section class="card"><h2>Recent runs</h2><p>Last {runs['total']} runs: {status_text}</p>
    <p class="muted">{runs['fallback_runs']} used template fallback content · {runs['blocked']} blocked</p></section>
  <section class="card wide"><h2>API usage (30 days)</h2>
    <table><tr><th>Service</th><th>Provider</th><th>Calls</th><th>Failures</th><th>Tokens</th><th>Est. cost</th></tr>{usage_rows}</table>
    <p class="muted">Cost is only estimated for paid providers when LLM_COST_PER_1K_TOKENS is set; free providers show volume and failures.</p></section>
</div>
</main>
</body>
</html>
"""


def generate_dashboard(db: DatabaseConnection, settings: Settings, output_path: str | Path, title: str = "Growth dashboard") -> Path:
    html = render_dashboard(collect_dashboard_data(db, settings), title)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
