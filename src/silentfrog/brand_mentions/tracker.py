"""Brand-mention counting + local time-series (v2.0 V20).

Counts how often the site's brand shows up on the open web — Brave
web results mentioning the brand off-site (fresh signal, needs the
same ``SILENTFROG_BRAVE_API_KEY`` the AI Citations probe uses) and
Common Crawl references to the host (historical signal, keyless) —
and appends the counts to a small local JSON series per host, so
repeat audits build a trend without any SaaS.

Gating mirrors ``ai_citations``: nothing runs unless
``SILENTFROG_BRAND_MENTIONS_ENABLE`` is set, every HTTP failure
degrades to ``measured=False``, and the same-day series entry is
replaced instead of appended (an audit loop must not fabricate a
trend). No new AI-engine APIs (V20 locked decision).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
from aiohttp import ClientTimeout

from ..ai_citations import _check_common_crawl  # deliberate reuse of the V20-locked CC probe
from ..crawl_types import AiVisibilityCheck

_DEFAULT_TIMEOUT_SECONDS = 12
_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_BRAVE_RESULT_CAP = 20
_MAX_SERIES_POINTS = 52
_FILE_NAME = "brand_mentions_history.json"
_SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class BrandMentionsPayload:
    measured: bool = False
    reason: str = ""
    brand: str = ""
    host: str = ""
    brave_mentions: int = 0
    common_crawl_refs: int = 0
    # Oldest-first [{"ts": epoch_int, "brave": int, "cc": int}, ...].
    series: list[dict[str, int]] = field(default_factory=list)

    @classmethod
    def from_raw(cls, value: Any) -> BrandMentionsPayload:
        if not isinstance(value, dict):
            return cls()
        raw_series = value.get("series", [])
        series = (
            [_clean_point(point) for point in raw_series if isinstance(point, dict)]
            if isinstance(raw_series, list)
            else []
        )
        return cls(
            measured=bool(value.get("measured", False)),
            reason=str(value.get("reason", "")),
            brand=str(value.get("brand", "")),
            host=str(value.get("host", "")),
            brave_mentions=int(value.get("brave_mentions", 0) or 0),
            common_crawl_refs=int(value.get("common_crawl_refs", 0) or 0),
            series=series,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "measured": self.measured,
            "reason": self.reason,
            "brand": self.brand,
            "host": self.host,
            "brave_mentions": self.brave_mentions,
            "common_crawl_refs": self.common_crawl_refs,
            "series": [dict(point) for point in self.series],
        }


def _clean_point(point: dict[str, Any]) -> dict[str, int]:
    return {
        "ts": int(point.get("ts", 0) or 0),
        "brave": int(point.get("brave", 0) or 0),
        "cc": int(point.get("cc", 0) or 0),
    }


def _enabled() -> bool:
    raw = os.environ.get("SILENTFROG_BRAND_MENTIONS_ENABLE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def derive_brand(url: str, og_site_name: str = "") -> str:
    """The brand to search for: og:site_name, else the domain stem."""
    site_name = (og_site_name or "").strip()
    if site_name:
        return site_name
    host = urlparse(url or "").netloc.split(":")[0]
    if not host:
        return ""
    parts = [part for part in host.split(".") if part and part != "www"]
    return parts[0].capitalize() if parts else ""


# --- history store (score_history.py pattern: never raises) ------------------


def _data_dir() -> Path:
    override = os.environ.get("SILENTFROG_DATA_DIR", "").strip()
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Silentfrog"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "silentfrog"


def _read_history() -> dict[str, list[dict[str, int]]]:
    path = _data_dir() / _FILE_NAME
    if not path.is_file():
        return {}
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, list[dict[str, int]]] = {}
    for host, points in raw.items():
        if isinstance(host, str) and isinstance(points, list):
            cleaned[host] = [_clean_point(point) for point in points if isinstance(point, dict)]
    return cleaned


def _write_history(data: dict[str, list[dict[str, int]]]) -> None:
    try:
        path = _data_dir() / _FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return


def record_point(host: str, brave: int, cc: int, now: float | None = None) -> list[dict[str, int]]:
    """Append (or same-day replace) a point; returns the host's series."""
    if not host:
        return []
    ts = int(now if now is not None else time.time())
    data = _read_history()
    series = data.get(host, [])
    if series and series[-1]["ts"] // _SECONDS_PER_DAY == ts // _SECONDS_PER_DAY:
        series = series[:-1]
    series.append({"ts": ts, "brave": int(brave), "cc": int(cc)})
    data[host] = series[-_MAX_SERIES_POINTS:]
    _write_history(data)
    return data[host]


# --- probes -------------------------------------------------------------------


async def _count_brave_mentions(
    brand: str, host: str, api_key: str, session: aiohttp.ClientSession, timeout: int
) -> tuple[int, str]:
    """Off-site Brave web results that mention the brand; (count, reason)."""
    params = {"q": f'"{brand}" -site:{host}', "count": str(_BRAVE_RESULT_CAP)}
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    try:
        async with session.get(
            _BRAVE_ENDPOINT, params=params, headers=headers, timeout=ClientTimeout(total=timeout)
        ) as response:
            if response.status >= 400:
                return 0, f"Brave returned HTTP {response.status}"
            body = await response.json(content_type=None)
    except Exception as exc:
        return 0, f"Brave request failed: {type(exc).__name__}"
    web = body.get("web") if isinstance(body, dict) else None
    results = web.get("results") if isinstance(web, dict) else None
    if not isinstance(results, list):
        return 0, "Brave response missing web.results"
    return len(results), ""


async def fetch_brand_mentions(
    url: str,
    og_site_name: str = "",
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    session: aiohttp.ClientSession | None = None,
) -> BrandMentionsPayload:
    """Count brand mentions and extend the local series. Never raises."""
    if not _enabled():
        return BrandMentionsPayload(reason="SILENTFROG_BRAND_MENTIONS_ENABLE not set")
    host = urlparse(url or "").netloc.split(":")[0]
    brand = derive_brand(url, og_site_name)
    if not host or not brand:
        return BrandMentionsPayload(reason="URL has no host to derive a brand from")
    api_key = os.environ.get("SILENTFROG_BRAVE_API_KEY", "").strip()

    own_session = session is None
    active = session if session is not None else aiohttp.ClientSession()
    try:
        brave_count, brave_reason = (0, "no API key")
        if api_key:
            brave_count, brave_reason = await _count_brave_mentions(brand, host, api_key, active, timeout_seconds)
        cc_count, cc_reason = await _check_common_crawl(f"https://{host}/", active, timeout_seconds)
    finally:
        if own_session:
            await active.close()

    measured = (bool(api_key) and not brave_reason) or not cc_reason
    if not measured:
        reasons = "; ".join(text for text in (f"Brave: {brave_reason}", f"Common Crawl: {cc_reason}") if text)
        return BrandMentionsPayload(reason=reasons, brand=brand, host=host)
    series = record_point(host, brave_count, cc_count)
    reason = f"Brave: {brave_reason}" if brave_reason else ""
    return BrandMentionsPayload(
        measured=True,
        reason=reason,
        brand=brand,
        host=host,
        brave_mentions=brave_count,
        common_crawl_refs=cc_count,
        series=series,
    )


# --- checks -------------------------------------------------------------------

_VISIBILITY_RECOMMENDATION = (
    "Grow authentic off-site mentions (PR, directories, communities). Counts read Brave's index "
    f"and cap at {_BRAVE_RESULT_CAP} results; absence is informational, never a penalty."
)
_TREND_RECOMMENDATION = (
    "Re-audit periodically: each audited day appends one point to the local series, so the trend "
    "reflects your own measurement cadence. A drop can also mean index churn — verify before reacting."
)


def _trend_check(payload: BrandMentionsPayload) -> AiVisibilityCheck:
    if len(payload.series) < 2:
        return _check(
            "brand_mentions_trend",
            "info",
            f"Only {len(payload.series)} measurement(s) recorded for {payload.host} — "
            "a trend needs at least two audited days.",
            _TREND_RECOMMENDATION,
        )
    previous, latest = payload.series[-2], payload.series[-1]
    delta = (latest["brave"] + latest["cc"]) - (previous["brave"] + previous["cc"])
    status = "warning" if delta < 0 else "good"
    direction = "down" if delta < 0 else ("up" if delta > 0 else "flat")
    return _check(
        "brand_mentions_trend",
        status,
        f"Brand-mention trend for {payload.brand}: {direction} ({delta:+d} vs the previous "
        f"measurement; {len(payload.series)} points recorded).",
        _TREND_RECOMMENDATION,
    )


def _check(key: str, status: str, details: str, recommendation: str) -> AiVisibilityCheck:
    titles = {
        "brand_mentions_visibility": "The brand is mentioned on the open web",
        "brand_mentions_trend": "Brand mentions are stable or growing over time",
    }
    return AiVisibilityCheck(
        area="AI Citations",
        check=titles[key],
        status=status,
        details=details,
        recommendation=recommendation,
        key=key,
    )


def build_brand_mention_checks(payload: BrandMentionsPayload) -> list[AiVisibilityCheck]:
    """Two AI-Citations rows — empty (not emitted) when unmeasured."""
    if not payload.measured:
        return []
    visibility_status = "good" if (payload.brave_mentions > 0 or payload.common_crawl_refs > 0) else "info"
    visibility = _check(
        "brand_mentions_visibility",
        visibility_status,
        f"Off-site Brave results mentioning '{payload.brand}': {payload.brave_mentions} "
        f"(cap {_BRAVE_RESULT_CAP}); Common Crawl references to {payload.host}: "
        f"{payload.common_crawl_refs}.",
        _VISIBILITY_RECOMMENDATION,
    )
    return [visibility, _trend_check(payload)]


__all__ = [
    "BrandMentionsPayload",
    "build_brand_mention_checks",
    "derive_brand",
    "fetch_brand_mentions",
    "record_point",
]
