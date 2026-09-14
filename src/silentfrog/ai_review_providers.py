"""Concrete ``AiReviewClient`` implementations for the v3 G7 AI-assisted
review (PLAN.md M7): Ollama (local-first, no key needed), Gemini (Google's
free tier — the recommended path for a machine without a local Ollama
server), OpenAI and Anthropic (BYO key). Plain REST via ``aiohttp`` — no
vendor SDKs, no new base dependency (``aiohttp`` is already a base dep; see
``fetcher`` strategy and ``integrations.ai_engines.client``).

Each client's ``review()`` stays SYNC to match the existing
``AiReviewClient`` Protocol and ``StaticAiReviewClient`` mock. Callers are a
GUI daemon thread (see ``ai_review_dialog.AiReviewResultDialog``) or a CLI
command running the client via ``asyncio.to_thread`` (see
``cli._review_cmd``) — never the Qt UI thread and never an already-running
asyncio loop. That lets each client drive its single aiohttp POST with one
``asyncio.run(...)`` inside ``review()``: safe because neither caller already
has a loop running on that thread. Calling ``review()`` directly from inside
a running asyncio loop would raise (nested ``asyncio.run``) — that is why the
CLI command hops to a worker thread instead of awaiting it in-loop.

Every failure — missing key, HTTP error, network exception, or a response
that isn't the JSON shape ``parse_ai_review_response`` expects — degrades to
an ``AiReviewResult`` with no findings and a short ``raw_summary`` starting
with ``"error: "``. Three tiers of failure are distinguished, so the GUI
result dialog can show something actionable for the common "Ollama isn't
running" case without over-fitting to every provider's error body shape:
a PRE-response failure (connection refused, DNS, timeout — the request
never got an HTTP response at all) carries a "not reachable"/"timed out"
reason; a 2xx response whose BODY isn't even JSON (a proxy/captive-portal
HTML page, an HTML error page some servers return with a 200) carries
``"unexpected response shape (not JSON)"`` — never "not reachable", since the
server there was very much reachable; and a 2xx response with a valid JSON
body that just doesn't have the provider's expected keys stays the generic
``"error: empty response"`` (``_finish``'s fallback when the per-provider
text-extractor finds nothing). These clients never raise.
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

_GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"

# Public: the GUI setup dialog uses this to placeholder the model field per
# provider without duplicating the literal default-model strings above.
DEFAULT_MODELS: dict[str, str] = {
    "ollama": _OLLAMA_DEFAULT_MODEL,
    "openai": _OPENAI_DEFAULT_MODEL,
    "anthropic": _ANTHROPIC_DEFAULT_MODEL,
    "gemini": _GEMINI_DEFAULT_MODEL,
}

# GUI/CLI provider picker order — Gemini first (Google's free tier is the
# recommended path when no local Ollama server is running).
PROVIDER_CHOICES: tuple[tuple[str, str], ...] = (
    ("gemini", "Gemini (Google — free tier)"),
    ("openai", "OpenAI"),
    ("anthropic", "Anthropic"),
    ("ollama", "Ollama (local, no key)"),
)

_OLLAMA_REMEDY = (
    "Ollama is not reachable at {url}. Start it with `ollama serve` (and `ollama pull llama3.2`), "
    "or pick Gemini — Google offers a free API key at https://aistudio.google.com/apikey."
)


async def _post_json(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: int,
) -> tuple[dict[str, Any] | None, str | None]:
    """One best-effort POST returning ``(body, None)`` on success or
    ``(None, reason)`` on any pre-response failure (HTTP error status,
    network exception, timeout) or a 2xx body that isn't the expected JSON
    object. Never raises. Cloned from
    ``integrations.ai_engines.client._post_json`` (same shape) rather than
    imported — that module's helper is private and this one owns a
    different caller (single-shot review clients, not a sampler) and needs
    to surface the failure reason, not just swallow it.

    Decoding the body is deliberately its OWN try, separate from the
    request/connect try below: a 2xx response whose body isn't JSON (a
    proxy/captive-portal HTML page, or an HTML error page some servers
    return with a 200) must never be reported as "not reachable" — the
    server plainly WAS reachable, it just didn't answer with JSON."""
    try:
        async with session.post(url, headers=headers, json=body, timeout=ClientTimeout(total=timeout)) as response:
            if response.status >= 400:
                raw = await response.text()
                return None, f"HTTP {response.status}: {raw[:200]}"
            return await _decode_json_body(response)
    except TimeoutError:
        return None, f"timed out after {timeout}s"
    except Exception:  # noqa: BLE001 - any pre-response failure must degrade, never raise
        return None, f"connection refused / not reachable at {url}"


async def _decode_json_body(response: aiohttp.ClientResponse) -> tuple[dict[str, Any] | None, str | None]:
    """Decode a successful (2xx) response's body. A decode failure or a
    non-dict JSON value here means the server answered but not with the
    expected JSON object — distinct from a pre-response network failure,
    see ``_post_json``'s docstring."""
    try:
        data = await response.json(content_type=None)
    except Exception:  # noqa: BLE001 - a malformed/non-JSON body must degrade, never raise
        return None, "unexpected response shape (not JSON)"
    if not isinstance(data, dict):
        return None, "unexpected response shape (not JSON)"
    return data, None


async def _post_with_own_session(
    session: aiohttp.ClientSession | None,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: int,
) -> tuple[dict[str, Any] | None, str | None]:
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
    degrade to a short error result. Never raises. Only reached once the POST
    itself succeeded — an empty/garbage extraction here means the 2xx body
    didn't have the shape the provider's text-extractor expects."""
    if not text:
        return AiReviewResult(provider=provider, model=model, findings=(), raw_summary="error: empty response")
    try:
        return parse_ai_review_response(text, provider=provider, model=model)
    except Exception as exc:  # noqa: BLE001 - any parse failure must degrade, never raise
        return AiReviewResult(provider=provider, model=model, findings=(), raw_summary=f"error: {_short(exc)}")


def _post_error_result(provider: str, model: str, reason: str) -> AiReviewResult:
    """The POST itself failed (HTTP error/timeout/network) — carry the real
    reason into raw_summary instead of the generic empty-response message."""
    return AiReviewResult(provider=provider, model=model, findings=(), raw_summary=f"error: {reason}")


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


def _gemini_text(data: dict[str, Any] | None) -> str | None:
    """Same shape as ``integrations.ai_engines.client._gemini_answer``."""
    candidates = data.get("candidates") if isinstance(data, dict) else None
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        return None
    content = candidates[0].get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return None
    texts = [str(part["text"]) for part in parts if isinstance(part, dict) and part.get("text")]
    joined = " ".join(texts).strip()
    return joined or None


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
        data, error = await _post_with_own_session(self.session, f"{endpoint}/api/chat", {}, body, self.timeout)
        if error:
            return _post_error_result("ollama", model, error)
        return _finish("ollama", model, _ollama_text(data))


@dataclass(frozen=True, slots=True)
class GeminiReviewClient:
    """BYO Gemini key — Google's free tier: ``config.api_key``, else the
    shared ai-engines keyring/env resolution (``resolve_api_key("gemini")``,
    the same key the Settings -> AI share-of-voice group already stores)."""

    config: AiProviderConfig
    session: aiohttp.ClientSession | None = None
    timeout: int = _DEFAULT_TIMEOUT_SECONDS

    def review(self, request: AiReviewInput, custom_instructions: str = "") -> AiReviewResult:
        return asyncio.run(self._review_async(request, custom_instructions))

    async def _review_async(self, request: AiReviewInput, custom_instructions: str) -> AiReviewResult:
        from .integrations.ai_engines import resolve_api_key

        model = self.config.model or _GEMINI_DEFAULT_MODEL
        key = self.config.api_key or resolve_api_key("gemini")
        if not key:
            return _no_key_error("gemini", model)
        prompt = build_review_prompt(request, custom_instructions)
        url = _GEMINI_URL_TEMPLATE.format(model=model)
        headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        data, error = await _post_with_own_session(self.session, url, headers, body, self.timeout)
        if error:
            return _post_error_result("gemini", model, error)
        return _finish("gemini", model, _gemini_text(data))


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
        data, error = await _post_with_own_session(self.session, _OPENAI_URL, headers, body, self.timeout)
        if error:
            return _post_error_result("openai", model, error)
        return _finish("openai", model, _openai_text(data))


@dataclass(frozen=True, slots=True)
class AnthropicReviewClient:
    """BYO Anthropic key: ``config.api_key``, else the shared ai-engines
    keyring lookup (``resolve_api_key("anthropic")``), else
    ``SILENTFROG_ANTHROPIC_API_KEY`` directly (the keyring resolver already
    falls back to that same env var, but the direct read keeps this client
    working even if the ``ai_engines`` extra path changes)."""

    config: AiProviderConfig
    session: aiohttp.ClientSession | None = None
    timeout: int = _DEFAULT_TIMEOUT_SECONDS

    def review(self, request: AiReviewInput, custom_instructions: str = "") -> AiReviewResult:
        return asyncio.run(self._review_async(request, custom_instructions))

    async def _review_async(self, request: AiReviewInput, custom_instructions: str) -> AiReviewResult:
        from .integrations.ai_engines import resolve_api_key

        model = self.config.model or _ANTHROPIC_DEFAULT_MODEL
        key = (
            self.config.api_key
            or resolve_api_key("anthropic")
            or os.environ.get("SILENTFROG_ANTHROPIC_API_KEY", "").strip()
        )
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
        data, error = await _post_with_own_session(self.session, _ANTHROPIC_URL, headers, body, self.timeout)
        if error:
            return _post_error_result("anthropic", model, error)
        return _finish("anthropic", model, _anthropic_text(data))


# Dict dispatch, not an if/elif ladder (AGENTS.md §1 string-dispatch rule).
_CLIENT_FACTORIES: dict[str, type[Any]] = {
    "ollama": OllamaReviewClient,
    "gemini": GeminiReviewClient,
    "openai": OpenAiReviewClient,
    "anthropic": AnthropicReviewClient,
}

# Dict dispatch for the human remedy shown alongside an error result
# (AGENTS.md §1 string-dispatch rule) — ollama's is reachability-shaped,
# the BYO-key providers all share the same "check the key" shape.
_KEY_PROVIDER_REMEDY = "Check the API key and model name; {provider} returned: "


def _ollama_remedy() -> str:
    url = os.environ.get("SILENTFROG_OLLAMA_URL", "") or _OLLAMA_DEFAULT_URL
    return _OLLAMA_REMEDY.format(url=url)


_PROVIDER_REMEDIES: dict[str, Any] = {
    "ollama": _ollama_remedy,
    "gemini": lambda: _KEY_PROVIDER_REMEDY.format(provider="gemini"),
    "openai": lambda: _KEY_PROVIDER_REMEDY.format(provider="openai"),
    "anthropic": lambda: _KEY_PROVIDER_REMEDY.format(provider="anthropic"),
}


def provider_remedy(provider: str) -> str:
    """The human remedy shown next to an error result's raw reason. Unknown
    provider names get the generic BYO-key remedy phrased with their own
    name (never raises, never an empty string)."""
    normalized = provider.strip().lower()
    factory = _PROVIDER_REMEDIES.get(normalized)
    if factory is not None:
        return factory()
    return _KEY_PROVIDER_REMEDY.format(provider=normalized or "the provider")


def client_for_config(config: AiProviderConfig) -> AiReviewClient | None:
    """Build the client for ``config.provider``, or ``None`` for an
    unrecognised provider name (never raises)."""
    factory = _CLIENT_FACTORIES.get(config.provider.strip().lower())
    return factory(config) if factory else None


def _resolved_key(provider: str) -> str:
    from .integrations.ai_engines import resolve_api_key

    try:
        return resolve_api_key(provider)
    except Exception:
        return ""


def _config_for_provider(provider: str) -> AiProviderConfig:
    normalized = provider.strip().lower()
    if normalized == "ollama":
        return AiProviderConfig(provider="ollama", api_key="")
    return AiProviderConfig(provider=normalized, api_key=_resolved_key(normalized))


# Keyed providers checked in this order when nothing is configured or
# preferred — Gemini first (Google's free tier is the easiest path).
_AUTO_KEY_ORDER = ("gemini", "openai", "anthropic")


def auto_config(preferred: str | None = None) -> AiProviderConfig:
    """The config the GUI/CLI use to pick a provider automatically: an
    explicit env/``secrets.local.json`` config always wins (an operator who
    set that up meant it); otherwise ``preferred`` if given (the user's own
    GUI/CLI pick); otherwise the first provider in ``_AUTO_KEY_ORDER`` that
    already has a resolvable key; otherwise a bare Ollama config
    (local-first, no key required). Pure, never raises."""
    explicit = load_ai_provider_config()
    if explicit:
        return explicit
    if preferred:
        return _config_for_provider(preferred)
    for provider in _AUTO_KEY_ORDER:
        if _resolved_key(provider):
            return _config_for_provider(provider)
    return AiProviderConfig(provider="ollama", api_key="")


__all__ = [
    "DEFAULT_MODELS",
    "PROVIDER_CHOICES",
    "AnthropicReviewClient",
    "GeminiReviewClient",
    "OllamaReviewClient",
    "OpenAiReviewClient",
    "auto_config",
    "client_for_config",
    "provider_remedy",
]
