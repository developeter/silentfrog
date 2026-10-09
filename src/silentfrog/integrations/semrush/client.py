"""Semrush Analytics API v3 client (v2.0 V17, optional + off by default).

The Semrush API is NOT JSON — it returns semicolon-separated CSV text
(first line = headers). On error the body is a single line like
``ERROR 120 :: WRONG KEY - ID PAIR`` (the numeric code is optional). Every
parser is tolerant and never raises; the client
degrades to ``SemrushMetrics(measured=False)`` on an empty key, an
exhausted budget, an HTTP error, or an unparseable body.

A full overview is up to two metered calls (domain_ranks +
backlinks_overview); each counts against the daily budget. Responses are
cached per registrable domain for 24h via the shared ``_psi_cache`` disk
cache so a whole-site crawl makes ~1-2 calls per domain, not per URL.

The never-raise HTTP shape mirrors ``perf_crux.fetch_crux`` /
``ai_citations``. The API-key resolution mirrors the lazy keyring wrapper
in ``integrations.google.oauth`` (keyring first, env fallback).
"""

from __future__ import annotations

import os
import re
from typing import Any

import aiohttp
from aiohttp import ClientTimeout

from ..._psi_cache import read_cache, write_cache
from ..single_flight import single_flight
from .budget import record_call, remaining
from .types import SemrushMetrics

_BASE_URL = "https://api.semrush.com/"
_DEFAULT_TIMEOUT_SECONDS = 15
_CACHE_SUBDIR = "semrush_cache"
_DATABASE = "us"
_KEYRING_SERVICE = "silentfrog-semrush"

_DOMAIN_RANKS_COLUMNS = "Db,Dn,Rk,Or,Ot,Oc,Ad,At,Ac"
_BACKLINKS_COLUMNS = "ascore,total,domains_num"

# ``ERROR 120 :: WRONG KEY - ID PAIR`` / ``ERROR :: ...``: the numeric code is
# optional, so a plain ``startswith("ERROR ::")`` misses the coded form (INT-9).
_ERROR_RE = re.compile(r"^\s*ERROR\b\s*(?P<code>\d+)?\s*::\s*(?P<message>.*)$", re.IGNORECASE)


def _keyring() -> Any:
    import keyring  # lazy: base dep, but keep module import light

    return keyring


def resolve_api_key() -> str:
    """Keyring (``silentfrog-semrush``/``api_key``) first, env fallback.

    keyring is a base dependency but stays lazy-imported (and degrades to
    env-only if it's ever unavailable at runtime), mirroring
    ``integrations.google.oauth``.
    """
    try:
        stored = _keyring().get_password(_KEYRING_SERVICE, "api_key")
        if stored:
            return str(stored).strip()
    except Exception:
        pass
    return os.environ.get("SILENTFROG_SEMRUSH_API_KEY", "").strip()


def _to_int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return 0
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _error_message(body: str) -> str:
    """``"WRONG KEY - ID PAIR (code 120)"`` for an error body, ``""`` otherwise."""
    lines = (body or "").strip().splitlines()
    match = _ERROR_RE.match(lines[0]) if lines else None
    if match is None:
        return ""
    message = match.group("message").strip() or "unknown error"
    code = match.group("code")
    return f"{message} (code {code})" if code else message


def _parse_csv(body: str) -> list[dict[str, str]]:
    """Tolerant Semrush CSV parser: split lines, split on ``;``, zip
    headers→row. Returns ``[]`` for empty input or an ``ERROR`` body.
    Never raises."""
    text = (body or "").strip()
    if not text or _error_message(text):
        return []
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    headers = [cell.strip() for cell in lines[0].split(";")]
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        cells = line.split(";")
        rows.append(
            {header: cells[index].strip() if index < len(cells) else "" for index, header in enumerate(headers)}
        )
    return rows


def _read_cache(domain: str) -> SemrushMetrics | None:
    return read_cache(_CACHE_SUBDIR, domain, SemrushMetrics.from_dict)


def _write_cache(domain: str, data: SemrushMetrics) -> None:
    write_cache(_CACHE_SUBDIR, domain, data)


async def _get_text(
    session: aiohttp.ClientSession,
    params: dict[str, str],
    timeout: int,
) -> str | None:
    """One metered GET returning the raw CSV body, or None on HTTP/network
    error. Records the call against the budget once the request is issued."""
    record_call()
    try:
        async with session.get(_BASE_URL, params=params, timeout=ClientTimeout(total=timeout)) as response:
            if response.status >= 400:
                return None
            return await response.text()
    except Exception:
        return None


async def _fetch_row(
    session: aiohttp.ClientSession,
    params: dict[str, str],
    timeout: int,
) -> tuple[dict[str, str] | None, str]:
    """One metered call -> (first CSV row or None, why it has none)."""
    body = await _get_text(session, params, timeout)
    if body is None:
        return None, "request failed (HTTP or network error)"
    rows = _parse_csv(body)
    if rows:
        return rows[0], ""
    return None, _error_message(body) or "no data returned"


async def _fetch_domain_ranks(
    session: aiohttp.ClientSession,
    domain: str,
    api_key: str,
    timeout: int,
) -> tuple[dict[str, str] | None, str]:
    params = {
        "type": "domain_ranks",
        "key": api_key,
        "domain": domain,
        "database": _DATABASE,
        "export_columns": _DOMAIN_RANKS_COLUMNS,
    }
    return await _fetch_row(session, params, timeout)


async def _fetch_backlinks(
    session: aiohttp.ClientSession,
    domain: str,
    api_key: str,
    timeout: int,
) -> tuple[dict[str, str] | None, str]:
    params = {
        "type": "backlinks_overview",
        "key": api_key,
        "target": domain,
        "target_type": "root_domain",
        "export_columns": _BACKLINKS_COLUMNS,
    }
    return await _fetch_row(session, params, timeout)


# Semrush echoes the requested column code in some responses and the
# human display name in others; accept either so the parser is robust.
_RANKS_FIELDS = {
    "organic_keywords": ("Or", "Organic Keywords"),
    "organic_traffic": ("Ot", "Organic Traffic"),
    "paid_keywords": ("Ad", "Adwords Keywords"),
    "paid_traffic": ("At", "Adwords Traffic"),
}
_BACKLINKS_FIELDS = {
    "domain_authority": ("ascore", "Authority Score"),
    "backlinks_total": ("total", "Total Backlinks"),
    "referring_domains": ("domains_num", "Referring Domains"),
}


def _pick(row: dict[str, str], candidates: tuple[str, ...]) -> int:
    for key in candidates:
        if key in row:
            return _to_int(row[key])
    return 0


def _build_metrics(ranks: dict[str, str] | None, backlinks: dict[str, str] | None) -> SemrushMetrics:
    ranks = ranks or {}
    backlinks = backlinks or {}
    return SemrushMetrics(
        domain_authority=_pick(backlinks, _BACKLINKS_FIELDS["domain_authority"]),
        organic_keywords=_pick(ranks, _RANKS_FIELDS["organic_keywords"]),
        organic_traffic=_pick(ranks, _RANKS_FIELDS["organic_traffic"]),
        backlinks_total=_pick(backlinks, _BACKLINKS_FIELDS["backlinks_total"]),
        referring_domains=_pick(backlinks, _BACKLINKS_FIELDS["referring_domains"]),
        paid_keywords=_pick(ranks, _RANKS_FIELDS["paid_keywords"]),
        paid_traffic=_pick(ranks, _RANKS_FIELDS["paid_traffic"]),
        measured=True,
    )


async def _overview_uncached(
    domain: str,
    api_key: str,
    max_calls: int,
    session: aiohttp.ClientSession | None,
    timeout_seconds: int,
) -> SemrushMetrics:
    """Cache check, budget check, the two metered calls and the cache write,
    as one unit so concurrent callers for a domain cannot interleave them."""
    cached = _read_cache(domain)
    if cached is not None:
        return cached

    # Both calls of a full overview must fit the remaining budget.
    if remaining(max_calls) < 2:
        return SemrushMetrics.unavailable(f"Daily Semrush call cap reached ({max_calls}); a domain overview needs 2.")

    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    try:
        ranks, ranks_error = await _fetch_domain_ranks(session, domain, api_key, timeout_seconds)
        backlinks, backlinks_error = await _fetch_backlinks(session, domain, api_key, timeout_seconds)
    finally:
        if own_session and session is not None:
            await session.close()

    if ranks is None and backlinks is None:
        return SemrushMetrics.unavailable(f"Semrush {ranks_error or backlinks_error}.")
    result = _build_metrics(ranks, backlinks)
    _write_cache(domain, result)
    return result


async def fetch_domain_overview(
    domain: str,
    api_key: str,
    max_calls: int,
    session: aiohttp.ClientSession | None = None,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
) -> SemrushMetrics:
    """Domain overview = domain_ranks + backlinks_overview (up to 2 metered
    calls). Cache-first per domain, budget-guarded, and single-flight per
    (loop, domain) so a crawl's concurrent pages spend one overview, not one
    each (INT-5). Returns an unmeasured ``SemrushMetrics`` (with a ``reason``)
    on empty key, exhausted budget, or any HTTP/parse/API error. Never raises."""
    domain = (domain or "").strip().lower()
    if not domain or not api_key:
        return SemrushMetrics.empty()
    return await single_flight(
        ("semrush", domain),
        lambda: _overview_uncached(domain, api_key, max_calls, session, timeout_seconds),
    )


async def test_connection(
    api_key: str,
    session: aiohttp.ClientSession | None = None,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    max_calls: int | None = None,
) -> tuple[bool, str]:
    """Hit a cheap ``domain_ranks`` endpoint and report ``(ok, message)``.

    ``ok`` is True when the body parses and is not an ``ERROR`` line. The test
    is one metered call, so with ``max_calls`` set it is refused once the
    daily budget is spent (INT-7). Never raises."""
    if not api_key:
        return False, "No API key set."
    if max_calls is not None and remaining(max_calls) < 1:
        return False, f"Daily Semrush call cap reached ({max_calls}); try again tomorrow or raise the cap."
    params = {
        "type": "domain_ranks",
        "key": api_key,
        "domain": "semrush.com",
        "database": _DATABASE,
        "export_columns": _DOMAIN_RANKS_COLUMNS,
    }
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    try:
        body = await _get_text(session, params, timeout_seconds)
    finally:
        if own_session and session is not None:
            await session.close()
    if body is None:
        return False, "Semrush request failed (HTTP or network error)."
    if _error_message(body):
        return False, body.strip()
    if not _parse_csv(body):
        return False, "Semrush returned an unrecognised response."
    return True, "Connection OK."


__all__ = [
    "SemrushMetrics",
    "fetch_domain_overview",
    "resolve_api_key",
    "test_connection",
]
