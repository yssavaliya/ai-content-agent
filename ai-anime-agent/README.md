# ai-anime-agent

A parallel instance of the AI Content Agent that publishes **AI** and **anime** content to Indian Instagram. It shares the same automation, market, Instagram account, and email as the main instance, but runs from this subfolder with its own database, brain documents, and schedule.

The topic alternates deterministically by UTC date (rule in `brain/strategy.md`): even dates produce AI content, odd dates produce anime content. The research agent receives the run date via the `$run_date` prompt variable and injects the full `brain/` documents into the prompt.

An autonomous Instagram content system. It researches a topic, plans and scores content ideas, drafts a publish-ready post, reviews it against the brand constitution, generates a lead image, publishes to Instagram, collects insights, and runs a Scientist learning loop that updates the content strategy from measured evidence.

## What is included

- Five LLM-backed agents that each shell out to the `opencode` CLI as a subprocess and validate strict JSON output:
  - `ResearchAgent` — recommends a content topic from the brand identity and strategy.
  - `PlannerAgent` — generates scored candidate ideas and selects the strongest.
  - `CreatorAgent` — turns the selected idea into a full post draft (carousel outline, caption, CTA, hashtags, image prompt, alt text).
  - `ReviewerAgent` — checks the draft for grammar, readability, tone, policy, and completeness, returning `PASS`/`FAIL`.
  - `ScientistAgent` — analyzes experiment results and recommends strategy changes backed by statistics.
- Image providers under `src/ai_content_agent/providers/image`:
  - `local` / `mock` — write JSON metadata only; used for tests and offline development.
  - `openai` — calls the OpenAI Images API (`gpt-image-1`) and writes a real PNG.
- Publishing under `src/ai_content_agent/publish`:
  - `InstagramPublisher` — real publishing via the Instagram Graph API (container → poll → publish). Images are converted to JPEG (≤ 8 MB) and hosted on a public HTTPS URL before publishing.
  - `GitHubRawImageHost` — uploads images to a GitHub repository and returns the raw.githubusercontent.com URL.
  - `DryRunPublisher` — fallback that simulates publishing when Instagram is not configured.
- Analytics under `src/ai_content_agent/analytics`:
  - `InstagramAnalyticsClient` — fetches per-post insights and account insights from the Graph API. Missing metrics are never treated as zero.
  - `AnalyticsCollector` — persists `post_metrics` and observations into SQLite.
- Notifications under `src/ai_content_agent/notifications` — dry-run, Discord, Telegram, Slack, and Email channels (any combination, configured via `NOTIFY_CHANNELS`). The notifier never raises.
- A `Scheduler` and CLI (`daily`, `analytics`, `scientist`, `monthly`) plus GitHub Actions workflows that run everything on a schedule.
- A `ContentPipeline` that orchestrates research → planning → creation → review → image → publish and persists each step to SQLite.

## Prerequisites

- Python 3.11+
- The `opencode` CLI installed and authenticated on the machine that runs the pipeline. All agents invoke it as a subprocess, so it must be available at `OPENCODE_COMMAND` (default `opencode`). Install with `npm install -g opencode-ai`.
- `OPENAI_API_KEY` only if you use `IMAGE_PROVIDER=openai`. The `local` and `mock` image providers do not need it.
- Real publishing/analytics requires Instagram Business API access (see below).

## Install

```bash
pip install -e .
# with dev/test dependencies
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and update values before running.

## Configuration

Supported environment variables (see `.env.example`):

- `LOG_LEVEL` — application log level, e.g. `DEBUG`, `INFO`, `WARNING`, `ERROR`
- `DATABASE_PATH` — SQLite database file path
- `OPENCODE_COMMAND` — command used to invoke the `opencode` CLI
- `OPENCODE_TIMEOUT_SECONDS` — per-invocation timeout for `opencode` (default 60)
- `INSTAGRAM_ENABLED` — `true`/`false`
- `IMAGE_PROVIDER` — `local`, `mock`, or `openai`
- `OPENAI_API_KEY` — optional; required only when `IMAGE_PROVIDER=openai`
- `OPENAI_MODEL`, `OPENAI_MAX_RETRIES`, `OPENAI_REQUEST_TIMEOUT_SECONDS` — OpenAI provider tuning
- `INSTAGRAM_ACCESS_TOKEN` / `INSTAGRAM_ACCOUNT_ID` — Instagram Business account credentials
- `INSTAGRAM_API_VERSION` — Graph API version (default `21.0`)
- `INSTAGRAM_PUBLISH_ENABLED` — set `true` to publish for real; otherwise publishing falls back to dry-run
- `INSTAGRAM_ANALYTICS_ENABLED` — set `true` to collect insights
- `MEDIA_HOST` / `MEDIA_HOST_REPO` / `MEDIA_HOST_TOKEN` / `MEDIA_HOST_BRANCH` / `MEDIA_HOST_PATH` — GitHub-raw media hosting (`MEDIA_HOST=github`); Instagram requires a public HTTPS image URL
- `NOTIFY_CHANNELS` — comma-separated list: `dryrun`, `discord`, `telegram`, `slack`, `email`
- `DISCORD_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SLACK_WEBHOOK_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TO`, `NOTIFY_SMTP_TLS` — per-channel credentials
- `SCIENTIST_MIN_SAMPLE_SIZE` (default 10), `SCIENTIST_MIN_EFFECT` (default 0.15), `SCIENTIST_APPLY_THRESHOLD` (default 0.6), `SCIENTIST_MAX_RECOMMENDATIONS` (default 5) — evidence gates for the learning loop

## Instagram setup

Real publishing and analytics require a Meta App linked to an Instagram Business account:

1. Create an Instagram Business account and connect it to a Facebook Page.
2. Create a Meta app at https://developers.facebook.com and add the Instagram product.
3. Generate a long-lived user access token with `instagram_business_content_publish` (publishing) and `instagram_business_manage_insights` (analytics).
4. Find your Instagram Business account id via the Graph API (`/<facebook-page-id>?fields=instagram_business_account`).
5. Apply for **Meta App Review** — the permissions are needed for the token to work on live accounts. Development-mode tokens only work for users who have the app role.
6. Set `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_ACCOUNT_ID`, `INSTAGRAM_PUBLISH_ENABLED=true`, and `INSTAGRAM_ANALYTICS_ENABLED=true`.

Published images must be JPEG and ≤ 8 MB and be reachable at a public HTTPS URL — this is why the pipeline converts images and uploads them to a GitHub repo (`MEDIA_HOST=github`, `MEDIA_HOST_REPO=owner/repo`, `MEDIA_HOST_TOKEN` = a fine-grained PAT with `Contents: Read and write`).

## Database

The project uses SQLite.

### Initialize the database

```bash
PYTHONPATH=src python -c "from ai_content_agent.database.connection import initialize_database; initialize_database('agent.db')"
```

### Run migrations

Migrations are defined in `src/ai_content_agent/database/connection.py` and run with:

```bash
PYTHONPATH=src python -c "from ai_content_agent.database.connection import run_migrations; run_migrations('agent.db')"
```

### Database tables

- `research_raw` — research agent output (one row per run)
- `planner_ideas` — scored candidate ideas and the selected idea
- `creator_outputs` — the generated post draft
- `review_history` — review verdict, feedback, and timestamp
- `image_assets` — generated image metadata and file path
- `publish_packages` — publish results (dry-run or real)
- `posts` — published posts linked to external media ids
- `post_metrics` — collected Instagram insights per post
- `observations` — metric observations feeding the Scientist
- `experiments` / `experiment_posts` — A/B experiments and per-post arm assignment
- `strategy_history` — every change applied to `brain/strategy.md`
- `schema_migrations` — schema version tracking

## Run locally

```bash
PYTHONPATH=src python -m ai_content_agent
```

This runs the full pipeline end to end. Inspect the results:

- `posts/publish_package_<timestamp>.json` — the full package with `research`, `planning`, `creation`, `review`, `image`, and `publish` sections.
- `images/YYYY/MM/DD/` — the generated image (a `.png` when `IMAGE_PROVIDER=openai`, otherwise a JSON metadata file).
- The SQLite database rows in `research_raw`, `planner_ideas`, `creator_outputs`, `review_history`, `image_assets`, and `publish_packages`, linked by foreign keys.

The CLI exposes the scheduled jobs directly:

```bash
ai-content-agent daily       # full pipeline (default)
ai-content-agent analytics   # collect Instagram insights
ai-content-agent scientist   # experiments + strategy updates
ai-content-agent monthly     # monthly digest
```

## Automation

`.github/workflows/` contains:

- `ci.yml` — lint + tests on push/PR.
- `daily.yml` — runs the daily pipeline (cron `0 6 * * *`), persists `agent.db`, `brain/strategy.md`, and generated assets back to the repo.
- `analytics.yml` — collects insights (cron `0 14 * * *`).
- `weekly.yml` — runs the Scientist learning loop (cron `30 6 * * 0`).
- `monthly.yml` — sends the monthly digest (cron `0 7 1 * *`).

Configure repository secrets (Settings → Secrets and variables → Actions) for every environment variable you set in `.env`. Scheduled jobs run on the default branch; commits pushed back use the built-in `GITHUB_TOKEN` with `contents: write`. Each job holds an exclusive lock file next to `agent.db` (`<db>.lock`), so overlapping scheduled runs cannot race on the shared database; stale locks are broken automatically.

## Tests

```bash
pytest
# or
python -m unittest discover
```

All agent and provider tests run fully mocked — no `opencode` binary, network access, or API key is required.
