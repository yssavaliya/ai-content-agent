from __future__ import annotations

import sys
from typing import Any, Sequence

from .application.scheduler import Scheduler
from .logging_config import setup_logging

USAGE = """Usage: ai-content-agent [command]

Commands:
  daily       Run the full content pipeline (research, plan, create, review, image, publish).
  analytics   Collect Instagram insights for published posts.
  scientist   Run the Scientist learning loop (experiments, analysis, strategy updates).
  monthly     Generate a monthly performance digest.
  prompts       Generate the HTML prompt viewer from recorded prompts (logs/prompts).
  anime-trends  Fetch real-world trending anime metadata from Kitsu API.
  anime-concept Generate original anime concept, characters, and episode breakdown.
  help          Show this help.

With no command, 'daily' is assumed.
"""


def _print_daily_results(result: dict[str, Any]) -> None:
    package = result.get("package") or {}
    print("AI Content Agent run completed.")
    print(f"Run id: {package.get('run_id')}")

    research = package.get("research") or {}
    print(f"Research topic: {research.get('recommended_topic')}")
    print(f"Research confidence: {research.get('confidence')}")
    print(f"Research id: {research.get('research_id')}")

    creation = package.get("creation") or {}
    print("Created draft:")
    print(f" - Caption: {creation.get('caption')}")
    print(f" - CTA: {creation.get('cta')}")
    print(f" - Hashtags: {', '.join(creation.get('hashtags', []))}")

    review = package.get("review") or {}
    print(f"Review: {review.get('status')}")

    image = package.get("image") or {}
    print(f"Image provider: {image.get('provider')}")
    print(f"Image file: {image.get('file_path')}")
    if image.get("media_url"):
        print(f"Media URL: {image.get('media_url')}")

    publish = package.get("publish") or {}
    print(f"Publish status: {publish.get('status')}")
    print(f"Publish id: {publish.get('published_id')}")


def _print_analytics(result: dict[str, Any]) -> None:
    summary = result.get("summary") or {}
    print("Analytics collection complete.")
    print(f"Enabled: {summary.get('enabled')}")
    if summary.get("enabled"):
        print(f"Posts considered: {summary.get('posts_considered')}")
        print(f"Collected: {summary.get('collected')}")
        print(f"Failed: {summary.get('failed')}")
        for failure in summary.get("failures", []):
            print(f" - post {failure.get('post_id')} ({failure.get('media_id')}): {failure.get('error')}")


def _print_scientist(result: dict[str, Any]) -> None:
    print("Scientist analysis complete.")
    print(f"Experiment id: {result.get('experiment_id')}")
    for experiment_result in result.get("results", []):
        print(
            f" - experiment {experiment_result.get('experiment_id')}: "
            f"d={experiment_result.get('cohens_d')}, "
            f"p={experiment_result.get('p_value')}, "
            f"winner={experiment_result.get('winner')}"
        )
    if result.get("note"):
        print(result["note"])
    print(f"Recommendations: {result.get('applied_count', 0)} applied")
    for outcome in result.get("outcomes", []):
        status = "applied" if outcome.get("applied") else f"rejected ({outcome.get('reason')})"
        print(f" - {outcome.get('variable')}: {status}")
    if result.get("summary"):
        print(f"Summary: {result.get('summary')}")


def _print_monthly(result: dict[str, Any]) -> None:
    digest = result.get("digest") or {}
    print("Monthly report complete.")
    print(f"Published posts: {digest.get('published_posts')}")
    print(f"Experiments completed: {digest.get('experiments_completed')}")
    print(f"Strategy changes applied: {digest.get('strategy_changes')}")
    print(f"Analytics observations: {digest.get('observations')}")


COMMANDS = ("daily", "analytics", "scientist", "monthly", "prompts", "anime-trends", "anime-concept")


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = list(argv) if argv is not None else sys.argv[1:]

    command = args[0] if args else "daily"

    if command in ("help", "--help", "-h"):
        print(USAGE)
        return 0
    if command not in COMMANDS:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2

    try:
        setup_logging()
        if command == "prompts":
            from .diagnostics.prompt_viewer import generate_html

            output = generate_html()
            print(f"Prompt viewer generated: {output}")
            return 0

        if command == "anime-trends":
            from .anime.metadata import AnimeMetadataClient

            client = AnimeMetadataClient()
            trends = client.get_trending(limit=5)
            print("=== Real-World Trending Anime (Kitsu API) ===")
            for i, item in enumerate(trends, 1):
                print(f"{i}. {item.title} ({item.japanese_title or 'N/A'})")
                print(f"   Rating: {item.average_rating or 'N/A'}% | Episodes: {item.episode_count or 'TBD'} | Status: {item.status}")
                print(f"   Synopsis: {item.synopsis[:140]}...")
            return 0

        if command == "anime-concept":
            from .anime.generator import AnimeContentGenerator

            theme = args[1] if len(args) > 1 else "Astrophysics and Ancient Indian Astronomy"
            generator = AnimeContentGenerator()
            concept = generator.generate_concept(theme=theme)
            chars = generator.generate_characters(concept=concept, count=2)
            outline = generator.generate_episode_outline(concept=concept, characters=chars, episode_number=1)
            pkg = generator.generate_post_package(concept=concept, outline=outline, characters=chars)

            print(f"=== Original Anime Concept: {concept.title} ===")
            print(f"Genre: {concept.genre}")
            print(f"Synopsis: {concept.synopsis}")
            print(f"Setting: {concept.setting}")
            print(f"Target Audience: {concept.target_audience}")
            print("\n--- Key Characters ---")
            for c in chars:
                print(f"* {c['name']} ({c['role']}): {c['personality']}")
                print(f"  Appearance: {c['appearance']}")
                print(f"  Motivation: {c['motivation']}")
            print(f"\n--- Episode 1 Outline: {outline.episode_title} ---")
            for s in outline.scenes:
                print(f"Scene {s.scene_number} [{s.location}]: {s.summary}")
            print(f"Cliffhanger: {outline.cliffhanger}")
            print(f"\nCaption:\n{pkg['caption'][:200]}...")
            return 0

        scheduler = Scheduler()
        if command == "daily":
            result = scheduler.run_daily()
            _print_daily_results(result)
        elif command == "analytics":
            result = scheduler.run_analytics()
            _print_analytics(result)
        elif command == "scientist":
            result = scheduler.run_scientist()
            _print_scientist(result)
        elif command == "monthly":
            result = scheduler.run_monthly()
            _print_monthly(result)
    except Exception as exc:
        print(f"Command '{command}' failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
