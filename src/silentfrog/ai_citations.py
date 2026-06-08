"""Cross-engine AI citation tracking (v1.1 N4a).

The competitive moat: for any audited URL, report whether AI engines
actually cite it. SaaS GEO tools (Otterly, Profound, AthenaHQ) charge
$$ for this; we deliver a free local-first equivalent.

Gating:
- Module imports cleanly without any new optional extra.
- ``fetch_ai_citations`` is gated on env knobs:
  - ``SILENTFROG_AI_CITATIONS_ENABLE=1`` enables the check at all.
  - ``SILENTFROG_BRAVE_API_KEY`` enables the Brave Search probe (the
    fresh-signal source).
- All HTTP failures degrade to ``measured=False`` / ``info`` rows.
  Never raises.

In-tree HTTP cache reuses the same pattern as ``perf_crux.py`` —
24h on-disk JSON cache keyed by URL. Removed the planned
``httpx-cache`` dep per §4.5 supply-chain hygiene (smaller-maintainer
risk + simple enough to do in-house).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
from aiohttp import ClientTimeout

from .crawl_types import AiVisibilityCheck

_DEFAULT_TIMEOUT_SECONDS = 12
_CACHE_TTL_SECONDS = 24 * 60 * 60

_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_COMMON_CRAWL_ENDPOINT = "https://index.commoncrawl.org/CC-MAIN-2025-26-index"


@dataclass(frozen=True)
class AiCitationsPayload:
    """Aggregated AI citation signals for one URL."""

    brave_indexed: bool = False
    brave_summary_mentions: int = 0
    common_crawl_references: int = 0
    perplexity_likely_indexed: bool = False
    measured: bool = False
    reason: str = ""

    @classmethod
    def empty(cls, reason: str = "") -> AiCitationsPayload:
        return cls(reason=reason)

    @classmethod
    def from_raw(cls, value: Any) -> AiCitationsPayload:
        if not isinstance(value, dict):
            return cls.empty()
        return cls(
            brave_indexed=bool(value.get("brave_indexed", False)),
            brave_summary_mentions=int(value.get("brave_summary_mentions", 0) or 0),
            common_crawl_references=int(value.get("common_crawl_references", 0) or 0),
            perplexity_likely_indexed=bool(value.get("perplexity_likely_indexed", False)),
            measured=bool(value.get("measured", False)),
            reason=str(value.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "brave_indexed": self.brave_indexed,
            "brave_summary_mentions": self.brave_summary_mentions,
            "common_crawl_references": self.common_crawl_references,
            "perplexity_likely_indexed": self.perplexity_likely_indexed,
            "measured": self.measured,
            "reason": self.reason,
        }


def _enabled() -> bool:
    raw = os.environ.get("SILENTFROG_AI_CITATIONS_ENABLE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _cache_dir() -> Path:
    override = os.environ.get("SILENTFROG_DATA_DIR", "").strip()
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Silentfrog"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "silentfrog"
    return base / "ai_citations_cache"


def _cache_key(url: str) -> str:
    safe = (
        url.replace("://", "__")
        .replace("/", "_")
        .replace(":", "_")
        .replace("?", "_")
        .replace("&", "_")
        .replace("=", "_")
    )[:160]
    return safe


def _read_cache(url: str) -> AiCitationsPayload | None:
    path = _cache_dir() / f"{_cache_key(url)}.json"
    if not path.is_file():
        return None
    try:
        age = time.time() - path.stat().st_mtime
        if age > _CACHE_TTL_SECONDS:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return AiCitationsPayload.from_raw(payload)


def _write_cache(url: str, data: AiCitationsPayload) -> None:
    try:
        directory = _cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{_cache_key(url)}.json").write_text(json.dumps(data.to_dict()), encoding="utf-8")
    except Exception:
        return


async def _check_brave(url: str, api_key: str, session: aiohttp.ClientSession, timeout: int) -> tuple[bool, int, str]:
    """Probe Brave Search; returns (indexed, summary_mentions, reason)."""
    netloc = urlparse(url).netloc
    if not netloc:
        return False, 0, "URL has no netloc"
    params = {"q": f"site:{netloc}", "count": "5"}
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    try:
        async with session.get(
            _BRAVE_ENDPOINT,
            params=params,
            headers=headers,
            timeout=ClientTimeout(total=timeout),
        ) as response:
            if response.status == 429:
                return False, 0, "Brave rate-limited (HTTP 429)"
            if response.status >= 400:
                return False, 0, f"Brave returned HTTP {response.status}"
            try:
                body = await response.json(content_type=None)
            except Exception as exc:
                return False, 0, f"Brave body decode failed: {type(exc).__name__}"
    except Exception as exc:
        return False, 0, f"Brave request failed: {type(exc).__name__}"
    web = body.get("web") if isinstance(body, dict) else None
    results = web.get("results") if isinstance(web, dict) else None
    if not isinstance(results, list):
        return False, 0, "Brave response missing web.results"
    indexed = len(results) > 0
    # Count site mentions in Brave's AI summary block (if present).
    summary_block = body.get("summarizer") if isinstance(body, dict) else None
    mentions = 0
    if isinstance(summary_block, dict):
        text = json.dumps(summary_block)
        mentions = text.lower().count(netloc.lower())
    return indexed, mentions, ""


async def _check_common_crawl(url: str, session: aiohttp.ClientSession, timeout: int) -> tuple[int, str]:
    """Probe Common Crawl index; returns (reference_count, reason).

    Common Crawl's CDX servers index by URL. Returning >0 means the URL
    has been seen at least once in the most recent crawl. This is a
    lagged signal (months behind live), positioned as 'historical' in
    the row's tooltip.
    """
    params = {"url": url, "output": "json", "limit": "5"}
    try:
        async with session.get(
            _COMMON_CRAWL_ENDPOINT,
            params=params,
            timeout=ClientTimeout(total=timeout),
        ) as response:
            if response.status >= 400:
                return 0, f"Common Crawl returned HTTP {response.status}"
            body_text = await response.text()
    except Exception as exc:
        return 0, f"Common Crawl request failed: {type(exc).__name__}"
    # CDX returns one JSON object per line.
    lines = [line for line in body_text.splitlines() if line.strip()]
    return len(lines), ""


async def fetch_ai_citations(
    url: str,
    brave_api_key: str | None = None,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    session: aiohttp.ClientSession | None = None,
) -> AiCitationsPayload:
    """Pull AI citation signals for ``url``.

    Returns ``AiCitationsPayload(measured=False)`` when the feature
    is disabled OR when every probe errored. Never raises.
    """
    if not _enabled():
        return AiCitationsPayload.empty("SILENTFROG_AI_CITATIONS_ENABLE not set")
    if not url or not url.startswith(("http://", "https://")):
        return AiCitationsPayload.empty("URL not absolute http(s)")

    cached = _read_cache(url)
    if cached is not None:
        return cached

    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    try:
        brave_indexed = False
        brave_mentions = 0
        brave_reason = "no API key" if not brave_api_key else ""
        if brave_api_key:
            brave_indexed, brave_mentions, brave_reason = await _check_brave(
                url, brave_api_key, session, timeout_seconds
            )
        cc_count, cc_reason = await _check_common_crawl(url, session, timeout_seconds)
    finally:
        if own_session and session is not None:
            await session.close()

    reasons: list[str] = []
    if brave_reason:
        reasons.append(f"Brave: {brave_reason}")
    if cc_reason:
        reasons.append(f"Common Crawl: {cc_reason}")
    measured = (brave_api_key is not None and not brave_reason) or cc_reason == ""
    result = AiCitationsPayload(
        brave_indexed=brave_indexed,
        brave_summary_mentions=brave_mentions,
        common_crawl_references=cc_count,
        perplexity_likely_indexed=brave_indexed,  # Perplexity uses Bing+Brave-ish indexes
        measured=measured,
        reason="; ".join(reasons),
    )
    _write_cache(url, result)
    return result


# ---------------------------------------------------------------------------
# AI Visibility row builders
# ---------------------------------------------------------------------------

_CHECK_META: dict[str, tuple[str, str, str]] = {
    "ai_citations_brave": (
        "AI Citations",
        "Brave Search indexes the URL (used by Claude, Brave AI)",
        "Brave is Claude's primary index. If a URL isn't in Brave it's effectively invisible to "
        "Claude regardless of other SEO work. Submit the sitemap to Brave + verify indexing.",
    ),
    "ai_citations_common_crawl": (
        "AI Citations",
        "Common Crawl has historical references to the URL",
        "Common Crawl powers the training and citation paths of many open AI engines. Pages "
        "absent from Common Crawl are invisible to those engines. Note: index lags by ~3 months.",
    ),
    "ai_citations_perplexity": (
        "AI Citations",
        "Perplexity likely indexes the URL (Brave + Bing heuristic)",
        "Perplexity composes from Brave + Bing-shaped indexes. Used as a heuristic when Perplexity's "
        "own search API isn't available; Brave presence is the strongest single signal we can read.",
    ),
}


def _check(key: str, status: str, detail: str) -> AiVisibilityCheck:
    area, title, recommendation = _CHECK_META[key]
    return AiVisibilityCheck(
        area=area,
        check=title,
        status=status,
        details=detail,
        recommendation=recommendation,
        key=key,
    )


def build_ai_citations_checks(payload: AiCitationsPayload) -> list[AiVisibilityCheck]:
    """Three rows in the optional 8th 'AI Citations' area.

    All myth-friendly: when ``measured=False`` every row reports
    ``info`` and does NOT down-weight the GEO Score.
    """
    if not payload.measured:
        detail_base = "AI citation tracking not measured"
        if payload.reason:
            detail_base = f"{detail_base}: {payload.reason}"
        return [
            _check("ai_citations_brave", "info", detail_base),
            _check("ai_citations_common_crawl", "info", detail_base),
            _check("ai_citations_perplexity", "info", detail_base),
        ]
    rows = [
        _check(
            "ai_citations_brave",
            "good" if payload.brave_indexed else "warning",
            f"Brave indexed: {'yes' if payload.brave_indexed else 'no'}; "
            f"AI summary mentions: {payload.brave_summary_mentions}.",
        ),
        _check(
            "ai_citations_common_crawl",
            "good" if payload.common_crawl_references > 0 else "info",
            f"Common Crawl references: {payload.common_crawl_references}.",
        ),
        _check(
            "ai_citations_perplexity",
            "good" if payload.perplexity_likely_indexed else "info",
            f"Heuristic — Perplexity likely indexed: {'yes' if payload.perplexity_likely_indexed else 'no'}.",
        ),
    ]
    return rows


__all__ = [
    "AiCitationsPayload",
    "build_ai_citations_checks",
    "fetch_ai_citations",
]
