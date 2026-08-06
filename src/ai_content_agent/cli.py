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
  help        Show this help.

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
    print(f"Recommendations: {result.get('applied_count')} applied")
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


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    setup_logging()

    command = args[0] if args else "daily"
    scheduler = Scheduler()

    if command in ("help", "--help", "-h"):
        print(USAGE)
        return 0

    try:
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
        else:
            print(f"Unknown command: {command}", file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 2
    except Exception as exc:
        print(f"Command '{command}' failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
