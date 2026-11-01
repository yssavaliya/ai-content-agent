import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from ai_content_agent.database.connection import DatabaseConnection, initialize_database
from ai_content_agent.growth import dedupe, usage
from ai_content_agent.growth.dashboard import collect_dashboard_data, generate_dashboard, render_dashboard
from ai_content_agent.growth.followers import (
    FollowerCount,
    FollowerSourceError,
    InstagramFollowerSource,
    daily_series,
    load_snapshots,
    record_snapshot,
)
from ai_content_agent.growth.health import check_health
from ai_content_agent.growth.insights import performance_insights
from ai_content_agent.growth.milestones import MilestonePlan, delta_over, evaluate
from ai_content_agent.settings import load_settings

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def snaps(*pairs: tuple[int, int]) -> list[tuple[datetime, int]]:
    """(days_ago, followers) pairs relative to NOW."""
    return [(NOW - timedelta(days=days), followers) for days, followers in pairs]


def make_settings(**extra):
    env = {
        "LOG_LEVEL": "INFO",
        "DATABASE_PATH": ":memory:",
        "OPENCODE_COMMAND": "opencode",
        "INSTAGRAM_ENABLED": "false",
        "IMAGE_PROVIDER": "local",
    }
    env.update(extra)
    return load_settings(env=env, env_file=Path("does-not-exist.env"))


class MilestoneTests(unittest.TestCase):
    def setUp(self):
        self.plan = MilestonePlan(start_date=date(2026, 11, 1))

    def test_targets_compound_by_two_and_a_half_every_period(self):
        self.assertEqual([self.plan.target(i) for i in range(4)], [1000, 2500, 6250, 15625])

    def test_each_target_is_due_one_period_after_the_previous(self):
        self.assertEqual(self.plan.deadline(0), date(2026, 11, 1) + timedelta(days=90))
        self.assertEqual(self.plan.deadline(1), date(2026, 11, 1) + timedelta(days=180))

    def test_no_snapshots_means_no_data(self):
        status = evaluate(self.plan, [], date(2026, 11, 10))
        self.assertEqual(status.status, "no_data")
        self.assertIsNone(status.followers)
        self.assertEqual(status.target, 1000)

    def test_on_track_when_pace_reaches_the_target(self):
        # +80 in 7 days (~11.4/day) with 81 days left projects to ~1105, past the 1000 target.
        status = evaluate(self.plan, snaps((7, 100), (0, 180)), date(2026, 11, 10), starting_followers=100)
        self.assertEqual(status.status, "on_track")
        self.assertGreaterEqual(status.projected_at_deadline, 1000)

    def test_at_risk_when_projection_is_close_but_short(self):
        # +70 in 7 days (10/day) projects to 980: short of 1000 but above 60% of it.
        status = evaluate(self.plan, snaps((7, 100), (0, 170)), date(2026, 11, 10), starting_followers=100)
        self.assertEqual(status.status, "at_risk")
        self.assertEqual(status.projected_at_deadline, 980)

    def test_behind_when_pace_is_far_too_slow(self):
        status = evaluate(self.plan, snaps((7, 100), (0, 107)), date(2026, 11, 10), starting_followers=100)
        self.assertEqual(status.status, "behind")

    def test_overdue_after_the_deadline(self):
        status = evaluate(self.plan, snaps((7, 100), (0, 130)), date(2027, 3, 1), starting_followers=100)
        self.assertEqual(status.status, "overdue")

    def test_reaching_a_target_advances_to_the_next(self):
        status = evaluate(self.plan, snaps((7, 900), (0, 1010)), date(2026, 11, 10), starting_followers=100)
        self.assertEqual(status.target, 2500)
        self.assertEqual(status.achieved_targets, (1000,))
        self.assertEqual(status.deadline, self.plan.deadline(1))
        self.assertGreater(status.progress, 0)

    def test_negative_pace_never_projects_below_current(self):
        status = evaluate(self.plan, snaps((7, 200), (0, 150)), date(2026, 11, 10), starting_followers=100)
        self.assertEqual(status.projected_at_deadline, 150)

    def test_delta_over_uses_oldest_snapshot_for_short_history(self):
        gain, span = delta_over(snaps((3, 100), (0, 130)), 7, NOW)
        self.assertEqual(gain, 30)
        self.assertAlmostEqual(span, 3.0)

    def test_delta_over_needs_two_snapshots(self):
        self.assertIsNone(delta_over(snaps((0, 100)), 7, NOW))


class FollowerTests(unittest.TestCase):
    @patch("ai_content_agent.growth.followers.requests.get")
    def test_instagram_source_reads_followers_count(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = {"followers_count": 321, "media_count": 12}
        count = InstagramFollowerSource("tok", "111").fetch()
        self.assertEqual((count.followers, count.media_count, count.source), (321, 12, "instagram"))
        self.assertEqual(mock_get.call_args.kwargs["params"]["fields"], "followers_count,media_count")

    @patch("ai_content_agent.growth.followers.requests.get")
    def test_network_error_does_not_leak_the_token(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("failed: https://graph.facebook.com/v21.0/1?access_token=SECRET9")
        with self.assertRaises(FollowerSourceError) as ctx:
            InstagramFollowerSource("SECRET9", "1").fetch()
        self.assertNotIn("SECRET9", str(ctx.exception))

    @patch("ai_content_agent.growth.followers.requests.get")
    def test_http_error_and_bad_payload_are_rejected(self, mock_get):
        mock_get.return_value = MagicMock(status_code=400, text="bad token")
        with self.assertRaises(FollowerSourceError):
            InstagramFollowerSource("t", "1").fetch()
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = {"id": "1"}
        with self.assertRaises(FollowerSourceError):
            InstagramFollowerSource("t", "1").fetch()

    def test_snapshots_round_trip_and_daily_series_keeps_last_per_day(self):
        db = DatabaseConnection(db_path=":memory:")
        try:
            record_snapshot(db, FollowerCount(100, None, "manual"), iso(NOW - timedelta(days=1, hours=5)))
            record_snapshot(db, FollowerCount(110, None, "manual"), iso(NOW - timedelta(days=1)))
            record_snapshot(db, FollowerCount(130, 9, "instagram"), iso(NOW))
            series = daily_series(load_snapshots(db))
            self.assertEqual([value for _, value in series], [110, 130])
            with self.assertRaises(ValueError):
                record_snapshot(db, FollowerCount(-1, None, "manual"))
        finally:
            db.close()


class DedupeTests(unittest.TestCase):
    def test_normalize_ignores_hashtags_urls_emoji_and_case(self):
        self.assertEqual(dedupe.normalize("Hello, WORLD! 🔥 #tag https://x.io/a"), "hello world")

    def test_identical_and_reworded_captions_score_high_unrelated_low(self):
        base = "Relentless focus beats noisy talent every single time."
        self.assertEqual(dedupe.similarity(base, base + " #anime"), 1.0)
        self.assertGreater(dedupe.similarity(base, "Relentless focus beats noisy talent every time!"), 0.85)
        self.assertLess(dedupe.similarity(base, "A glowing blade splits the eclipse over the harbor."), 0.5)

    def test_find_similar_caption_respects_threshold_and_exclusion(self):
        db = DatabaseConnection(db_path=":memory:")
        try:
            db.execute("INSERT INTO research_raw(provider,title,source,summary,category,retrieved_at,normalized_at,raw_payload) VALUES ('p','t','s','s','c','x','x','{}')")
            db.execute("INSERT INTO planner_ideas(research_id,idea_text,educational_score,originality_score,engagement_score,relevance_score,total_score,selected,reasoning,created_at) VALUES (1,'i',0,0,0,0,0,1,'r','x')")
            for caption in ("Discipline outlasts motivation every single day.", "A completely unrelated caption about blades."):
                db.execute(
                    "INSERT INTO creator_outputs(planner_id,carousel_outline,caption,cta,hashtags,image_prompt,alt_text,markdown_path,json_path,created_at) VALUES (1,'[]',?,'c','[]','p','a','','','x')",
                    (caption,),
                )
            hit = dedupe.find_similar_caption(db, "Discipline outlasts motivation every single day!", 0.85)
            self.assertIsNotNone(hit)
            self.assertEqual(hit.creator_output_id, 1)
            self.assertIsNone(dedupe.find_similar_caption(db, "Discipline outlasts motivation every single day!", 0.85, exclude_id=1))
            self.assertIsNone(dedupe.find_similar_caption(db, "Totally new words here about harbors and neon.", 0.85))
        finally:
            db.close()


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "agent.db"
        initialize_database(self.db_path)
        self._env = patch.dict(
            os.environ,
            {
                "LOG_LEVEL": "INFO",
                "DATABASE_PATH": str(self.db_path),
                "OPENCODE_COMMAND": "opencode",
                "INSTAGRAM_ENABLED": "false",
                "IMAGE_PROVIDER": "local",
                "LLM_COST_PER_1K_TOKENS": "0.002",
            },
        )
        self._env.start()
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)  # no stray .env

    def tearDown(self):
        os.chdir(self._cwd)
        self._env.stop()
        self.tmp.cleanup()

    def test_records_calls_and_prices_only_paid_providers(self):
        usage.record_usage("llm", "chat", provider="openai", model="m", input_tokens=1000, output_tokens=1000, duration_ms=5)
        usage.record_usage("llm", "chat", provider="opencode", ok=False)
        connection = sqlite3.connect(self.db_path)
        try:
            rows = connection.execute("SELECT provider, ok, est_cost_usd FROM api_usage ORDER BY id").fetchall()
        finally:
            connection.close()
        self.assertEqual(rows, [("openai", 1, 0.004), ("opencode", 0, 0.0)])

    def test_summary_groups_by_provider(self):
        usage.record_usage("llm", "chat", provider="gemini", input_tokens=10, output_tokens=5)
        usage.record_usage("llm", "chat", provider="gemini", ok=False)
        db = DatabaseConnection(self.db_path)
        try:
            summary = usage.usage_summary(db, "2000-01-01T00:00:00Z")
        finally:
            db.close()
        self.assertEqual((summary[0]["provider"], summary[0]["calls"], summary[0]["failures"]), ("gemini", 2, 1))

    def test_never_raises_and_never_creates_a_database(self):
        missing = Path(self.tmp.name) / "missing.db"
        with patch.dict(os.environ, {"DATABASE_PATH": str(missing)}):
            usage.record_usage("llm", "chat", provider="openai")
            self.assertFalse(missing.exists())
        with patch.dict(os.environ, {"DATABASE_PATH": ":memory:"}):
            usage.record_usage("llm", "chat", provider="openai")
        with patch("ai_content_agent.growth.usage.current_settings", side_effect=RuntimeError("boom")):
            usage.record_usage("llm", "chat", provider="openai")

    def test_as_int_rejects_mocks_and_bools(self):
        self.assertEqual(usage.as_int(7), 7)
        self.assertIsNone(usage.as_int(MagicMock()))
        self.assertIsNone(usage.as_int(True))


def add_measured_post(db, external_id, caption, rate, arm=None, age_days=2):
    created = iso(NOW - timedelta(days=age_days))
    post_id = db.execute(
        "INSERT INTO posts(external_id, caption, image_description, hashtags, created_at) VALUES (?, ?, 'd', '[]', ?)",
        (external_id, caption, created),
    ).lastrowid
    db.execute(
        "INSERT INTO post_metrics(post_id, media_id, impressions, reach, likes, comments, shares, saves, engagement, engagement_rate, collected_at, raw_payload) "
        "VALUES (?, ?, 100, 80, 5, 1, 2, 3, 11, ?, ?, '{}')",
        (post_id, external_id, rate, created),
    )
    if arm:
        db.execute("INSERT INTO experiments(name, description, started_at, status) VALUES (?, 'd', 'x', 'active')", (f"e-{external_id}",))
        exp_id = db.execute("SELECT MAX(id) FROM experiments").fetchone()[0]
        db.execute("INSERT INTO experiment_posts(experiment_id, post_id, arm, assigned_at) VALUES (?, ?, ?, 'x')", (exp_id, post_id, arm))
    return post_id


class InsightsTests(unittest.TestCase):
    def test_empty_when_nothing_is_measured(self):
        db = DatabaseConnection(db_path=":memory:")
        try:
            self.assertEqual(performance_insights(db), "")
        finally:
            db.close()

    def test_lists_best_and_weakest_posts(self):
        db = DatabaseConnection(db_path=":memory:")
        try:
            for index, rate in enumerate([0.01, 0.05, 0.09, 0.02, 0.07, 0.03, 0.04]):
                add_measured_post(db, f"m{index}", f"Caption number {index}", rate, arm="variant" if index == 2 else None)
            text = performance_insights(db, count=2)
            self.assertIn("Best performing", text)
            self.assertIn("Caption number 2", text)
            self.assertIn("experiment arm: variant", text)
            self.assertIn("Weakest", text)
            self.assertIn("Caption number 0", text)
        finally:
            db.close()


class BestAndWorstOverlapTests(unittest.TestCase):
    def test_a_post_is_never_both_best_and_weakest(self):
        from ai_content_agent.growth.insights import top_and_bottom_posts

        db = DatabaseConnection(db_path=":memory:")
        try:
            self.assertEqual(top_and_bottom_posts(db, 5), ([], []))
            add_measured_post(db, "only", "Only post", 0.05)
            best, worst = top_and_bottom_posts(db, 5)
            self.assertEqual(([p["caption"] for p in best], worst), (["Only post"], []))
            for index, rate in enumerate([0.09, 0.08, 0.04, 0.03, 0.02]):
                add_measured_post(db, f"m{index}", f"Post {index}", rate)
            best, worst = top_and_bottom_posts(db, 5)  # 6 posts: 3 best, 3 weakest, no overlap
            best_ids, worst_ids = {p["id"] for p in best}, {p["id"] for p in worst}
            self.assertEqual((len(best_ids), len(worst_ids)), (3, 3))
            self.assertFalse(best_ids & worst_ids)
            self.assertEqual(worst[0]["engagement_rate"], 0.02)  # weakest first
        finally:
            db.close()


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseConnection(db_path=":memory:")
        self.plan = MilestonePlan(start_date=date(2026, 11, 1))

    def tearDown(self):
        self.db.close()

    def test_flags_missing_posts_and_followers_on_a_fresh_install(self):
        issues = check_health(self.db, self.plan, NOW)
        self.assertTrue(any("No post has been recorded" in i for i in issues))
        self.assertTrue(any("No follower count" in i for i in issues))

    def test_healthy_when_posting_and_followers_are_fresh_and_growing(self):
        add_measured_post(self.db, "m1", "c", 0.05, age_days=1)
        record_snapshot(self.db, FollowerCount(100, None, "manual"), iso(NOW - timedelta(days=7)))
        record_snapshot(self.db, FollowerCount(190, None, "manual"), iso(NOW))
        self.assertEqual(check_health(self.db, self.plan, NOW), [])

    def test_flags_stale_posts_and_stale_followers(self):
        add_measured_post(self.db, "m1", "c", 0.05, age_days=10)
        record_snapshot(self.db, FollowerCount(100, None, "manual"), iso(NOW - timedelta(days=9)))
        issues = check_health(self.db, self.plan, NOW)
        self.assertTrue(any("No post recorded in the last 3 days" in i for i in issues))
        self.assertTrue(any("not been refreshed" in i for i in issues))

    def test_flags_repeated_fallbacks_blocks_and_api_failures(self):
        for status, metadata in (("blocked_duplicate", '{"fallbacks": ["creator"]}'), ("blocked_review", '{"fallbacks": ["research"]}')):
            self.db.execute(
                "INSERT INTO research_raw(provider,title,source,summary,category,retrieved_at,normalized_at,raw_payload) VALUES ('p','t','s','s','c','x','x','{}')"
            )
            self.db.execute("INSERT INTO planner_ideas(research_id,idea_text,educational_score,originality_score,engagement_score,relevance_score,total_score,selected,reasoning,created_at) VALUES (1,'i',0,0,0,0,0,1,'r','x')")
            self.db.execute("INSERT INTO creator_outputs(planner_id,carousel_outline,caption,cta,hashtags,image_prompt,alt_text,markdown_path,json_path,created_at) VALUES (1,'[]','c','c','[]','p','a','','','x')")
            self.db.execute(
                "INSERT INTO publish_packages(creator_output_id,status,published_id,package_path,metadata,created_at) VALUES (1,?,'',?,?,'x')",
                (status, "p", metadata),
            )
        for _ in range(5):
            self.db.execute(
                "INSERT INTO api_usage(created_at, service, operation, provider, ok) VALUES (?, 'llm', 'chat', 'gemini', 0)",
                (iso(NOW - timedelta(hours=1)),),
            )
        issues = check_health(self.db, self.plan, NOW)
        self.assertTrue(any("template fallback" in i for i in issues))
        self.assertTrue(any("were blocked" in i for i in issues))
        self.assertTrue(any("API calls failed" in i for i in issues))


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseConnection(db_path=":memory:")
        self.settings = make_settings(GROWTH_START_DATE="2026-11-01")

    def tearDown(self):
        self.db.close()

    def test_empty_database_still_renders(self):
        html = render_dashboard(collect_dashboard_data(self.db, self.settings, NOW))
        self.assertIn("Milestone progress", html)
        self.assertIn("No data yet", html)
        self.assertIn("No measured posts yet.", html)
        self.assertIn("No experiments yet.", html)

    def test_renders_followers_growth_posts_and_progress(self):
        record_snapshot(self.db, FollowerCount(100, None, "manual"), iso(NOW - timedelta(days=7)))
        record_snapshot(self.db, FollowerCount(160, None, "manual"), iso(NOW))
        add_measured_post(self.db, "m1", "Best caption", 0.12)
        data = collect_dashboard_data(self.db, self.settings, NOW)
        html = render_dashboard(data)
        self.assertEqual(data["week_gain"], 60)
        self.assertIn("+60", html)
        self.assertIn("Best caption", html)
        self.assertIn("12.0%", html)
        self.assertIn("<polyline", html)
        self.assertIn("1,000", html)

    def test_untrusted_text_is_escaped(self):
        add_measured_post(self.db, "m1", '<script>alert("x")</script> caption', 0.1)
        html = render_dashboard(collect_dashboard_data(self.db, self.settings, NOW))
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)

    def test_generate_writes_a_self_contained_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_dashboard(self.db, self.settings, Path(tmp) / "nested" / "index.html")
            text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("<!doctype html>"))
        self.assertNotIn("http://", text.replace("http://www.w3.org", ""))
        self.assertNotIn("<script", text)


if __name__ == "__main__":
    unittest.main()
