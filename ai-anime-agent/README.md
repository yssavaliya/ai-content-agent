# ai-anime-agent

A parallel instance of the AI Content Agent that publishes **AI** and **anime** content to Indian Instagram. It shares the same automation, market and Instagram account as the main instance, but runs from this subfolder with its own database, brain documents, and schedule.

The topic alternates deterministically by UTC date (rule in `brain/strategy.md`): even dates produce AI content, odd dates produce anime content. The research agent receives the run date via the `$run_date` prompt variable and injects the full `brain/` documents into the prompt.

An autonomous Instagram content system. It researches a topic, plans and scores content ideas, drafts a publish-ready post, reviews it against the brand constitution, generates a lead image, publishes to Instagram, collects insights, and runs a Scientist learning loop that updates the content strategy from measured evidence.

## What is included

- Six LLM-backed agents that each shell out to the `opencode` CLI as a subprocess and validate strict JSON output:
  - `ResearchAgent` — recommends a content topic from the brand identity and strategy.
  - `PlannerAgent` — generates scored candidate ideas and selects the strongest.
  - `CreatorAgent` — turns the selected idea into a full post draft (carousel outline, caption, CTA, hashtags, image prompt, alt text).
  - `ReviewerAgent` — checks the draft for grammar, readability, tone, policy, and completeness, returning `PASS`/`FAIL`.
  - `PredictorAgent` — estimates virality from the draft, research, review and recent post performance.
  - `ScientistAgent` — analyzes experiment results and recommends strategy changes backed by statistics.
- Image providers under `src/ai_content_agent/providers/image`:
  - `local` / `mock` — write JSON metadata only; used for tests and offline development.
  - `openai` — calls the OpenAI Images API (`gpt-image-1`) and writes a real PNG.
- Publishing under `src/ai_content_agent/publish`:
  - `InstagramPublisher` — real publishing via the Instagram Graph API (container → poll → publish). Images are converted to JPEG (≤ 8 MB) and hosted on a public HTTPS URL before publishing.
  - `GitHubRawImageHost` — uploads images to a GitHub repository and returns the raw.githubusercontent.com URL.
  - `DryRunPublisher` — fallback when Instagram is not configured: simulates publishing and writes a Markdown post kit for manual posting (see below).
- Analytics under `src/ai_content_agent/analytics`:
  - `InstagramAnalyticsClient` — fetches per-post insights and account insights from the Graph API. Missing metrics are never treated as zero.
  - `AnalyticsCollector` — persists `post_metrics` and observations into SQLite.
- Notifications under `src/ai_content_agent/notifications` — dry-run, Discord, Telegram, Slack channels (any combination, configured via `NOTIFY_CHANNELS`). The notifier never raises.
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
- `LLM_PROVIDER` — `opencode` (default, free), `openai` or `gemini`
- `OPENAI_TEXT_MODEL`, `OPENAI_TEXT_FALLBACK_ENABLED`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_BASE_URL` — optional API fallbacks
- `OPENCODE_TIMEOUT_SECONDS` — per-invocation timeout for `opencode` (default 60)
- `INSTAGRAM_ENABLED` — `true`/`false`
- `IMAGE_PROVIDER` — `pollinations`/`flux`, `pillow`, `openai`, `local` or `mock`
- `OPENAI_API_KEY` — optional; required only when `IMAGE_PROVIDER=openai`
- `OPENAI_MODEL`, `OPENAI_MAX_RETRIES`, `OPENAI_REQUEST_TIMEOUT_SECONDS` — OpenAI provider tuning
- `INSTAGRAM_ACCESS_TOKEN` / `INSTAGRAM_ACCOUNT_ID` — Instagram Business account credentials
- `INSTAGRAM_API_VERSION` — Graph API version (default `21.0`)
- `INSTAGRAM_PUBLISH_ENABLED` — set `true` to publish for real; otherwise publishing falls back to dry-run
- `INSTAGRAM_ANALYTICS_ENABLED` — set `true` to collect insights
- `ANALYTICS_MAX_AGE_DAYS` — only posts newer than this are re-measured each run (default 30)
- `BUFFER_ACCESS_TOKEN` / `BUFFER_PROFILE_ID` — optional Buffer publishing and analytics (see costs table)
- `BUFFER_SCHEDULE_TIME_UTC` — optional `HH:MM` (UTC). Without it Buffer posts are shared immediately when the job ends (GitHub cron jobs are often delayed by hours, so that can be the middle of the night in India); with it they are scheduled for the next occurrence of that time (`12:30` = 6 PM IST). Uses Buffer's `customScheduled` mode and falls back to the queue; not yet verified against a live Buffer account.
- `AGENT_RETRY_BACKOFF_SECONDS` — pause between LLM retries (default 15; tests set 0)
- `MEDIA_HOST` / `MEDIA_HOST_REPO` / `MEDIA_HOST_TOKEN` / `MEDIA_HOST_BRANCH` / `MEDIA_HOST_PATH` — GitHub-raw media hosting (`MEDIA_HOST=github`); Instagram requires a public HTTPS image URL
- `NOTIFY_CHANNELS` — comma-separated list: `dryrun`, `discord`, `telegram`, `slack` (unusable/unknown values fall back to `dryrun`)
- `DISCORD_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SLACK_WEBHOOK_URL` — per-channel credentials
- `SCIENTIST_MIN_SAMPLE_SIZE` (default 10), `SCIENTIST_MIN_EFFECT` (default 0.15), `SCIENTIST_APPLY_THRESHOLD` (default 0.6), `SCIENTIST_MAX_RECOMMENDATIONS` (default 5) — evidence gates for the learning loop

## Manual publishing (replaces the old email hand-off)

When Instagram publishing is off or not configured (`INSTAGRAM_PUBLISH_ENABLED=false`), the pipeline does **not** call Instagram. The `DryRunPublisher` writes a copy-paste-ready Markdown **post kit** next to the package (`posts/post_kit_<run_id>.md`: caption, CTA, hashtags, alt text, image location, carousel outline). The kit is available in three places, none of which need email:

- In the repository, committed with the run artifacts under `posts/`.
- In the GitHub Actions **job summary** of the `daily` and `manual` workflows.
- In the success notification (full caption, hashtags and alt text) sent to the configured Discord/Telegram/Slack channel, or the log when only `dryrun` is configured.

If the ReviewerAgent returns `FAIL`, nothing is generated or published: the run is stored with publish status `blocked_review` and a failure notification lists the reviewer's reasons.

## Architecture and static hosting

This repository is a Python command-line system driven by GitHub Actions cron jobs. It has **no web frontend, no HTTP API and no user accounts**, so there is nothing to convert into a static website and no server to host. The only persistent state is a SQLite file (`agent.db`) and generated files under `posts/` and `images/`, which the workflows commit back to the repository. If you want a browsable site later, `posts/post_kit_*.md` and `posts/*.json` can be published with any static host such as GitHub Pages; that is not set up here.

Hosting requirements: a GitHub repository with Actions enabled (free for public repositories; private repositories have a monthly free-minute quota), or any machine with Python 3.11+ and Node.js (for the `opencode` CLI) running `ai-content-agent daily` from cron.

## Costs and free / open-source choices

| Component | Default | Cost / licence note |
| --- | --- | --- |
| LLM for all agents | `opencode` CLI with the model in `opencode.json` | The CLI is open source; the configured `-free` model is offered by a third party and is not guaranteed to stay free. |
| OpenAI / Gemini chat | Off unless `OPENAI_API_KEY` / `GEMINI_API_KEY` is set | Proprietary, usage-billed. Used only as an optional fallback (or when `LLM_PROVIDER` selects them). |
| Image generation | `IMAGE_PROVIDER=local` (writes the prompt only, no picture) | `openai` renders real images but is a paid API. **No free image generator is bundled**, so automatic image posts need either that paid provider or a manually created image from the post kit. |
| Image generation (free path) | `IMAGE_PROVIDER=pollinations` (alias `flux`) or `pillow` | Pollinations is a free hosted FLUX service: no key, but it is **not open source** and has no uptime guarantee, so it falls back to the offline `pillow` renderer (Pillow, HPND licence). |
| Publishing | Instagram Graph API, or Buffer when `BUFFER_ACCESS_TOKEN` + `BUFFER_PROFILE_ID` are set | The Graph API has no fee but needs a Meta app and Business account. Buffer is a proprietary service; its free plan is limited and may change. Both are optional: without either the dry-run post kit is used. |
| Media hosting | `MEDIA_HOST=github` | Uses raw.githubusercontent.com, so the image repository must be **public** for Buffer/Instagram to fetch the file. |
| Anime metadata | Kitsu API (`anime-trends`, `anime-concept` commands only) | Free, no key, third-party; a built-in sample list is used if it is unreachable. |
| Python deps | `openai`, `requests`, `Pillow` | MIT/Apache-2.0/HPND licences. |

Email/SMTP support has been removed entirely; no mail provider is required or used.

## When the LLM is unavailable

If an agent cannot get an answer from any LLM provider, the pipeline continues with fixed template output so a post is still produced. That output is never presented as model output:

- The package gets `"fallbacks": ["reviewer", ...]` and the affected sections carry `"source": "procedural_fallback"`.
- The fallback reviewer passes the template content but says so in its reasons; the fallback predictor records a neutral 50/MEDIUM placeholder rather than an invented estimate.
- The notification subject ends with `(template fallback content)` and the body names the stages, so a green run with no model behind it is visible. Check `LLM_PROVIDER`, API keys and quotas when you see it.

## Analytics and the learning loop

Every post sent through a live publisher (Instagram or Buffer, whatever status it reports such as `published`, `scheduled` or `sent`) is stored in `posts` and assigned to the active experiment. `ai-content-agent analytics` (and the start of every `daily` run) then refreshes metrics for posts from the last `ANALYTICS_MAX_AGE_DAYS` days (default 30). The Scientist only acts once each experiment arm has `SCIENTIST_MIN_SAMPLE_SIZE` measured posts.

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
- `manual.yml` — on-demand run (`workflow_dispatch`) with selectable image provider and notification channels.
- `daily.yml` — runs the daily pipeline (cron `0 6 * * *`), persists `agent.db`, `brain/strategy.md`, and generated assets back to the repo.
- `analytics.yml` — collects insights (cron `0 14 * * *`).
- `weekly.yml` — runs the Scientist learning loop (cron `30 6 * * 0`).
- `monthly.yml` — sends the monthly digest (cron `0 7 1 * *`).

All workflows share one `concurrency` group (`repo-state`) so two jobs never write `agent.db` or push at the same time. A failing pipeline step now fails the workflow (previously the pipe hid the exit code), but run artifacts are still committed.

Configure repository secrets (Settings → Secrets and variables → Actions) for every environment variable you set in `.env`. Scheduled jobs run on the default branch; commits pushed back use the built-in `GITHUB_TOKEN` with `contents: write`. Each job holds an exclusive lock file next to `agent.db` (`<db>.lock`), so overlapping scheduled runs cannot race on the shared database; stale locks are broken automatically.

## Development and verification

Run everything from the repository root of the instance you are using (`brain/` and `posts/` are resolved relative to the working directory; prompt templates ship inside the package).

```bash
pip install -e ".[dev]"
python -m ruff check .
python -m pytest -q          # fully mocked; no opencode binary, network or API key needed
python -m unittest discover -s tests
```

## Tests

```bash
pytest
# or
python -m unittest discover
```

All agent and provider tests run fully mocked — no `opencode` binary, network access, or API key is required.
