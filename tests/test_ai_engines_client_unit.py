"""Unit tests for the v3 G3 Stage 1 AI-engine share-of-voice client
(stubbed, no real network)."""

from __future__ import annotations

from typing import Any

import pytest

from silentfrog.integrations.ai_engines import client as sov_client
from silentfrog.integrations.ai_engines.client import (
    fetch_share_of_voice,
    probe_gemini,
    probe_openai,
    probe_perplexity,
)
from silentfrog.integrations.ai_engines.client import (
    test_connection as run_test_connection,  # aliased: pytest would collect a `test_` name
)


@pytest.fixture(autouse=True)
def _clear_report_memo() -> None:
    # The per-host one-sampling-per-session memo would leak reports across
    # tests in one pytest process.
    sov_client._REPORT_MEMO.clear()


class _Resp:
    def __init__(self, status: int, body: Any = None) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self) -> _Resp:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    async def json(self, content_type: Any = None) -> Any:
        return self._body


class _DummySession:
    """Route by URL substring -> response factory. Records every POST url
    so tests can assert zero-network-call contracts."""

    def __init__(self, routes: dict[str, _Resp] | None = None, raises: type[Exception] | None = None) -> None:
        self._routes = routes or {}
        self._raises = raises
        self.calls: list[str] = []

    def post(self, url: str, **_: Any) -> _Resp:
        self.calls.append(url)
        if self._raises is not None:
            raise self._raises("simulated")
        for key, resp in self._routes.items():
            if key in url:
                return resp
        return _Resp(404, body={})

    async def close(self) -> None:
        return None


_OPENAI_BODY = {"choices": [{"message": {"content": "Acme is a great tool trusted by many teams."}}]}
_PERPLEXITY_BODY = {
    "choices": [{"message": {"content": "Acme offers strong reliability."}}],
    "citations": ["https://acme.com/about", "https://other.example/x"],
}
_GEMINI_BODY = {"candidates": [{"content": {"parts": [{"text": "Acme "}, {"text": "is solid."}]}}]}


# --- per-engine happy-path parse --------------------------------------------


@pytest.mark.asyncio
async def test_probe_openai_parses_answer() -> None:
    session = _DummySession({"api.openai.com": _Resp(200, _OPENAI_BODY)})
    answer = await probe_openai("What is Acme?", "KEY", session)
    assert answer.measured is True
    assert answer.engine == "openai"
    assert "great tool" in answer.text
    assert answer.citations == ()
    assert session.calls == ["https://api.openai.com/v1/chat/completions"]


@pytest.mark.asyncio
async def test_probe_perplexity_parses_answer_and_citations() -> None:
    session = _DummySession({"api.perplexity.ai": _Resp(200, _PERPLEXITY_BODY)})
    answer = await probe_perplexity("What is Acme?", "KEY", session)
    assert answer.measured is True
    assert answer.engine == "perplexity"
    assert "strong reliability" in answer.text
    assert answer.citations == ("https://acme.com/about", "https://other.example/x")


@pytest.mark.asyncio
async def test_probe_gemini_joins_answer_parts() -> None:
    session = _DummySession({"generativelanguage.googleapis.com": _Resp(200, _GEMINI_BODY)})
    answer = await probe_gemini("What is Acme?", "KEY", session)
    assert answer.measured is True
    assert answer.engine == "gemini"
    assert answer.text == "Acme  is solid."
    assert answer.citations == ()  # Gemini's API returns no citation list


# --- non-200 / garbage -> unmeasured -----------------------------------------


@pytest.mark.asyncio
async def test_probe_openai_http_error_is_unmeasured() -> None:
    session = _DummySession({"api.openai.com": _Resp(500, {})})
    answer = await probe_openai("prompt", "KEY", session)
    assert answer.measured is False
    assert answer.text == ""


@pytest.mark.asyncio
async def test_probe_perplexity_garbage_body_is_unmeasured() -> None:
    session = _DummySession({"api.perplexity.ai": _Resp(200, {"unexpected": "shape"})})
    answer = await probe_perplexity("prompt", "KEY", session)
    assert answer.measured is False


@pytest.mark.asyncio
async def test_probe_gemini_missing_parts_is_unmeasured() -> None:
    session = _DummySession({"generativelanguage.googleapis.com": _Resp(200, {"candidates": [{}]})})
    answer = await probe_gemini("prompt", "KEY", session)
    assert answer.measured is False


@pytest.mark.asyncio
async def test_probe_openai_network_exception_is_unmeasured() -> None:
    session = _DummySession(raises=ConnectionError)
    answer = await probe_openai("prompt", "KEY", session)
    assert answer.measured is False


# --- disabled-by-default contract -------------------------------------------


@pytest.mark.asyncio
async def test_fetch_disabled_without_env_flag_makes_zero_calls(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SILENTFROG_AI_SOV_ENABLE", raising=False)
    monkeypatch.setenv("SILENTFROG_OPENAI_API_KEY", "KEY")  # a key present is not enough on its own
    session = _DummySession({"api.openai.com": _Resp(200, _OPENAI_BODY)})
    report = await fetch_share_of_voice("acme.com", "Acme", session=session)
    assert report.measured is False
    assert report.engines == ()
    assert session.calls == []


@pytest.mark.asyncio
async def test_fetch_enabled_but_no_keys_makes_zero_calls(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SILENTFROG_AI_SOV_ENABLE", "1")
    monkeypatch.delenv("SILENTFROG_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SILENTFROG_PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("SILENTFROG_GEMINI_API_KEY", raising=False)
    session = _DummySession({"api.openai.com": _Resp(200, _OPENAI_BODY)})
    report = await fetch_share_of_voice("acme.com", "Acme", session=session)
    assert report.measured is False
    assert session.calls == []


# --- fetch_share_of_voice end-to-end (one keyed engine) ----------------------


@pytest.mark.asyncio
async def test_fetch_samples_each_host_once_per_session(monkeypatch, tmp_path) -> None:
    # The collector runs per audited URL; without the per-host memo a site
    # crawl would repeat the same paid prompts for every page of the host.
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SILENTFROG_AI_SOV_ENABLE", "1")
    monkeypatch.setenv("SILENTFROG_OPENAI_API_KEY", "KEY")
    monkeypatch.delenv("SILENTFROG_PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("SILENTFROG_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SILENTFROG_AI_SOV_PROMPTS", "What is Acme?")
    session = _DummySession({"api.openai.com": _Resp(200, _OPENAI_BODY)})

    first = await fetch_share_of_voice("acme.com", "Acme", session=session)
    calls_after_first = list(session.calls)
    second = await fetch_share_of_voice("acme.com", "Acme", session=session)

    assert first.measured is True
    assert second == first
    assert session.calls == calls_after_first  # no extra network on the second page
    third = await fetch_share_of_voice("other.example", "Other", session=session)
    assert third.measured is True
    assert len(session.calls) > len(calls_after_first)  # a new host samples again


@pytest.mark.asyncio
async def test_fetch_samples_only_keyed_engines(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SILENTFROG_AI_SOV_ENABLE", "1")
    monkeypatch.setenv("SILENTFROG_OPENAI_API_KEY", "KEY")
    monkeypatch.delenv("SILENTFROG_PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("SILENTFROG_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SILENTFROG_AI_SOV_PROMPTS", "What is Acme?")
    session = _DummySession({"api.openai.com": _Resp(200, _OPENAI_BODY)})
    report = await fetch_share_of_voice("acme.com", "Acme", session=session)
    assert report.measured is True
    assert {engine.engine for engine in report.engines} == {"openai"}
    assert report.engines[0].mention_count == 1
    assert session.calls == ["https://api.openai.com/v1/chat/completions"]


# --- test_connection (v3 G3 Stage 2) -----------------------------------------


@pytest.mark.asyncio
async def test_test_connection_happy_path() -> None:
    session = _DummySession({"api.openai.com": _Resp(200, _OPENAI_BODY)})
    ok, message = await run_test_connection("openai", "KEY", session=session)
    assert ok is True
    assert message == "ok"
    assert session.calls == ["https://api.openai.com/v1/chat/completions"]


@pytest.mark.asyncio
async def test_test_connection_http_error_is_failure() -> None:
    session = _DummySession({"generativelanguage.googleapis.com": _Resp(401, {})})
    ok, message = await run_test_connection("gemini", "KEY", session=session)
    assert ok is False
    assert message == "request failed (HTTP or network error)."


@pytest.mark.asyncio
async def test_test_connection_network_exception_is_failure() -> None:
    session = _DummySession(raises=ConnectionError)
    ok, _message = await run_test_connection("perplexity", "KEY", session=session)
    assert ok is False


@pytest.mark.asyncio
async def test_test_connection_empty_key_short_circuits() -> None:
    ok, message = await run_test_connection("openai", "")
    assert ok is False
    assert message == "No API key set."


@pytest.mark.asyncio
async def test_test_connection_unknown_engine_short_circuits() -> None:
    ok, message = await run_test_connection("claude", "KEY")
    assert ok is False
    assert "Unknown engine" in message


# --- PR-G2: INT-2 (Settings opt-in), INT-4 (single flight), INT-6 (memo) ------


class _OpenAiServer:
    """A local OpenAI stand-in that counts real POSTs and answers slowly enough
    for concurrent callers to overlap (so a missing guard shows as extra POSTs)."""

    def __init__(self) -> None:
        self.posts = 0
        self.status = 200

    async def handler(self, _request):
        import asyncio

        from aiohttp import web

        self.posts += 1
        await asyncio.sleep(0.05)
        if self.status != 200:
            return web.Response(status=self.status)
        return web.json_response(_OPENAI_BODY)


async def _sov_setup(aiohttp_server, monkeypatch, tmp_path, *, enable_env: str | None) -> _OpenAiServer:
    from aiohttp import web

    fake = _OpenAiServer()
    app = web.Application()
    app.router.add_post("/v1/chat", fake.handler)
    server = await aiohttp_server(app)
    monkeypatch.setattr(sov_client, "_OPENAI_URL", str(server.make_url("/v1/chat")))
    monkeypatch.setattr(sov_client, "_keyring", lambda: (_ for _ in ()).throw(RuntimeError("no keychain in tests")))
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    if enable_env is None:
        monkeypatch.delenv("SILENTFROG_AI_SOV_ENABLE", raising=False)
    else:
        monkeypatch.setenv("SILENTFROG_AI_SOV_ENABLE", enable_env)
    monkeypatch.setenv("SILENTFROG_OPENAI_API_KEY", "KEY-1")
    monkeypatch.delenv("SILENTFROG_PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("SILENTFROG_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SILENTFROG_AI_SOV_PROMPTS", "What is Acme?;Is Acme good?")
    return fake


@pytest.mark.asyncio
async def test_settings_opt_in_enables_sampling_without_the_env_var(aiohttp_server, monkeypatch, tmp_path) -> None:
    from silentfrog.integrations.ai_engines.config import AiEnginesConfig, save_config

    fake = await _sov_setup(aiohttp_server, monkeypatch, tmp_path, enable_env=None)
    assert sov_client._enabled() is False
    assert (await fetch_share_of_voice("acme.com", "Acme")).measured is False
    assert fake.posts == 0  # both switches off: not a single paid call

    save_config(AiEnginesConfig(enabled=True))
    assert sov_client._enabled() is True
    report = await fetch_share_of_voice("acme.com", "Acme")
    assert report.measured is True
    assert fake.posts == 2  # 1 keyed engine x 2 prompts


@pytest.mark.asyncio
async def test_concurrent_callers_for_one_host_share_one_sampling(aiohttp_server, monkeypatch, tmp_path) -> None:
    import asyncio

    fake = await _sov_setup(aiohttp_server, monkeypatch, tmp_path, enable_env="1")

    reports = await asyncio.gather(*[fetch_share_of_voice("acme.com", "Acme") for _ in range(4)])

    assert fake.posts == 2  # engines x prompts, not 4x that
    assert all(report.measured for report in reports)


@pytest.mark.asyncio
async def test_failed_sampling_is_not_remembered_and_a_fixed_key_resamples(
    aiohttp_server, monkeypatch, tmp_path
) -> None:
    fake = await _sov_setup(aiohttp_server, monkeypatch, tmp_path, enable_env="1")
    fake.status = 401

    failed = await fetch_share_of_voice("acme.com", "Acme")
    assert failed.measured is False
    assert sov_client._REPORT_MEMO == {}

    fake.status = 200
    monkeypatch.setenv("SILENTFROG_OPENAI_API_KEY", "KEY-2")
    fixed = await fetch_share_of_voice("acme.com", "Acme")
    assert fixed.measured is True
    assert fake.posts == 4  # 2 failed probes, then 2 real ones


@pytest.mark.asyncio
async def test_memo_is_per_key_so_a_changed_key_resamples(aiohttp_server, monkeypatch, tmp_path) -> None:
    fake = await _sov_setup(aiohttp_server, monkeypatch, tmp_path, enable_env="1")

    await fetch_share_of_voice("acme.com", "Acme")
    await fetch_share_of_voice("acme.com", "Acme")
    assert fake.posts == 2  # same host, same key: sampled once

    monkeypatch.setenv("SILENTFROG_OPENAI_API_KEY", "KEY-2")
    await fetch_share_of_voice("acme.com", "Acme")
    assert fake.posts == 4
    assert all("KEY-" not in memo_key for memo_key in sov_client._REPORT_MEMO)  # keys are hashed, never stored


def test_ai_engines_config_defaults_off_and_survives_corruption(monkeypatch, tmp_path) -> None:
    from silentfrog.integrations.ai_engines.config import AiEnginesConfig, load_config, save_config

    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    assert load_config().enabled is False
    save_config(AiEnginesConfig(enabled=True))
    assert load_config().enabled is True
    (tmp_path / "ai_engines" / "config.json").write_text("{not json", encoding="utf-8")
    assert load_config().enabled is False
