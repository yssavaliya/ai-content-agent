# ai-content-agent

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
- `IMAGE_PROVIDER` — `auto` (default in the workflows), `cloudflare`, `pollinations`/`flux`, `pillow`, `openai`, `local` or `mock`; `IMAGE_CHAIN`, `CLOUDFLARE_IMAGE_MODEL`, `BUFFER_QUEUE_LIMIT` — see "Images and the Buffer queue"
- `OPENAI_API_KEY` — optional; required only when `IMAGE_PROVIDER=openai`
- `OPENAI_MODEL`, `OPENAI_MAX_RETRIES`, `OPENAI_REQUEST_TIMEOUT_SECONDS` — OpenAI provider tuning
- `INSTAGRAM_ACCESS_TOKEN` / `INSTAGRAM_ACCOUNT_ID` — Instagram Business account credentials
- `INSTAGRAM_API_VERSION` — Graph API version (default `21.0`)
- `INSTAGRAM_PUBLISH_ENABLED` — set `true` to publish for real; otherwise publishing falls back to dry-run
- `HUMAN_APPROVAL_REQUIRED` — defaults to `false` for unattended publishing; set `true` only to force post-kit review instead of live Instagram/Buffer publishing
- `INSTAGRAM_ANALYTICS_ENABLED` — set `true` to collect insights
- `ANALYTICS_MAX_AGE_DAYS` — only posts newer than this are re-measured each run (default 30)
- `BUFFER_ACCESS_TOKEN` / `BUFFER_PROFILE_ID` — optional Buffer publishing and analytics (see costs table)
- `BUFFER_SCHEDULE_TIME_UTC` — optional `HH:MM` (UTC). Without it Buffer posts are shared immediately when the job ends (GitHub cron jobs are often delayed by hours, so that can be the middle of the night in India); with it they are scheduled for the next occurrence of that time (`12:30` = 6 PM IST). Uses Buffer's `customScheduled` mode and falls back to the queue; not yet verified against a live Buffer account.
- `GROWTH_START_DATE`, `GROWTH_BASE_TARGET`, `GROWTH_MULTIPLIER`, `GROWTH_PERIOD_DAYS` — follower milestone plan (defaults: first snapshot date, 1000, 2.5, 90)
- `DUPLICATE_SIMILARITY_THRESHOLD` — similarity (0-1) at which a caption counts as a repeat (default 0.85)
- `LLM_COST_PER_1K_TOKENS` — optional cost estimate for paid LLM providers (default 0 = untracked)
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

## Images and the Buffer queue

**Image quality.** `IMAGE_PROVIDER=auto` (the workflow default) tries `IMAGE_CHAIN` in order and keeps the first real image:
1. **Cloudflare FLUX.1 [schnell]**, 1024 px, no watermark, using the same free Cloudflare credentials as the LLM chain. Request and response follow Cloudflare's model page; it has not been run against a live account here, and Cloudflare's pricing for it was not on the page I could read, so watch your neuron usage in the Cloudflare dashboard.
2. **Pollinations FLUX**, keyless. Measured: it returns **768x768** (not the 1080 requested), stamps a **"pollinations.ai" logo** in the corner despite `nologo=true`, and allows one image per 45 s per IP. Bytes that are not a decodable image are rejected.
3. **Offline Pillow poster.** It cannot fail. It now draws the post's own opening line (it used to print one fixed quote, cut mid-sentence, on every post) and ends a too-long line with an ellipsis.

**Buffer queue.** With Buffer, every run first reads the channel's posts (read-only). If `BUFFER_QUEUE_LIMIT` (default 10, Buffer's free-plan limit) scheduled posts are already waiting it stops before any LLM or image call and alerts you, and the captions Buffer already holds are added to the duplicate check, which also covers the other instance and any other automation posting to the same channel. If Buffer refuses a post anyway, the run saves a post kit, records `blocked_publish` and exits non-zero. `ai-content-agent buffer-status` (or the **Buffer queue status** workflow) lists what Buffer holds.

**Review revisions.** A draft the reviewer rejects is no longer simply discarded: the creator is asked again with the reviewer's objections in the prompt, up to `MAX_REVIEW_REVISIONS` times (default 2). Every draft and verdict is kept in the database; if the last draft still fails, or the model can only repeat the rejected one, the post is blocked as before. A real run showed why: the first draft was generic ("What fuels your inner strength?"), and the reviewer was right to reject it.

## LLM providers: free tiers, fallback and caching

Nothing here needs a GPU, a local model or a paid API, and nothing is installed in GitHub Actions beyond Python packages. Every agent calls one function; behind it `LLM_CHAIN` (see `.env.example`) lists providers in order. For each call the chain skips providers without credentials, tries the next one on any failure, and only if all of them fail does the pipeline use the offline template generator, so a provider outage can never stop the daily run.

**What each provider actually is** (checked 1 Nov 2026 against the provider's own documentation unless marked; free tiers change, so re-check before relying on a number):

| Provider | Free access | Open source? | What I verified |
| --- | --- | --- | --- |
| **Groq** | Free plan, API key | No: proprietary service running open-weight models | Per-account limits shown only in the console. Third-party pages agree on about 30 requests/min and 1,000/day for the 70B Llama model; **not confirmed from Groq's own docs**. |
| **Cloudflare Workers AI** | 10,000 neurons/day on the free Workers plan; above that requests fail until 00:00 UTC | No (open-weight models) | Official pricing page. Has an OpenAI-compatible endpoint (`.../accounts/{id}/ai/v1/chat/completions`). |
| **OpenRouter** `:free` models | Yes: 20 requests/min, 50/day (1,000/day after buying $10 of credits) | No (aggregator; free model list changes) | Official limits page. |
| **Gemini API** | Free tier in AI Studio | No: proprietary model | Limits are per account in AI Studio and not published on the page I could read. Terms: on the free tier Google may use prompts and outputs to improve its products; in the EEA, UK and Switzerland only paid services may be used to serve users. |
| **Pollinations text** | Keyless legacy endpoint worked in my tests | Model is open-weight (GPT-OSS-20B); the service is not | **1 reply per 45 s per IP** (HTTP 402 `FREE_LIMIT`), answers identical requests from a shared cache, 30-50 s per answer, no stated terms. Newer docs say a key is required, so this endpoint may go away. Use as a last resort only. |
| **opencode CLI** | Free gateway model | CLI is open source; the model is third-party | Flaky in practice ("Unexpected server error" in CI on 30 Oct). Last resort. |

**Default order.** The workflows use `cloudflare,groq,gemini,openrouter,pollinations` (override with an `LLM_CHAIN` secret or repository variable). Cloudflare is first because it answered 13 of 13 recorded calls in about 9 s, while Pollinations averaged 39 s with many failures and Gemini mostly failed on this account. `opencode` is no longer in the default order (it failed every call it received); add it to `LLM_CHAIN` to bring it back.

**Caption quality gate.** After the model reviewer, `growth/quality.py` runs deterministic checks (famous-quote reproduction, over-long hook, hashtag stuffing, too many emojis). A model PASS cannot override them: the draft goes back to the creator with the reasons, like any other rejection. The quote list is a small curated guard, not a complete one; the creator prompt also asks for original wording and, in the Hinglish instance, for natural everyday Hindi only.
| *GitHub Models* | **Retired on 30 Jul 2026**: do not use | | GitHub's own notice. |
| *Hugging Face Inference Providers* | **Not free**: free accounts get no included credits | | Official pricing page. |
| *Cerebras* | Needs a verified payment method for the trial credits | No | Official limits page (5 requests/min per model). Left out of the default chain. |
| *Mistral* | Free "Experiment" tier reported | Some models open-weight | Could not load Mistral's own limits page; third-party numbers conflict. Not wired in. |

"Free" is not "open source": the services above are hosted products. The weights behind most of them are open (Llama, GPT-OSS, Qwen); the APIs, limits and uptime are not.

At about 5 LLM calls per instance per day, every free tier above is far below its limit. What fails in practice is availability and output quality, not quota, so batching calls would save nothing. The chain does these instead:

- **Health tracking.** A provider answering 401/403, 400/404 or "quota exhausted" is skipped for the rest of the run; two failed calls in a row cool it down for 5 minutes; a provider whose last 3+ calls in 48 h all failed is moved to the back of the order.
- **Retries and timeouts.** Timeouts, 5xx and rate limits are retried with backoff (honouring `Retry-After`, up to 60 s); each provider has a request timeout (120 s for the slow keyless one), and one call never exceeds `LLM_CALL_BUDGET_SECONDS` across all providers.
- **Output validation.** An answer that is not a JSON object, or was cut off (`finish_reason=length`), counts as a failure of that provider and the next one is tried. `max_tokens` (default 8192) is always sent because a provider default of 1,500 truncated reasoning-model answers, and even 4096 was not enough for the research prompt on the keyless GPT-OSS model.
- **Cache.** Validated answers are cached on disk by prompt for `LLM_CACHE_TTL_HOURS`, and the workflows persist the folder with `actions/cache`, so re-running a failed job does not spend quota again. A cached answer is never served twice to a caller that rejected it.
- **Offline templates.** `fallback/templates.py` writes a different on-brand post per day and per retry (thousands of combinations, no numbers or claims), and the duplicate guard asks for another variant when one was already used.
- **Reasoning effort.** The keyless GPT-OSS model is sent `reasoning_effort: low`: with its default effort a 9 KB prompt used more than 8,192 tokens thinking and returned HTTP 400, while `low` answered in about 20 s with a few hundred tokens.
- **Short limits are waited out.** A 429/402 that names a wait of 60 s or less (`Retry-After`, "retry in 25s", `retryDelay`) is a per-minute limit even when the text says "quota"; longer ones disable the provider for the run.
- **Image retries.** The Pollinations image provider waits out a 402/429/5xx (honouring "Retry after 10s", capped at 30 s) up to 3 times before using the offline Pillow poster; a busy second used to cost the artwork.
- **Visibility.** Every call is recorded in `api_usage`; a run that used templates says so in its notification.

**Setup (all free).** Add any of these as repository secrets (Settings -> Secrets and variables -> Actions); none is required:
`GROQ_API_KEY`, `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`. Optional: `GROQ_MODEL`, `CLOUDFLARE_MODEL`, `OPENROUTER_MODEL`, `LLM_CHAIN` (secret or repository variable). Model ids change; `llm-check` reports a model that has been retired.

**Testing it on GitHub Actions.** Run the **LLM provider check** workflow (Actions -> LLM provider check -> Run workflow). It pings each provider once and writes a status table to the job summary; it fails only if none answers. It also runs every Monday. Locally: `LLM_CHAIN=groq,pollinations ai-content-agent llm-check`.

## Growth engine

The pipeline is built to grow `@aimagix.studio` with real followers only: it uses official APIs, never buys or fakes engagement, and never scrapes. Everything below is implemented and covered by tests; what needs your accounts is called out explicitly.

**Milestones.** Targets are 1,000 followers, then 2.5x the previous target for every further 90 days (1,000 / 2,500 / 6,250 / 15,625 ...). Each target is due `90 x (n + 1)` days after the start date. `ai-content-agent milestone` shows progress, the pace needed per day, the pace of the last 7 days and whether that pace reaches the target (`on_track`, `at_risk`, `behind`, `overdue`).

**Follower tracking.** `ai-content-agent followers` stores today's count in `follower_snapshots`. Source: the official Instagram Graph API (`followers_count`), which needs an Instagram **Business or Creator** account linked to a Facebook Page plus `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_ACCOUNT_ID`. Without those, record the number yourself (for example from the app) with `ai-content-agent followers 412`. Buffer's API has no follower-count endpoint that this project uses.

**Dashboard.** `ai-content-agent dashboard [path]` writes one self-contained HTML file (no CDN, no JavaScript) from the agent's own database: followers and daily/weekly gain, milestone progress, reach, impressions, engagement rate, saves/shares/comments, best and weakest posts, experiment results, recent run health and API usage. The analytics workflows rebuild it daily and commit `dashboard/index.html`; turn on GitHub Pages for that folder, or just open the file.

**It learns from results.**
- The daily run first refreshes metrics for recent posts, then the Scientist analyses the active experiment.
- The creator prompt receives the best and weakest recent posts, so it repeats what worked and avoids what failed.
- The active experiment (default: curiosity-question hook vs declarative hook) assigns each post an arm *before* it is written and tells the creator which hook style to use, so the two arms really differ. The Scientist only changes `brain/strategy.md` when sample size, effect size and confidence gates are all met.

**Originality.** A caption at least `DUPLICATE_SIMILARITY_THRESHOLD` similar to any earlier one is regenerated once with the old caption listed as off-limits. If it is still a near-copy, or the LLM is down and only the fixed template is available, the post is **blocked** (`blocked_duplicate`) and you are notified instead of posting repetitive content.

**Monitoring and cost.** Every LLM, image and publish call is recorded in `api_usage` (provider, success, tokens, duration). Cost is only estimated for paid providers when `LLM_COST_PER_1K_TOKENS` is set. `ai-content-agent health` (run by the analytics workflows) notifies your channels when: no post was recorded for 3 days, the last runs used fallback content or were blocked, more than half of recent API calls failed, follower counts are stale, or growth is `behind`/`overdue`.

**Not automated (and why).**
- Reading competitors' accounts: Instagram's official Business Discovery endpoint needs a Business-account token (see above) and is not implemented yet; scraping is out of bounds.
- Reels or video: the pipeline publishes single images; there are no retention metrics for them.
- Followers and viral reach are outcomes of content quality and time. Nothing here can guarantee 1,000 followers in 2-3 months; the milestone report tells you honestly whether the measured pace gets there.

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
ai-content-agent followers [N]  # record follower count (API, or the number N)
ai-content-agent milestone   # progress toward the active follower target
ai-content-agent dashboard [path]  # static HTML dashboard
ai-content-agent health      # alert channels if something needs a human
ai-content-agent llm-check   # ping every provider in LLM_CHAIN
```

## Automation

`.github/workflows/` contains:

- `ci.yml` — lint + tests on push/PR.
- `manual.yml` — on-demand run (`workflow_dispatch`) with selectable image provider and notification channels.
- `daily.yml` — runs the daily pipeline (cron `0 6 * * *`), persists `agent.db`, `brain/strategy.md`, and generated assets back to the repo.
- `analytics.yml` — collects insights (cron `0 14 * * *`).
- `weekly.yml` — runs the Scientist learning loop (cron `30 6 * * 0`).
- `monthly.yml` — sends the monthly digest (cron `0 7 1 * *`).
- `record-followers.yml` — manual: enter the follower count you see on Instagram (and pick the instance); it is stored, the dashboard is rebuilt and both are committed. Use it until the Instagram Graph API token is set.

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
