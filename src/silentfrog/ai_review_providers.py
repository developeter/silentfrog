"""Concrete ``AiReviewClient`` implementations for the v3 G7 AI-assisted
review (PLAN.md M7): Ollama (local-first default, no key needed), OpenAI and
Anthropic (BYO key). Plain REST via ``aiohttp`` — no vendor SDKs, no new base
dependency (``aiohttp`` is already a base dep; see ``fetcher`` strategy and
``integrations.ai_engines.client``).

Each client's ``review()`` stays SYNC to match the existing
``AiReviewClient`` Protocol and ``StaticAiReviewClient`` mock. Callers are a
GUI daemon thread (see ``seo_gui._on_ai_review``) or a CLI command running
the client via ``asyncio.to_thread`` (see ``cli._review_cmd``) — never the
Qt UI thread and never an already-running asyncio loop. That lets each
client drive its single aiohttp POST with one ``asyncio.run(...)`` inside
``review()``: safe because neither caller already has a loop running on
that thread. Calling ``review()`` directly from inside a running asyncio
loop would raise (nested ``asyncio.run``) — that is why the CLI command
hops to a worker thread instead of awaiting it in-loop.

Every failure — missing key, HTTP error, network exception, or a response
that isn't the JSON shape ``parse_ai_review_response`` expects — degrades to
an ``AiReviewResult`` with no findings and a short ``raw_summary`` starting
with ``"error: "``. These clients never raise.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiohttp import ClientTimeout

from .ai_review import (
    AiProviderConfig,
    AiReviewClient,
    AiReviewInput,
    AiReviewResult,
    build_review_prompt,
    load_ai_provider_config,
    parse_ai_review_response,
)

_DEFAULT_TIMEOUT_SECONDS = 60

_OLLAMA_DEFAULT_URL = "http://localhost:11434"
_OLLAMA_DEFAULT_MODEL = "llama3.2"

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_ANTHROPIC_VERSION = "2023-06-01"
_ANTHROPIC_MAX_TOKENS = 2048


async def _post_json(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: int,
) -> dict[str, Any] | None:
    """One best-effort POST returning the parsed JSON body, or ``None`` on
    any HTTP error, network exception, or non-dict body. Never raises.
    Cloned from ``integrations.ai_engines.client._post_json`` (same shape)
    rather than imported — that module's helper is private and this one
    owns a different caller (single-shot review clients, not a sampler)."""
    try:
        async with session.post(url, headers=headers, json=body, timeout=ClientTimeout(total=timeout)) as response:
            if response.status >= 400:
                return None
            data = await response.json(content_type=None)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


async def _post_with_own_session(
    session: aiohttp.ClientSession | None,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: int,
) -> dict[str, Any] | None:
    """Open a session when the client wasn't given one (mirrors
    ``fetch_share_of_voice``'s own-session-if-none lifecycle)."""
    own_session = session is None
    active = session if session is not None else aiohttp.ClientSession()
    try:
        return await _post_json(active, url, headers, body, timeout)
    finally:
        if own_session:
            await active.close()


def _finish(provider: str, model: str, text: str | None) -> AiReviewResult:
    """Parse the extracted response text into an ``AiReviewResult``, or
    degrade to a short error result. Never raises."""
    if not text:
        return AiReviewResult(provider=provider, model=model, findings=(), raw_summary="error: empty response")
    try:
        return parse_ai_review_response(text, provider=provider, model=model)
    except Exception as exc:  # noqa: BLE001 - any parse failure must degrade, never raise
        return AiReviewResult(provider=provider, model=model, findings=(), raw_summary=f"error: {_short(exc)}")


def _no_key_error(provider: str, model: str) -> AiReviewResult:
    return AiReviewResult(provider=provider, model=model, findings=(), raw_summary="error: no API key configured")


def _short(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:200]


def _ollama_text(data: dict[str, Any] | None) -> str | None:
    message = data.get("message") if isinstance(data, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, str) and content.strip() else None


def _openai_text(data: dict[str, Any] | None) -> str | None:
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, str) and content.strip() else None


def _anthropic_text(data: dict[str, Any] | None) -> str | None:
    content = data.get("content") if isinstance(data, dict) else None
    if not isinstance(content, list) or not content or not isinstance(content[0], dict):
        return None
    text = content[0].get("text")
    return text if isinstance(text, str) and text.strip() else None


@dataclass(frozen=True, slots=True)
class OllamaReviewClient:
    """Local-first default: no API key needed. Talks to a locally running
    Ollama server (``ollama serve``)."""

    config: AiProviderConfig
    session: aiohttp.ClientSession | None = None
    timeout: int = _DEFAULT_TIMEOUT_SECONDS

    def review(self, request: AiReviewInput, custom_instructions: str = "") -> AiReviewResult:
        return asyncio.run(self._review_async(request, custom_instructions))

    async def _review_async(self, request: AiReviewInput, custom_instructions: str) -> AiReviewResult:
        model = self.config.model or _OLLAMA_DEFAULT_MODEL
        endpoint = (self.config.endpoint or os.environ.get("SILENTFROG_OLLAMA_URL", "") or _OLLAMA_DEFAULT_URL).rstrip(
            "/"
        )
        prompt = build_review_prompt(request, custom_instructions)
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
        }
        data = await _post_with_own_session(self.session, f"{endpoint}/api/chat", {}, body, self.timeout)
        return _finish("ollama", model, _ollama_text(data))


@dataclass(frozen=True, slots=True)
class OpenAiReviewClient:
    """BYO OpenAI key: ``config.api_key``, else the shared ai-engines env
    fallback (``SILENTFROG_OPENAI_API_KEY``, keyring first)."""

    config: AiProviderConfig
    session: aiohttp.ClientSession | None = None
    timeout: int = _DEFAULT_TIMEOUT_SECONDS

    def review(self, request: AiReviewInput, custom_instructions: str = "") -> AiReviewResult:
        return asyncio.run(self._review_async(request, custom_instructions))

    async def _review_async(self, request: AiReviewInput, custom_instructions: str) -> AiReviewResult:
        from .integrations.ai_engines import resolve_api_key

        model = self.config.model or _OPENAI_DEFAULT_MODEL
        key = self.config.api_key or resolve_api_key("openai")
        if not key:
            return _no_key_error("openai", model)
        prompt = build_review_prompt(request, custom_instructions)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        data = await _post_with_own_session(self.session, _OPENAI_URL, headers, body, self.timeout)
        return _finish("openai", model, _openai_text(data))


@dataclass(frozen=True, slots=True)
class AnthropicReviewClient:
    """BYO Anthropic key: ``config.api_key``, else
    ``SILENTFROG_ANTHROPIC_API_KEY``."""

    config: AiProviderConfig
    session: aiohttp.ClientSession | None = None
    timeout: int = _DEFAULT_TIMEOUT_SECONDS

    def review(self, request: AiReviewInput, custom_instructions: str = "") -> AiReviewResult:
        return asyncio.run(self._review_async(request, custom_instructions))

    async def _review_async(self, request: AiReviewInput, custom_instructions: str) -> AiReviewResult:
        model = self.config.model or _ANTHROPIC_DEFAULT_MODEL
        key = self.config.api_key or os.environ.get("SILENTFROG_ANTHROPIC_API_KEY", "").strip()
        if not key:
            return _no_key_error("anthropic", model)
        prompt = build_review_prompt(request, custom_instructions)
        headers = {
            "x-api-key": key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "max_tokens": _ANTHROPIC_MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
        data = await _post_with_own_session(self.session, _ANTHROPIC_URL, headers, body, self.timeout)
        return _finish("anthropic", model, _anthropic_text(data))


# Dict dispatch, not an if/elif ladder (AGENTS.md §1 string-dispatch rule).
_CLIENT_FACTORIES: dict[str, type[Any]] = {
    "ollama": OllamaReviewClient,
    "openai": OpenAiReviewClient,
    "anthropic": AnthropicReviewClient,
}


def client_for_config(config: AiProviderConfig) -> AiReviewClient | None:
    """Build the client for ``config.provider``, or ``None`` for an
    unrecognised provider name (never raises)."""
    factory = _CLIENT_FACTORIES.get(config.provider.strip().lower())
    return factory(config) if factory else None


def default_config() -> AiProviderConfig:
    """The config the GUI/CLI use when the user hasn't picked one: the
    configured provider (env or ``secrets.local.json``, see
    ``load_ai_provider_config``), or else a bare Ollama config — local-first,
    no key required, matching the "off by default but usable out of the
    box" story for this feature."""
    return load_ai_provider_config() or AiProviderConfig(provider="ollama", api_key="")


__all__ = [
    "AnthropicReviewClient",
    "OllamaReviewClient",
    "OpenAiReviewClient",
    "client_for_config",
    "default_config",
]
