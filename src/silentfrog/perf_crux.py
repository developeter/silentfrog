"""CrUX real-user CWV field data via PageSpeed Insights (v1.1 N1).

Companion to ``perf_vitals.py``. ``perf_vitals`` measures the page
locally; this module pulls Google's CrUX P75 measurements (real
Chrome user origin/page-level data) over the free PageSpeed Insights
API.

The free tier supports ~25,000 requests/day without an API key and
much more with one. We aggressively cache responses for 24h per URL
so a sitemap-level audit doesn't hammer the API.

Failure modes (all degrade to ``has_field_data=False``):

- API key absent and PSI rate-limits the anonymous request
- Network error / timeout
- URL has no field data (low-traffic origin)
- PSI response missing the ``loadingExperience`` block

This module never raises; the caller treats ``CruxData`` with
``has_field_data=False`` as a "not measured" signal that emits ``info``
status rows.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import ClientTimeout

_PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_DEFAULT_TIMEOUT_SECONDS = 12
_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h per the plan §N1


@dataclass(frozen=True)
class CruxData:
    """CrUX P75 metrics + metadata about why field data is or isn't present."""

    lcp_p75_ms: float | None = None
    inp_p75_ms: float | None = None
    cls_p75: float | None = None
    has_field_data: bool = False
    reason: str = ""

    @classmethod
    def empty(cls, reason: str = "") -> CruxData:
        return cls(reason=reason)

    @classmethod
    def from_raw(cls, value: Any) -> CruxData:
        if not isinstance(value, dict):
            return cls.empty()

        def _opt_float(raw: Any) -> float | None:
            if raw is None or raw == "":
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None

        return cls(
            lcp_p75_ms=_opt_float(value.get("lcp_p75_ms")),
            inp_p75_ms=_opt_float(value.get("inp_p75_ms")),
            cls_p75=_opt_float(value.get("cls_p75")),
            has_field_data=bool(value.get("has_field_data", False)),
            reason=str(value.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lcp_p75_ms": self.lcp_p75_ms,
            "inp_p75_ms": self.inp_p75_ms,
            "cls_p75": self.cls_p75,
            "has_field_data": self.has_field_data,
            "reason": self.reason,
        }


def _cache_dir() -> Path:
    override = os.environ.get("SILENTFROG_DATA_DIR", "").strip()
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Silentfrog"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "silentfrog"
    return base / "crux_cache"


def _cache_key(url: str) -> str:
    # Stable, filename-safe.
    safe = (
        url.replace("://", "__")
        .replace("/", "_")
        .replace(":", "_")
        .replace("?", "_")
        .replace("&", "_")
        .replace("=", "_")
    )[:160]
    return safe


def _read_cache(url: str) -> CruxData | None:
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
    return CruxData.from_raw(payload)


def _write_cache(url: str, data: CruxData) -> None:
    try:
        directory = _cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{_cache_key(url)}.json"
        path.write_text(json.dumps(data.to_dict()), encoding="utf-8")
    except Exception:
        # Cache failures are non-fatal; the next call simply re-fetches.
        return


def _parse_psi_response(raw: Any) -> CruxData:
    if not isinstance(raw, dict):
        return CruxData.empty("PSI returned non-dict body")
    loading = raw.get("loadingExperience")
    if not isinstance(loading, dict):
        return CruxData.empty("PSI response missing loadingExperience")
    metrics = loading.get("metrics")
    if not isinstance(metrics, dict):
        return CruxData.empty("loadingExperience.metrics missing")

    def _p75(metric_name: str) -> float | None:
        block = metrics.get(metric_name)
        if not isinstance(block, dict):
            return None
        try:
            return float(block.get("percentile", 0))
        except (TypeError, ValueError):
            return None

    lcp = _p75("LARGEST_CONTENTFUL_PAINT_MS")
    inp = _p75("INTERACTION_TO_NEXT_PAINT")
    cls = _p75("CUMULATIVE_LAYOUT_SHIFT_SCORE")
    # CrUX returns CLS multiplied by 100; the public Core Web Vitals
    # threshold (0.1) is on the unscaled value. Reverse here.
    if cls is not None:
        cls = cls / 100.0
    has_data = any(value is not None for value in (lcp, inp, cls))
    if not has_data:
        return CruxData.empty("CrUX P75 fields all absent — likely low-traffic URL")
    return CruxData(
        lcp_p75_ms=lcp,
        inp_p75_ms=inp,
        cls_p75=cls,
        has_field_data=True,
    )


async def fetch_crux(
    url: str,
    api_key: str | None = None,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    session: aiohttp.ClientSession | None = None,
) -> CruxData:
    """Pull CrUX P75 metrics for ``url``.

    Order of operations:
    1. Check the 24h cache; return immediately on hit.
    2. GET PSI with ``strategy=mobile`` and ``category=performance``.
    3. Parse ``loadingExperience.metrics``.
    4. Write the result (positive or negative) to the cache.

    Never raises. On error returns ``CruxData(has_field_data=False)``
    with a populated ``reason`` field. The caller treats this as a
    "not measured" signal (status=info).
    """
    if not url or not url.startswith(("http://", "https://")):
        return CruxData.empty("URL not absolute http(s)")

    cached = _read_cache(url)
    if cached is not None:
        return cached

    params: dict[str, str] = {
        "url": url,
        "strategy": "mobile",
        "category": "performance",
    }
    if api_key:
        params["key"] = api_key

    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    try:
        async with session.get(
            _PSI_ENDPOINT,
            params=params,
            timeout=ClientTimeout(total=timeout_seconds),
        ) as response:
            if response.status == 429:
                result = CruxData.empty("PSI rate-limited (HTTP 429)")
                _write_cache(url, result)
                return result
            if response.status >= 400:
                result = CruxData.empty(f"PSI returned HTTP {response.status}")
                _write_cache(url, result)
                return result
            try:
                body = await response.json(content_type=None)
            except Exception as exc:
                return CruxData.empty(f"PSI body decode failed: {type(exc).__name__}")
    except Exception as exc:
        # Don't poison the cache on transient network failures so the
        # next attempt retries.
        return CruxData.empty(f"PSI request failed: {type(exc).__name__}")
    finally:
        if own_session and session is not None:
            await session.close()

    result = _parse_psi_response(body)
    _write_cache(url, result)
    return result


__all__ = [
    "CruxData",
    "fetch_crux",
]
