"""Lighthouse category scores via PageSpeed Insights (v2.0 V14).

The same ``runPagespeed`` endpoint ``perf_crux`` uses for CrUX field
data also returns a full Lighthouse lab run when categories are
requested. This module pulls the category scores (0-100) and caches
them 24h per URL through the shared PSI cache.

A Lighthouse lab run is slow (~10-30s/URL) and rate-limited, so it is
never wired into the bulk crawl — it is an on-demand, single-page action
(the GUI "Run Lighthouse" button). Never raises; any failure returns
``LighthouseScores(measured=False)``, which the checks layer renders as
``info`` (§1.5), never a penalty.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp
from aiohttp import ClientTimeout

from ..._psi_cache import read_cache, write_cache

_PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_DEFAULT_TIMEOUT_SECONDS = 60  # lab runs are slow; well above the CrUX 12s
_CACHE_SUBDIR = "lighthouse_cache"

# PSI category key -> LighthouseScores field. "best-practices" is hyphenated
# in the API; "pwa" was retired in Lighthouse 12 so we parse it if present
# but never request it (requesting a removed category 400s).
_CATEGORY_FIELDS = {
    "performance": "performance",
    "accessibility": "accessibility",
    "best-practices": "best_practices",
    "seo": "seo",
    "pwa": "pwa",
}
_REQUEST_CATEGORIES = ("performance", "accessibility", "best-practices", "seo")


@dataclass(frozen=True)
class LighthouseScores:
    performance: int = 0
    accessibility: int = 0
    best_practices: int = 0
    seo: int = 0
    pwa: int = 0
    fetched_at: str = ""
    measured: bool = False

    @classmethod
    def from_dict(cls, value: Any) -> LighthouseScores:
        if not isinstance(value, dict):
            return cls()

        def _score(name: str) -> int:
            try:
                return int(value.get(name, 0) or 0)
            except (TypeError, ValueError):
                return 0

        return cls(
            performance=_score("performance"),
            accessibility=_score("accessibility"),
            best_practices=_score("best_practices"),
            seo=_score("seo"),
            pwa=_score("pwa"),
            fetched_at=str(value.get("fetched_at", "")),
            measured=bool(value.get("measured", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "performance": self.performance,
            "accessibility": self.accessibility,
            "best_practices": self.best_practices,
            "seo": self.seo,
            "pwa": self.pwa,
            "fetched_at": self.fetched_at,
            "measured": self.measured,
        }


def _category_score(categories: dict[str, Any], key: str) -> int:
    block = categories.get(key)
    if not isinstance(block, dict):
        return 0
    raw_score = block.get("score")
    if raw_score is None:
        return 0
    try:
        return round(float(raw_score) * 100)
    except (TypeError, ValueError):
        return 0


def _parse_lighthouse(raw: Any) -> LighthouseScores:
    result = raw.get("lighthouseResult") if isinstance(raw, dict) else None
    if not isinstance(result, dict):
        return LighthouseScores()
    categories = result.get("categories")
    if not isinstance(categories, dict):
        return LighthouseScores()
    scores = {field: _category_score(categories, key) for key, field in _CATEGORY_FIELDS.items()}
    return LighthouseScores(fetched_at=str(result.get("fetchTime", "")), measured=True, **scores)


def _request_params(url: str, api_key: str) -> list[tuple[str, str]]:
    params = [("url", url), ("strategy", "mobile")]
    params += [("category", category) for category in _REQUEST_CATEGORIES]
    if api_key:
        params.append(("key", api_key))
    return params


async def _request_psi(
    url: str, api_key: str, timeout_seconds: int, session: aiohttp.ClientSession | None
) -> Any | None:
    params = _request_params(url, api_key)
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    try:
        async with session.get(_PSI_ENDPOINT, params=params, timeout=ClientTimeout(total=timeout_seconds)) as response:
            if response.status >= 400:
                return None
            return await response.json(content_type=None)
    except Exception:
        return None
    finally:
        if own_session and session is not None:
            await session.close()


async def fetch_lighthouse(
    url: str,
    api_key: str = "",
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    session: aiohttp.ClientSession | None = None,
) -> LighthouseScores:
    """Run Lighthouse for ``url`` via PSI; return 0-100 category scores.

    Cache-first (24h). Never raises — any failure yields
    ``LighthouseScores(measured=False)`` (status=info downstream).
    """
    if not url or not url.startswith(("http://", "https://")):
        return LighthouseScores()

    cached = read_cache(_CACHE_SUBDIR, url, LighthouseScores.from_dict)
    if cached is not None:
        return cached

    body = await _request_psi(url, api_key, timeout_seconds, session)
    result = _parse_lighthouse(body)
    if result.measured:
        write_cache(_CACHE_SUBDIR, url, result)
    return result


__all__ = ["LighthouseScores", "fetch_lighthouse"]
