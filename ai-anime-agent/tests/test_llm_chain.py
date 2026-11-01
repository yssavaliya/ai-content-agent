import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from ai_content_agent.cli import main
from ai_content_agent.database.connection import initialize_database
from ai_content_agent.llm.cache import LLMCache, prompt_key
from ai_content_agent.llm.chain import ProviderChain, ProviderHealth, demote_recently_failing, reset_health
from ai_content_agent.llm.check import check_provider, render_markdown, render_text, run_check
from ai_content_agent.llm.errors import (
    AUTH,
    BAD_OUTPUT,
    BAD_REQUEST,
    JSON_MODE,
    QUOTA,
    RATE_LIMIT,
    TRANSIENT,
    AllProvidersFailed,
    ProviderError,
)
from ai_content_agent.llm.providers import Completion, HttpProvider, ProviderSpec
from ai_content_agent.llm.registry import build_providers, describe_chain
from ai_content_agent.opencode.client import OpenCodeClient, OpenCodeError, OpenCodeResult
from ai_content_agent.opencode.recorder import PromptRecorder
from ai_content_agent.settings import load_settings

GOOD = '{"ok": true}'


def settings_for(**extra):
    env = {
        "LOG_LEVEL": "INFO",
        "DATABASE_PATH": ":memory:",
        "OPENCODE_COMMAND": "opencode",
        "INSTAGRAM_ENABLED": "false",
        "IMAGE_PROVIDER": "local",
    }
    env.update(extra)
    return load_settings(env=env, env_file=Path("none.env"))


class Scripted:
    """Provider double: each call pops the next scripted outcome (text or ProviderError)."""

    supports_json_mode = True
    records_own_usage = False

    def __init__(self, name, *outcomes):
        self.name = name
        self.outcomes = list(outcomes)
        self.calls = []

    def complete(self, prompt, json_mode, timeout):
        self.calls.append(json_mode)
        outcome = self.outcomes.pop(0) if self.outcomes else GOOD
        if isinstance(outcome, Exception):
            raise outcome
        return Completion(outcome, model=f"{self.name}-model", input_tokens=3, output_tokens=2)


def response(status=200, body=None, text=None, headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {}
    resp.text = text if text is not None else json.dumps(body or {})
    if body is not None:
        resp.json.return_value = body
    else:
        resp.json.side_effect = ValueError("not json")
    return resp


def ok_body(content=GOOD, **extra):
    return {"choices": [{"message": {"content": content}}], "model": "m-1", "usage": {"prompt_tokens": 11, "completion_tokens": 7}, **extra}


class HttpProviderTests(unittest.TestCase):
    def make(self, key="sekret", requires_key=True):
        spec = ProviderSpec("p", "https://api.example/v1/chat/completions", "m", key, requires_key=requires_key)
        session = MagicMock()
        return HttpProvider(spec, session=session), session

    def test_success_sends_auth_and_json_mode_and_parses_usage(self):
        provider, session = self.make()
        session.post.return_value = response(body=ok_body("<think>hmm</think>" + GOOD))
        result = provider.complete("hello", True, 20)
        self.assertEqual((result.text, result.model, result.input_tokens, result.output_tokens), (GOOD, "m-1", 11, 7))
        kwargs = session.post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sekret")
        self.assertEqual(kwargs["json"]["response_format"], {"type": "json_object"})
        self.assertEqual(kwargs["json"]["messages"][0]["content"], "hello")

    def test_keyless_provider_sends_no_authorization_and_json_mode_can_be_off(self):
        provider, session = self.make(key=None, requires_key=False)
        session.post.return_value = response(body=ok_body())
        provider.complete("x", False, 20)
        kwargs = session.post.call_args.kwargs
        self.assertNotIn("Authorization", kwargs["headers"])
        self.assertNotIn("response_format", kwargs["json"])

    def test_http_errors_are_classified(self):
        cases = [
            (401, "bad key", {}, AUTH),
            (403, "forbidden", {}, AUTH),
            (404, "model not found", {}, BAD_REQUEST),
            (400, "invalid request", {}, BAD_REQUEST),
            (400, "unsupported parameter: response_format", {}, JSON_MODE),
            (429, "slow down", {"Retry-After": "5"}, RATE_LIMIT),
            (429, "You exceeded your daily quota", {}, QUOTA),
            (429, "busy", {"Retry-After": "600"}, QUOTA),
            (402, '{"error":{"code":"FREE_LIMIT","message":"Free limit reached: 1 reply every 45 seconds per IP. Retry after 16s"}}', {}, RATE_LIMIT),
            (402, "payment required", {}, QUOTA),
            (429, "You exceeded your current quota. Please retry in 25.5s.", {}, RATE_LIMIT),
            (429, 'You exceeded your current quota {"retryDelay": "30s"}', {}, RATE_LIMIT),
            (429, 'You exceeded your current quota {"retryDelay": "3600s"}', {}, QUOTA),
            (400, "The model exhausted its output token limit before producing an answer.", {}, BAD_OUTPUT),
            (500, "oops", {}, TRANSIENT),
            (503, "overloaded", {}, TRANSIENT),
        ]
        for status, text, headers, kind in cases:
            with self.subTest(status=status, text=text):
                provider, session = self.make()
                session.post.return_value = response(status=status, text=text, headers=headers)
                with self.assertRaises(ProviderError) as ctx:
                    provider.complete("x", True, 20)
                self.assertEqual(ctx.exception.kind, kind)

    def test_retry_hint_in_the_body_is_parsed_when_there_is_no_header(self):
        provider, session = self.make()
        session.post.return_value = response(status=402, text="Free limit reached. Retry after 16s, or get a key")
        with self.assertRaises(ProviderError) as ctx:
            provider.complete("x", True, 20)
        self.assertEqual((ctx.exception.kind, ctx.exception.retry_after), (RATE_LIMIT, 16.0))

    def test_truncated_answers_are_reported_as_such(self):
        provider, session = self.make()
        body = {"choices": [{"message": {"content": '{"a": "cut'}, "finish_reason": "length"}]}
        session.post.return_value = response(body=body)
        with self.assertRaises(ProviderError) as ctx:
            provider.complete("x", True, 20)
        self.assertEqual(ctx.exception.kind, BAD_OUTPUT)
        self.assertIn("truncated", str(ctx.exception))

    def test_max_tokens_is_always_sent_and_seed_only_when_asked(self):
        provider, session = self.make()
        session.post.return_value = response(body=ok_body())
        provider.complete("x", False, 20)
        self.assertEqual(session.post.call_args.kwargs["json"]["max_tokens"], 8192)
        self.assertNotIn("seed", session.post.call_args.kwargs["json"])
        seeded = HttpProvider(ProviderSpec("s", "https://x", "m", None, requires_key=False, send_seed=True), session=session)
        seeded.complete("x", False, 20)
        self.assertIsInstance(session.post.call_args.kwargs["json"]["seed"], int)

    def test_extra_body_is_merged_into_every_request(self):
        spec = ProviderSpec("p", "https://x", "m", None, requires_key=False, extra_body={"reasoning_effort": "low"})
        session = MagicMock()
        session.post.return_value = response(body=ok_body())
        HttpProvider(spec, session=session).complete("x", False, 20)
        self.assertEqual(session.post.call_args.kwargs["json"]["reasoning_effort"], "low")

    def test_retry_after_is_parsed(self):
        provider, session = self.make()
        session.post.return_value = response(status=429, text="busy", headers={"Retry-After": "7"})
        with self.assertRaises(ProviderError) as ctx:
            provider.complete("x", True, 20)
        self.assertEqual(ctx.exception.retry_after, 7.0)

    def test_timeout_and_network_errors_are_transient_and_never_leak_the_key(self):
        provider, session = self.make()
        session.post.side_effect = requests.Timeout("slow")
        with self.assertRaises(ProviderError) as ctx:
            provider.complete("x", True, 20)
        self.assertEqual(ctx.exception.kind, TRANSIENT)
        session.post.side_effect = requests.ConnectionError("failed calling https://x?key=sekret")
        with self.assertRaises(ProviderError) as ctx:
            provider.complete("x", True, 20)
        self.assertEqual(ctx.exception.kind, TRANSIENT)
        self.assertNotIn("sekret", str(ctx.exception))

    def test_empty_or_malformed_answers_are_bad_output(self):
        for body in ({"choices": [{"message": {"content": "  "}}]}, {"choices": []}, {"unexpected": 1}):
            with self.subTest(body=body):
                provider, session = self.make()
                session.post.return_value = response(body=body)
                with self.assertRaises(ProviderError) as ctx:
                    provider.complete("x", True, 20)
                self.assertEqual(ctx.exception.kind, BAD_OUTPUT)


class ChainTests(unittest.TestCase):
    def chain(self, *providers, **kwargs):
        self.sleeps = []
        kwargs.setdefault("health", ProviderHealth())
        kwargs.setdefault("sleep", self.sleeps.append)
        kwargs.setdefault("jitter", lambda: 0.5)
        return ProviderChain(list(providers), **kwargs)

    def test_first_working_provider_answers_and_others_are_untouched(self):
        a, b = Scripted("a"), Scripted("b")
        with patch("ai_content_agent.llm.chain.record_usage") as usage:
            result = self.chain(a, b).complete("p")
        self.assertEqual((result.provider, result.text, len(b.calls)), ("a", GOOD, 0))
        self.assertEqual(usage.call_args.kwargs["provider"], "a")
        self.assertTrue(usage.call_args.kwargs["ok"])

    def test_transient_failures_retry_then_fall_through_to_the_next_provider(self):
        a = Scripted("a", ProviderError(TRANSIENT, "503"), ProviderError(TRANSIENT, "503"))
        b = Scripted("b")
        result = self.chain(a, b, max_attempts=2).complete("p")
        self.assertEqual(result.provider, "b")
        self.assertEqual(len(a.calls), 2)
        self.assertEqual(len(self.sleeps), 1)  # one backoff between the two attempts
        self.assertEqual([x.provider for x in result.attempts], ["a", "a"])

    def test_a_retry_can_succeed_and_honours_retry_after(self):
        a = Scripted("a", ProviderError(RATE_LIMIT, "429", retry_after=4.0))
        result = self.chain(a).complete("p")
        self.assertEqual((result.provider, len(a.calls)), ("a", 2))
        self.assertEqual(self.sleeps, [4.0])

    def test_retry_after_is_capped(self):
        a = Scripted("a", ProviderError(RATE_LIMIT, "429", retry_after=900.0))
        self.chain(a).complete("p")
        self.assertEqual(self.sleeps, [60.0])

    def test_auth_bad_request_and_quota_disable_the_provider_for_later_calls(self):
        for kind in (AUTH, BAD_REQUEST, QUOTA):
            with self.subTest(kind=kind):
                a = Scripted("a", ProviderError(kind, "nope"))
                b = Scripted("b")
                chain = self.chain(a, b)
                self.assertEqual(chain.complete("one").provider, "b")
                self.assertEqual(chain.complete("two").provider, "b")
                self.assertEqual(len(a.calls), 1)  # never retried, never asked again
                self.assertEqual(len(self.sleeps), 0)

    def test_non_json_answer_moves_on_without_retrying_the_same_provider(self):
        a = Scripted("a", "Sure! Here you go: not json")
        b = Scripted("b")
        result = self.chain(a, b).complete("p")
        self.assertEqual((result.provider, len(a.calls)), ("b", 1))
        self.assertEqual(result.attempts[0].kind, BAD_OUTPUT)

    def test_fenced_json_is_accepted(self):
        a = Scripted("a", "```json\n" + GOOD + "\n```")
        self.assertEqual(self.chain(a).complete("p").provider, "a")

    def test_json_mode_rejection_retries_once_without_json_mode(self):
        a = Scripted("a", ProviderError(JSON_MODE, "response_format unsupported"))
        health = ProviderHealth()
        result = self.chain(a, health=health, max_attempts=1).complete("p")
        self.assertEqual((result.provider, a.calls), ("a", [True, False]))
        self.assertFalse(health.json_mode_ok("a"))
        self.chain(a, health=health).complete("another prompt")
        self.assertEqual(a.calls[-1], False)  # remembered for later calls

    def test_all_failing_raises_all_providers_failed_with_every_attempt(self):
        a = Scripted("a", ProviderError(AUTH, "bad key"))
        b = Scripted("b", ProviderError(TRANSIENT, "x"), ProviderError(TRANSIENT, "y"))
        with self.assertRaises(AllProvidersFailed) as ctx:
            self.chain(a, b).complete("p")
        self.assertEqual({x.provider for x in ctx.exception.attempts}, {"a", "b"})
        self.assertIn("All LLM providers failed", str(ctx.exception))

    def test_empty_chain_raises_all_providers_failed(self):
        with self.assertRaises(AllProvidersFailed):
            self.chain().complete("p")

    def test_a_provider_bug_is_contained(self):
        a = Scripted("a", KeyError("boom"), KeyError("boom"))
        b = Scripted("b")
        self.assertEqual(self.chain(a, b).complete("p").provider, "b")

    def test_two_failed_calls_trigger_a_cooldown_that_expires(self):
        now = [0.0]
        health = ProviderHealth(clock=lambda: now[0])
        a = Scripted("a", *[ProviderError(TRANSIENT, "x")] * 4)
        b = Scripted("b")
        chain = self.chain(a, b, health=health, clock=lambda: now[0], max_attempts=2)
        chain.complete("one")
        chain.complete("two")  # second failed call -> cooldown
        calls_before = len(a.calls)
        chain.complete("three")
        self.assertEqual(len(a.calls), calls_before)  # skipped during cooldown
        now[0] += 301
        a.outcomes = []  # healthy again
        self.assertEqual(chain.complete("four").provider, "a")

    def test_call_budget_skips_remaining_providers(self):
        now = [0.0]

        class Slow(Scripted):
            def complete(self, prompt, json_mode, timeout):
                now[0] += 200
                raise ProviderError(TRANSIENT, "slow")

        a, b = Slow("a"), Scripted("b")
        with self.assertRaises(AllProvidersFailed) as ctx:
            self.chain(a, b, clock=lambda: now[0], call_budget_seconds=150, max_attempts=1).complete("p")
        self.assertEqual(len(b.calls), 0)
        self.assertIn("budget", ctx.exception.attempts[-1].message)

    def test_usage_is_recorded_for_failures_and_not_duplicated_for_self_recording_providers(self):
        a = Scripted("a", ProviderError(AUTH, "x"))
        own = Scripted("own")
        own.records_own_usage = True
        with patch("ai_content_agent.llm.chain.record_usage") as usage:
            self.chain(a, own).complete("p")
        self.assertEqual([c.kwargs["provider"] for c in usage.call_args_list], ["a"])
        self.assertFalse(usage.call_args_list[0].kwargs["ok"])


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = [1000.0]
        self.cache = LLMCache(self.tmp.name, ttl_hours=1, clock=lambda: self.now[0])

    def tearDown(self):
        self.tmp.cleanup()

    def chain(self, *providers):
        return ProviderChain(list(providers), cache=self.cache, health=ProviderHealth(), sleep=lambda s: None)

    def test_repeat_prompt_is_served_from_cache_without_calling_a_provider(self):
        a = Scripted("a")
        chain = self.chain(a)
        first = chain.complete("same prompt")
        second = self.chain(a).complete("same prompt")  # new chain object: a re-run of the job
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual((second.text, second.provider, len(a.calls)), (GOOD, "a", 1))

    def test_a_cached_answer_is_never_served_twice_to_the_same_caller(self):
        a = Scripted("a")
        self.chain(a).complete("p")
        chain = self.chain(a)
        self.assertTrue(chain.complete("p").cached)
        retry = chain.complete("p")  # the caller asked again: it rejected the cached answer
        self.assertFalse(retry.cached)
        self.assertEqual(len(a.calls), 2)

    def test_invalid_json_and_failures_are_not_cached(self):
        a = Scripted("a", "not json")
        b = Scripted("b", ProviderError(TRANSIENT, "x"), ProviderError(TRANSIENT, "x"))
        with self.assertRaises(AllProvidersFailed):
            self.chain(a, b).complete("p")
        self.assertEqual(list(Path(self.tmp.name).glob("*.json")), [])

    def test_entries_expire(self):
        a = Scripted("a")
        self.chain(a).complete("p")
        self.now[0] += 3601
        self.assertFalse(self.chain(a).complete("p").cached)
        self.assertEqual(len(a.calls), 2)

    def test_purge_removes_expired_and_corrupt_entries(self):
        self.cache.put(prompt_key("old", True), GOOD, "a", "m")
        (Path(self.tmp.name) / "broken.json").write_text("{not json", encoding="utf-8")
        self.now[0] += 3601
        self.cache.put(prompt_key("new", True), GOOD, "a", "m")
        self.assertEqual(self.cache.purge_expired(), 2)
        self.assertEqual(len(list(Path(self.tmp.name).glob("*.json"))), 1)

    def test_disabled_cache_and_unwritable_directory_are_harmless(self):
        disabled = LLMCache(self.tmp.name, enabled=False)
        disabled.put("k", GOOD, "a", "m")
        self.assertIsNone(disabled.get("k"))
        blocked = LLMCache(Path(self.tmp.name) / "file.txt" / "sub")
        (Path(self.tmp.name) / "file.txt").write_text("x", encoding="utf-8")
        blocked.put("k", GOOD, "a", "m")  # must not raise


class DemotionTests(unittest.TestCase):
    def test_providers_that_only_failed_recently_move_to_the_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "agent.db"
            initialize_database(db)
            connection = sqlite3.connect(db)
            for _ in range(3):
                connection.execute(
                    "INSERT INTO api_usage(created_at, service, operation, provider, ok) VALUES (strftime('%Y-%m-%dT%H:%M:%SZ','now'), 'llm', 'chat', 'groq', 0)"
                )
            connection.execute(
                "INSERT INTO api_usage(created_at, service, operation, provider, ok) VALUES (strftime('%Y-%m-%dT%H:%M:%SZ','now'), 'llm', 'chat', 'gemini', 0)"
            )
            connection.commit()
            connection.close()
            providers = [Scripted("groq"), Scripted("gemini"), Scripted("pollinations")]
            ordered = demote_recently_failing(providers, str(db))
            # groq: 3 calls, 0 ok -> demoted. gemini has only 1 call -> not enough evidence.
            self.assertEqual([p.name for p in ordered], ["gemini", "pollinations", "groq"])

    def test_missing_or_in_memory_database_keeps_the_configured_order(self):
        providers = [Scripted("a"), Scripted("b")]
        self.assertEqual(demote_recently_failing(providers, ":memory:"), providers)
        self.assertEqual(demote_recently_failing(providers, "does-not-exist.db"), providers)


class RegistryAndCheckTests(unittest.TestCase):
    def test_providers_without_credentials_are_skipped_but_keyless_ones_stay(self):
        settings = settings_for(LLM_CHAIN="groq,gemini,cloudflare,openrouter,pollinations,opencode", GROQ_API_KEY="k")
        names = [p.name for p in build_providers(settings, opencode_client=object())]
        self.assertEqual(names, ["groq", "pollinations", "opencode"])
        status = {s.name: s for s in describe_chain(settings)}
        self.assertTrue(status["groq"].configured)
        self.assertEqual(status["gemini"].reason, "GEMINI_API_KEY is not set")
        self.assertIn("CLOUDFLARE_ACCOUNT_ID", status["cloudflare"].reason)

    def test_only_the_gpt_oss_provider_gets_reasoning_effort(self):
        settings = settings_for(LLM_CHAIN="pollinations,groq", GROQ_API_KEY="k")
        specs = {p.name: p.spec for p in build_providers(settings)}
        self.assertEqual(specs["pollinations"].extra_body, {"reasoning_effort": "low"})
        self.assertEqual(specs["groq"].extra_body, {})  # Llama models would reject the parameter

    def test_cloudflare_url_contains_the_account_id(self):
        settings = settings_for(LLM_CHAIN="cloudflare", CLOUDFLARE_ACCOUNT_ID="acc123", CLOUDFLARE_API_TOKEN="t")
        (provider,) = build_providers(settings)
        self.assertEqual(
            provider.spec.chat_url, "https://api.cloudflare.com/client/v4/accounts/acc123/ai/v1/chat/completions"
        )

    def test_gemini_reuses_the_existing_settings(self):
        settings = settings_for(LLM_CHAIN="gemini", GEMINI_API_KEY="g", GEMINI_MODEL="gemini-x")
        (provider,) = build_providers(settings)
        self.assertEqual(provider.spec.chat_url, "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
        self.assertEqual(provider.spec.model, "gemini-x")

    def test_unknown_names_are_rejected_and_the_default_is_legacy_mode(self):
        with self.assertRaises(ValueError):
            settings_for(LLM_CHAIN="groq,bogus")
        self.assertEqual(settings_for().llm_chain, ())
        self.assertEqual(settings_for(LLM_CHAIN=" Groq , GEMINI ").llm_chain, ("groq", "gemini"))

    def test_check_reports_ok_failed_and_not_json(self):
        good = Scripted("good")
        bad = Scripted("bad", ProviderError(AUTH, "HTTP 401: nope"))
        chatty = Scripted("chatty", "I would be glad to help")
        self.assertEqual(check_provider(good).status, "ok")
        row = check_provider(bad)
        self.assertEqual(row.status, "failed")
        self.assertIn("auth", row.detail)
        self.assertEqual(check_provider(chatty).status, "failed")

    def test_check_retries_without_json_mode_and_renders_tables(self):
        provider = Scripted("p", ProviderError(JSON_MODE, "response_format"))
        self.assertEqual(check_provider(provider).status, "ok")
        settings = settings_for(LLM_CHAIN="groq,pollinations")
        rows = run_check([Scripted("pollinations")], describe_chain(settings))
        self.assertEqual([r.status for r in rows], ["not configured", "ok"])
        self.assertIn("groq", render_text(rows))
        markdown = render_markdown(rows)
        self.assertIn("| pollinations | ✅ ok |", markdown)
        self.assertIn("➖", markdown)


class ClientIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self._env = patch.dict(
            os.environ,
            {
                "LOG_LEVEL": "WARNING",
                "DATABASE_PATH": ":memory:",
                "OPENCODE_COMMAND": "opencode",
                "INSTAGRAM_ENABLED": "false",
                "IMAGE_PROVIDER": "local",
                "LLM_CHAIN": "pollinations,opencode",
                "LLM_BACKOFF_SECONDS": "0",
            },
            clear=True,
        )
        self._env.start()
        reset_health()

    def tearDown(self):
        self._env.stop()
        os.chdir(self._cwd)
        self.tmp.cleanup()

    def client(self):
        return OpenCodeClient(recorder=PromptRecorder(logs_dir=Path(self.tmp.name) / "logs"))

    @patch("requests.post")
    def test_run_uses_the_chain_and_returns_the_answer(self, post):
        post.return_value = response(body=ok_body('```json\n{"topic": "x"}\n```'))
        result = self.client().run([], input_text="prompt", label="ResearchAgent")
        self.assertEqual(json.loads(result.stdout), {"topic": "x"})
        self.assertEqual(post.call_args.kwargs["json"]["model"], "openai-fast")

    @patch("requests.post")
    def test_falls_back_to_the_opencode_cli_when_http_providers_fail(self, post):
        post.side_effect = requests.ConnectionError("down")
        client = self.client()
        with patch.object(OpenCodeClient, "_run_opencode", return_value=OpenCodeResult(GOOD, "", 0, 0.1)) as cli:
            result = client.run([], input_text="prompt", label="x")
        self.assertEqual(json.loads(result.stdout), {"ok": True})
        cli.assert_called_once()

    @patch("requests.post")
    def test_total_failure_raises_opencode_error_so_agents_and_pipeline_can_fall_back(self, post):
        post.side_effect = requests.ConnectionError("down")
        client = self.client()
        with patch.object(OpenCodeClient, "_run_opencode", side_effect=OpenCodeError("cli missing", -1, "", "")):
            with self.assertRaises(OpenCodeError) as ctx:
                client.run([], input_text="prompt", label="x")
        self.assertIn("All LLM providers failed", str(ctx.exception))

    @patch("requests.post")
    def test_second_agent_does_not_pay_for_a_provider_the_first_found_dead(self, post):
        post.return_value = response(status=401, text="bad key")
        with patch.object(OpenCodeClient, "_run_opencode", return_value=OpenCodeResult(GOOD, "", 0, 0.1)):
            self.client().run([], input_text="one")
            self.client().run([], input_text="two")  # a different client object, as each agent has
        self.assertEqual(post.call_count, 1)

    def test_cli_llm_check_exit_codes(self):
        def run(*args):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                return main(list(args)), out.getvalue(), err.getvalue()

        with patch("requests.post", return_value=response(body=ok_body())):
            code, out, _ = run("llm-check")
        self.assertEqual(code, 0)
        self.assertIn("pollinations", out)
        self.assertIn("skipped", out)
        with patch("requests.post", side_effect=requests.ConnectionError("down")):
            code, _, err = run("llm-check", "--markdown")
        self.assertEqual(code, 1)
        self.assertIn("templates only", err)
        with patch.dict(os.environ, {"LLM_CHAIN": ""}):
            code, _, err = run("llm-check")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
