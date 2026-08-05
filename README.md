# ai-content-agent

A small autonomous AI Content Agent skeleton for Phase X / Checkpoint Y.

## What is included

- clean architecture separation between domain, application, and infrastructure
- domain models and interface ports for trend discovery, content generation, publishing, and analytics
- dummy infrastructure implementations for a runnable checkpoint
- CLI entrypoint for one agent checkpoint cycle

## Database

This project uses SQLite for the database layer.

### Initialize the database

```bash
cd /workspaces/ai-content-agent
PYTHONPATH=src python3 -c "from ai_content_agent.database.connection import initialize_database; initialize_database('agent.db')"
```

### Run migrations

At this checkpoint, migrations are defined in `src/ai_content_agent/database/connection.py` and can be executed with:

```bash
PYTHONPATH=src python3 -c "from ai_content_agent.database.connection import run_migrations; run_migrations('agent.db')"
```

### Database tables

- `posts`
- `analytics`
- `experiments`

## Configuration

This project uses environment variables for configuration. Copy `.env.example` to `.env` and update the values before running.

Supported variables:

- `LOG_LEVEL` — application log level, e.g. `DEBUG`, `INFO`, `WARNING`, `ERROR`
- `DATABASE_PATH` — SQLite database file path
- `OPENCODE_COMMAND` — command used for OpenCode execution if applicable
- `INSTAGRAM_ENABLED` — `true`/`false` flag to enable Instagram behavior
- `IMAGE_PROVIDER` — provider identifier for image generation or assets

## Agent framework

The agent framework is implemented under `src/ai_content_agent/agents`.

Implemented placeholder agents:

- `ResearchAgent`
- `PlannerAgent`
- `CreatorAgent`
- `ReviewerAgent`

Each agent exposes:

- `name`
- `description`
- `input_schema`
- `output_schema`
- `execute()`

Agent execution currently returns placeholder outputs.

## Run locally

```bash
cd /workspaces/ai-content-agent
PYTHONPATH=src python3 -m ai_content_agent
```

Optionally install in editable mode:

```bash
cd /workspaces/ai-content-agent
python3 -m pip install -e .
ai-content-agent
```

## Tests

```bash
cd /workspaces/ai-content-agent
PYTHONPATH=src python3 -m unittest tests.test_database_connection
```

## Next checkpoint

Add real integrations for trend research, Instagram publishing, and analytics collection.
