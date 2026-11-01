from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

from ..settings import Settings
from .cache import LLMCache
from .chain import ProviderChain, demote_recently_failing
from .providers import HttpProvider, OpenCodeCliProvider, Provider, ProviderSpec

logger = logging.getLogger(__name__)

# gpt-oss-20b is a reasoning model: 30-50 s per answer was measured, so a 45 s default would cut it off.
POLLINATIONS_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    configured: bool
    model: str
    reason: str = ""


def provider_spec(name: str, settings: Settings) -> tuple[ProviderSpec | None, str]:
    """(spec, why-not) for an OpenAI-compatible provider. ``spec`` is None when it cannot be built."""
    spec, why_not = _base_spec(name, settings)
    if spec is not None:
        spec = replace(spec, max_tokens=settings.llm_max_output_tokens)
    return spec, why_not


def _base_spec(name: str, settings: Settings) -> tuple[ProviderSpec | None, str]:
    if name == "groq":
        return ProviderSpec(
            "groq", "https://api.groq.com/openai/v1/chat/completions", settings.groq_model, settings.groq_api_key
        ), "GROQ_API_KEY is not set"
    if name == "gemini":
        base = settings.gemini_base_url.rstrip("/")
        return ProviderSpec(
            "gemini", f"{base}/chat/completions", settings.gemini_model, settings.gemini_api_key
        ), "GEMINI_API_KEY is not set"
    if name == "cloudflare":
        if not settings.cloudflare_account_id:
            return None, "CLOUDFLARE_ACCOUNT_ID is not set"
        url = f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/ai/v1/chat/completions"
        return ProviderSpec("cloudflare", url, settings.cloudflare_model, settings.cloudflare_api_token), (
            "CLOUDFLARE_API_TOKEN is not set"
        )
    if name == "openrouter":
        return ProviderSpec(
            "openrouter",
            "https://openrouter.ai/api/v1/chat/completions",
            settings.openrouter_model,
            settings.openrouter_api_key,
        ), "OPENROUTER_API_KEY is not set"
    if name == "pollinations":
        # Keyless on the legacy endpoint; an optional key is sent when set.
        return ProviderSpec(
            "pollinations",
            settings.pollinations_text_url,
            settings.pollinations_text_model,
            settings.pollinations_api_key,
            requires_key=False,
            send_seed=True,
            timeout_seconds=POLLINATIONS_TIMEOUT_SECONDS,
        ), ""
    if name == "openai":
        return ProviderSpec(
            "openai", "https://api.openai.com/v1/chat/completions", settings.openai_text_model, settings.openai_api_key
        ), "OPENAI_API_KEY is not set (paid API: only use it deliberately)"
    return None, f"{name} is not an HTTP provider"


def describe_chain(settings: Settings) -> list[ProviderStatus]:
    """Every provider named in LLM_CHAIN with whether it has what it needs to run."""
    statuses = []
    for name in settings.llm_chain:
        if name == "opencode":
            statuses.append(ProviderStatus(name, True, "opencode CLI"))
            continue
        spec, why_not = provider_spec(name, settings)
        if spec is None:
            statuses.append(ProviderStatus(name, False, "-", why_not))
        elif spec.configured:
            statuses.append(ProviderStatus(name, True, spec.model))
        else:
            statuses.append(ProviderStatus(name, False, spec.model, why_not))
    return statuses


def build_providers(settings: Settings, opencode_client: Any | None = None) -> list[Provider]:
    providers: list[Provider] = []
    for name in settings.llm_chain:
        if name == "opencode":
            if opencode_client is not None:
                providers.append(OpenCodeCliProvider(opencode_client))
            continue
        spec, why_not = provider_spec(name, settings)
        if spec is None or not spec.configured:
            logger.info("LLM provider %s skipped: %s", name, why_not)
            continue
        providers.append(HttpProvider(spec))
    return providers


def build_chain(settings: Settings, opencode_client: Any | None = None) -> ProviderChain:
    providers = demote_recently_failing(build_providers(settings, opencode_client), settings.database_path)
    cache = LLMCache(settings.llm_cache_dir, settings.llm_cache_ttl_hours, settings.llm_cache_enabled)
    if cache.enabled:
        cache.purge_expired()
    return ProviderChain(
        providers,
        max_attempts=settings.llm_max_attempts,
        request_timeout=settings.llm_request_timeout_seconds,
        call_budget_seconds=settings.llm_call_budget_seconds,
        backoff_seconds=settings.llm_backoff_seconds,
        cache=cache,
    )
