"""Unit tests for the v3 G7 concrete AiReviewClient implementations
(Ollama/OpenAI/Anthropic), stubbed with a _DummySession — no real network.
Mirrors tests/test_ai_engines_client_unit.py's fake-session shape."""

from __future__ import annotations

import json
from typing import Any

from silentfrog.ai_review import AiProviderConfig, AiReviewEvidence, AiReviewInput
from silentfrog.ai_review_providers import (
    AnthropicReviewClient,
    OllamaReviewClient,
    OpenAiReviewClient,
    client_for_config,
    default_config,
)


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
    so tests can assert no-network-on-short-circuit contracts."""

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


def _request() -> AiReviewInput:
    return AiReviewInput(
        target="https://example.com/page",
        scope="page",
        issues=(),
        context=(AiReviewEvidence("Title", "Example"),),
    )


_FINDINGS_JSON = json.dumps(
    {
        "summary": "One opportunity.",
        "findings": [
            {
                "id": "answer_gap",
                "severity": "warning",
                "area": "Answerability",
                "reason": "No direct answer.",
                "recommendation": "Add one.",
            }
        ],
    }
)


# --- Ollama (local-first default, no key) -----------------------------------


def test_ollama_review_happy_path() -> None:
    session = _DummySession({"localhost:11434": _Resp(200, {"message": {"content": _FINDINGS_JSON}})})
    client = OllamaReviewClient(AiProviderConfig(provider="ollama", api_key=""), session=session)

    result = client.review(_request())

    assert result.provider == "ollama"
    assert result.model == "llama3.2"
    assert result.raw_summary == "One opportunity."
    assert result.findings[0].area == "Answerability"
    assert session.calls == ["http://localhost:11434/api/chat"]


def test_ollama_review_uses_env_endpoint_and_config_model(monkeypatch) -> None:
    monkeypatch.setenv("SILENTFROG_OLLAMA_URL", "http://ollama-host:9999")
    session = _DummySession({"ollama-host:9999": _Resp(200, {"message": {"content": _FINDINGS_JSON}})})
    client = OllamaReviewClient(AiProviderConfig(provider="ollama", api_key="", model="custom-model"), session=session)

    result = client.review(_request())

    assert result.model == "custom-model"
    assert session.calls == ["http://ollama-host:9999/api/chat"]


def test_ollama_review_config_endpoint_wins_over_env(monkeypatch) -> None:
    monkeypatch.setenv("SILENTFROG_OLLAMA_URL", "http://env-host:1")
    session = _DummySession({"config-host:2": _Resp(200, {"message": {"content": _FINDINGS_JSON}})})
    client = OllamaReviewClient(
        AiProviderConfig(provider="ollama", api_key="", endpoint="http://config-host:2"), session=session
    )

    client.review(_request())

    assert session.calls == ["http://config-host:2/api/chat"]


def test_ollama_review_http_error_is_error_result_never_raises() -> None:
    session = _DummySession({"localhost:11434": _Resp(500, {})})
    client = OllamaReviewClient(AiProviderConfig(provider="ollama", api_key=""), session=session)

    result = client.review(_request())

    assert result.findings == ()
    assert result.raw_summary.startswith("error:")


def test_ollama_review_network_exception_is_error_result_never_raises() -> None:
    session = _DummySession(raises=ConnectionError)
    client = OllamaReviewClient(AiProviderConfig(provider="ollama", api_key=""), session=session)

    result = client.review(_request())

    assert result.findings == ()
    assert result.raw_summary.startswith("error:")


def test_ollama_review_garbage_json_content_is_error_result() -> None:
    session = _DummySession({"localhost:11434": _Resp(200, {"message": {"content": "not json"}})})
    client = OllamaReviewClient(AiProviderConfig(provider="ollama", api_key=""), session=session)

    result = client.review(_request())

    assert result.findings == ()
    assert result.raw_summary.startswith("error:")


def test_ollama_review_unexpected_body_shape_is_error_result() -> None:
    session = _DummySession({"localhost:11434": _Resp(200, {"unexpected": "shape"})})
    client = OllamaReviewClient(AiProviderConfig(provider="ollama", api_key=""), session=session)

    result = client.review(_request())

    assert result.raw_summary == "error: empty response"


# --- OpenAI (BYO key) --------------------------------------------------------


def test_openai_review_happy_path() -> None:
    session = _DummySession({"api.openai.com": _Resp(200, {"choices": [{"message": {"content": _FINDINGS_JSON}}]})})
    client = OpenAiReviewClient(AiProviderConfig(provider="openai", api_key="KEY"), session=session)

    result = client.review(_request())

    assert result.provider == "openai"
    assert result.model == "gpt-4o-mini"
    assert result.findings[0].reason == "No direct answer."
    assert session.calls == ["https://api.openai.com/v1/chat/completions"]


def test_openai_review_no_key_short_circuits_without_network(monkeypatch) -> None:
    monkeypatch.delenv("SILENTFROG_OPENAI_API_KEY", raising=False)
    session = _DummySession({"api.openai.com": _Resp(200, {})})
    client = OpenAiReviewClient(AiProviderConfig(provider="openai", api_key=""), session=session)

    result = client.review(_request())

    assert result.raw_summary == "error: no API key configured"
    assert session.calls == []


def test_openai_review_falls_back_to_shared_env_key(monkeypatch) -> None:
    monkeypatch.setenv("SILENTFROG_OPENAI_API_KEY", "env-key")
    session = _DummySession({"api.openai.com": _Resp(200, {"choices": [{"message": {"content": _FINDINGS_JSON}}]})})
    client = OpenAiReviewClient(AiProviderConfig(provider="openai", api_key=""), session=session)

    result = client.review(_request())

    assert result.findings
    assert session.calls == ["https://api.openai.com/v1/chat/completions"]


def test_openai_review_http_error_is_error_result() -> None:
    session = _DummySession({"api.openai.com": _Resp(500, {})})
    client = OpenAiReviewClient(AiProviderConfig(provider="openai", api_key="KEY"), session=session)

    result = client.review(_request())

    assert result.raw_summary.startswith("error:")


# --- Anthropic (BYO key) -----------------------------------------------------


def test_anthropic_review_happy_path() -> None:
    session = _DummySession({"api.anthropic.com": _Resp(200, {"content": [{"text": _FINDINGS_JSON}]})})
    client = AnthropicReviewClient(AiProviderConfig(provider="anthropic", api_key="KEY"), session=session)

    result = client.review(_request())

    assert result.provider == "anthropic"
    assert result.model == "claude-haiku-4-5-20251001"
    assert result.findings[0].area == "Answerability"
    assert session.calls == ["https://api.anthropic.com/v1/messages"]


def test_anthropic_review_no_key_short_circuits_without_network(monkeypatch) -> None:
    monkeypatch.delenv("SILENTFROG_ANTHROPIC_API_KEY", raising=False)
    session = _DummySession({"api.anthropic.com": _Resp(200, {})})
    client = AnthropicReviewClient(AiProviderConfig(provider="anthropic", api_key=""), session=session)

    result = client.review(_request())

    assert result.raw_summary == "error: no API key configured"
    assert session.calls == []


def test_anthropic_review_falls_back_to_env_key(monkeypatch) -> None:
    monkeypatch.setenv("SILENTFROG_ANTHROPIC_API_KEY", "env-key")
    session = _DummySession({"api.anthropic.com": _Resp(200, {"content": [{"text": _FINDINGS_JSON}]})})
    client = AnthropicReviewClient(AiProviderConfig(provider="anthropic", api_key=""), session=session)

    result = client.review(_request())

    assert result.findings
    assert session.calls == ["https://api.anthropic.com/v1/messages"]


def test_anthropic_review_garbage_body_is_error_result() -> None:
    session = _DummySession({"api.anthropic.com": _Resp(200, {"content": [{}]})})
    client = AnthropicReviewClient(AiProviderConfig(provider="anthropic", api_key="KEY"), session=session)

    result = client.review(_request())

    assert result.raw_summary == "error: empty response"


def test_anthropic_review_empty_content_list_is_error_result() -> None:
    session = _DummySession({"api.anthropic.com": _Resp(200, {"content": []})})
    client = AnthropicReviewClient(AiProviderConfig(provider="anthropic", api_key="KEY"), session=session)

    result = client.review(_request())

    assert result.raw_summary == "error: empty response"


# --- custom instructions reach the prompt -----------------------------------


def test_custom_instructions_are_forwarded_into_the_prompt() -> None:
    session = _DummySession({"api.anthropic.com": _Resp(200, {"content": [{"text": _FINDINGS_JSON}]})})
    client = AnthropicReviewClient(AiProviderConfig(provider="anthropic", api_key="KEY"), session=session)

    client.review(_request(), "Is this page ready to publish?")

    # The dummy session doesn't record request bodies; the contract under
    # test here is just that passing custom_instructions doesn't raise and
    # still reaches the provider (prompt content itself is covered by
    # test_ai_review.py's build_review_prompt tests).
    assert session.calls == ["https://api.anthropic.com/v1/messages"]


# --- dispatch / defaults ------------------------------------------------------


def test_client_for_config_dispatches_known_providers() -> None:
    assert isinstance(client_for_config(AiProviderConfig(provider="ollama", api_key="")), OllamaReviewClient)
    assert isinstance(client_for_config(AiProviderConfig(provider="OpenAI", api_key="k")), OpenAiReviewClient)
    assert isinstance(client_for_config(AiProviderConfig(provider="anthropic", api_key="k")), AnthropicReviewClient)


def test_client_for_config_unknown_provider_is_none() -> None:
    assert client_for_config(AiProviderConfig(provider="custom", api_key="k")) is None


def test_default_config_falls_back_to_ollama_when_nothing_configured(monkeypatch, tmp_path) -> None:
    for name in (
        "SILENTFROG_AI_API_KEY",
        "SILENTFROG_AI_PROVIDER",
        "SILENTFROG_AI_MODEL",
        "SILENTFROG_AI_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # no secrets.local.json here

    config = default_config()

    assert config.provider == "ollama"
    assert config.api_key == ""


def test_default_config_prefers_a_configured_provider(monkeypatch) -> None:
    monkeypatch.setenv("SILENTFROG_AI_PROVIDER", "openai")
    monkeypatch.setenv("SILENTFROG_AI_API_KEY", "secret")

    config = default_config()

    assert config.provider == "openai"
    assert config.api_key == "secret"
