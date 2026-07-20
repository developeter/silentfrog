"""BYO-key AI-engine share-of-voice client (v3 G3 Stage 1, optional extra
``silentfrog[ai-engines]``, off by default).

Plain REST calls to the OpenAI / Perplexity / Gemini chat endpoints — no
vendor SDKs, no new base dependency. Every probe is a single best-effort
attempt: any HTTP error, network exception, or unexpected response shape
degrades to an unmeasured ``EngineAnswer``/``ShareOfVoiceReport``, never
raises. Mirrors ``ai_citations`` / ``brand_mentions`` self-gating (the env
knob is read INSIDE this module, not passed in by the caller) and the
Semrush client's keyring-first key resolution.

A stock audit makes ZERO calls here: ``fetch_share_of_voice`` short-circuits
before opening a session unless ``SILENTFROG_AI_SOV_ENABLE`` is set AND at
least one engine has a resolvable key.
"""

from __future__ import annotations

import os
from typing import Any

import aiohttp
from aiohttp import ClientTimeout

from .history import record_point
from .sampling import build_prompts
from .scoring import cites_domain, count_competitor_mentions, mentions_brand, sentiment_label
from .types import EngineAnswer, EngineShareOfVoice, ShareOfVoiceReport

_DEFAULT_TIMEOUT_SECONDS = 15
_KEYRING_SERVICE = "silentfrog-ai-engines"
_ENGINES = ("openai", "perplexity", "gemini")

OPENAI_MODEL = "gpt-4o-mini"
_PERPLEXITY_MODEL = "sonar"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

_ENV_KEY_FALLBACKS = {
    "openai": "SILENTFROG_OPENAI_API_KEY",
    "perplexity": "SILENTFROG_PERPLEXITY_API_KEY",
    "gemini": "SILENTFROG_GEMINI_API_KEY",
}

# One sampling per host per app session: the collector runs per audited URL,
# and a site crawl would otherwise repeat the same paid brand-level prompts
# for every page of the host. Keyed by host only — callers derive the brand
# deterministically from the host, so a second brand for the same host
# cannot occur today. Concurrent same-host workers may race past this once
# (bounded by max_concurrent_per_host); that is accepted over a loop-bound
# lock, since audits run under more than one event loop.
_REPORT_MEMO: dict[str, ShareOfVoiceReport] = {}


def _enabled() -> bool:
    raw = os.environ.get("SILENTFROG_AI_SOV_ENABLE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _competitors() -> tuple[str, ...]:
    raw = os.environ.get("SILENTFROG_AI_SOV_COMPETITORS", "")
    return tuple(name.strip() for name in raw.split(";") if name.strip())


def _keyring() -> Any:
    import keyring  # lazy, optional extra

    return keyring


def resolve_api_key(engine: str) -> str:
    """Keyring (``silentfrog-ai-engines``/``<engine>``) first, env fallback.
    Unknown engine names resolve to an empty key (never raises)."""
    try:
        stored = _keyring().get_password(_KEYRING_SERVICE, engine)
        if stored:
            return str(stored).strip()
    except Exception:
        pass
    return os.environ.get(_ENV_KEY_FALLBACKS.get(engine, ""), "").strip()


async def _post_json(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: int,
) -> dict[str, Any] | None:
    """One best-effort POST returning the parsed JSON body, or ``None`` on
    any HTTP error, network exception, or non-dict body. Never raises."""
    try:
        async with session.post(url, headers=headers, json=body, timeout=ClientTimeout(total=timeout)) as response:
            if response.status >= 400:
                return None
            data = await response.json(content_type=None)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _chat_completion_answer(engine: str, prompt: str, data: dict[str, Any] | None) -> EngineAnswer:
    """Shared OpenAI-shaped ``choices[0].message.content`` parser (used by
    both OpenAI and Perplexity). Perplexity additionally echoes a top-level
    ``citations`` list of URLs; OpenAI has none, so it tolerantly reads ()."""
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return EngineAnswer(engine=engine, prompt=prompt)
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        return EngineAnswer(engine=engine, prompt=prompt)
    citations_raw = data.get("citations") if isinstance(data, dict) else None
    citations = tuple(str(item) for item in citations_raw if item) if isinstance(citations_raw, list) else ()
    return EngineAnswer(engine=engine, prompt=prompt, text=content, citations=citations, measured=True)


def _gemini_answer(prompt: str, data: dict[str, Any] | None) -> EngineAnswer:
    candidates = data.get("candidates") if isinstance(data, dict) else None
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        return EngineAnswer(engine="gemini", prompt=prompt)
    content = candidates[0].get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return EngineAnswer(engine="gemini", prompt=prompt)
    texts = [str(part["text"]) for part in parts if isinstance(part, dict) and part.get("text")]
    joined = " ".join(texts).strip()
    if not joined:
        return EngineAnswer(engine="gemini", prompt=prompt)
    return EngineAnswer(engine="gemini", prompt=prompt, text=joined, measured=True)


async def probe_openai(
    prompt: str, api_key: str, session: aiohttp.ClientSession, timeout: int = _DEFAULT_TIMEOUT_SECONDS
) -> EngineAnswer:
    body = {"model": OPENAI_MODEL, "messages": [{"role": "user", "content": prompt}]}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = await _post_json(session, _OPENAI_URL, headers, body, timeout)
    return _chat_completion_answer("openai", prompt, data)


async def probe_perplexity(
    prompt: str, api_key: str, session: aiohttp.ClientSession, timeout: int = _DEFAULT_TIMEOUT_SECONDS
) -> EngineAnswer:
    body = {"model": _PERPLEXITY_MODEL, "messages": [{"role": "user", "content": prompt}]}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = await _post_json(session, _PERPLEXITY_URL, headers, body, timeout)
    return _chat_completion_answer("perplexity", prompt, data)


async def probe_gemini(
    prompt: str, api_key: str, session: aiohttp.ClientSession, timeout: int = _DEFAULT_TIMEOUT_SECONDS
) -> EngineAnswer:
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    data = await _post_json(session, _GEMINI_URL, headers, body, timeout)
    return _gemini_answer(prompt, data)


# Dispatch table, not an if/elif ladder (AGENTS.md §1 string-dispatch rule).
_PROBES = {"openai": probe_openai, "perplexity": probe_perplexity, "gemini": probe_gemini}

_TEST_PROMPT = "Reply with OK."


async def test_connection(
    engine: str,
    api_key: str,
    session: aiohttp.ClientSession | None = None,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Hit the named engine with a single short prompt and report
    ``(ok, message)``. Mirrors ``semrush.client.test_connection``: one cheap
    probe, never raises. Reuses the per-engine probe used by
    ``fetch_share_of_voice`` — ``ok`` is True only when it parses a real
    reply (``measured``), not on an HTTP/network failure."""
    if not api_key:
        return False, "No API key set."
    probe = _PROBES.get(engine)
    if probe is None:
        return False, f"Unknown engine: {engine!r}."
    own_session = session is None
    active = session if session is not None else aiohttp.ClientSession()
    try:
        answer = await probe(_TEST_PROMPT, api_key, active, timeout_seconds)
    finally:
        if own_session:
            await active.close()
    if answer.measured:
        return True, "ok"
    return False, "request failed (HTTP or network error)."


async def _sample_engine(
    engine: str,
    prompts: tuple[str, ...],
    api_key: str,
    brand: str,
    host: str,
    competitors: tuple[str, ...],
    session: aiohttp.ClientSession,
    timeout: int,
) -> EngineShareOfVoice:
    """Sample every prompt against one engine and score the answers. A
    per-prompt probe failure just yields an unmeasured ``EngineAnswer``,
    excluded from the mention/citation/sentiment tally below."""
    probe = _PROBES[engine]
    answers = [await probe(prompt, api_key, session, timeout) for prompt in prompts]
    measured = [answer for answer in answers if answer.measured]
    if not measured:
        return EngineShareOfVoice(engine=engine, prompts_sampled=len(prompts))
    mentioning = [answer for answer in measured if mentions_brand(answer.text, brand)]
    citing = [answer for answer in measured if cites_domain(answer, host)]
    competitor_hits = count_competitor_mentions([answer.text for answer in measured], competitors)
    sentiment = sentiment_label(" ".join(answer.text for answer in mentioning)) if mentioning else "neutral"
    return EngineShareOfVoice(
        engine=engine,
        prompts_sampled=len(prompts),
        mention_count=len(mentioning),
        citation_count=len(citing),
        sentiment=sentiment,
        competitor_mention_count=competitor_hits,
        measured=True,
    )


def _history_stats(engine: EngineShareOfVoice) -> dict[str, int]:
    return {"mentions": engine.mention_count, "citations": engine.citation_count, "prompts": engine.prompts_sampled}


def _keyed_engines() -> dict[str, str]:
    keys = {engine: resolve_api_key(engine) for engine in _ENGINES}
    return {engine: key for engine, key in keys.items() if key}


async def fetch_share_of_voice(
    host: str,
    brand: str,
    session: aiohttp.ClientSession | None = None,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
) -> ShareOfVoiceReport:
    """Sample the standard prompt set against every keyed engine and score
    the results. Returns an unmeasured report — with ZERO network calls —
    when the feature is off, the host/brand can't be derived, or no engine
    has a key. A host is sampled at most once per app session (the signal is
    host-level and off-page; every page of a crawl reuses the same report).
    Never raises."""
    host = (host or "").strip().lower()
    brand = (brand or "").strip()
    if not _enabled() or not host or not brand:
        return ShareOfVoiceReport(host=host, brand=brand)
    keys = _keyed_engines()
    if not keys:
        return ShareOfVoiceReport(host=host, brand=brand)
    memoized = _REPORT_MEMO.get(host)
    if memoized is not None:
        return memoized

    prompts = build_prompts(brand)
    competitors = _competitors()
    own_session = session is None
    active = session if session is not None else aiohttp.ClientSession()
    try:
        engines = tuple(
            [
                await _sample_engine(engine, prompts, api_key, brand, host, competitors, active, timeout_seconds)
                for engine, api_key in keys.items()
            ]
        )
    finally:
        if own_session:
            await active.close()

    stats = {engine.engine: _history_stats(engine) for engine in engines if engine.measured}
    if stats:
        record_point(host, stats)
    report = ShareOfVoiceReport(host=host, brand=brand, engines=engines, measured=True)
    _REPORT_MEMO[host] = report
    return report


__all__ = [
    "OPENAI_MODEL",
    "fetch_share_of_voice",
    "probe_gemini",
    "probe_openai",
    "probe_perplexity",
    "resolve_api_key",
    "test_connection",
]
