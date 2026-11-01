from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from ..database.connection import DatabaseConnection
from ..opencode.context import get_run_id
from ..settings import current_settings
from ..timestamps import utc_now_iso

logger = logging.getLogger(__name__)

PAID_PROVIDERS = frozenset({"openai", "gemini"})


def as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def record_usage(
    service: str,
    operation: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    ok: bool = True,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    duration_ms: int | None = None,
) -> None:
    """Append one API call to ``api_usage``. Never raises: tracking must not break a run.

    The estimated cost is only non-zero for paid providers and only when LLM_COST_PER_1K_TOKENS is set,
    so with the default free setup the table records volume and failures, not money.
    """
    try:
        settings = current_settings()
        database = settings.database_path
        if database == ":memory:" or not Path(database).exists():
            return
        tokens = (input_tokens or 0) + (output_tokens or 0)
        cost = tokens / 1000 * settings.llm_cost_per_1k_tokens if provider in PAID_PROVIDERS else 0.0
        connection = sqlite3.connect(database, timeout=5)
        try:
            connection.execute(
                "INSERT INTO api_usage(created_at, service, operation, provider, model, ok, input_tokens, "
                "output_tokens, est_cost_usd, duration_ms, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    utc_now_iso(),
                    service,
                    operation,
                    provider,
                    model,
                    1 if ok else 0,
                    input_tokens,
                    output_tokens,
                    cost,
                    duration_ms,
                    get_run_id(),
                ),
            )
            connection.commit()
        finally:
            connection.close()
    except Exception as exc:  # noqa: BLE001 - usage tracking is best effort
        logger.debug("API usage not recorded: %s", exc)


def usage_summary(db: DatabaseConnection, since_iso: str) -> list[dict]:
    """Calls, failures, tokens and estimated cost per service/provider since ``since_iso``."""
    return db.fetch_all(
        "SELECT service, COALESCE(provider, '-') AS provider, COUNT(*) AS calls, "
        "SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS failures, "
        "COALESCE(SUM(input_tokens), 0) AS input_tokens, COALESCE(SUM(output_tokens), 0) AS output_tokens, "
        "ROUND(COALESCE(SUM(est_cost_usd), 0), 4) AS est_cost_usd "
        "FROM api_usage WHERE created_at >= ? GROUP BY service, provider ORDER BY calls DESC",
        (since_iso,),
    )
