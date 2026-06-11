"""Scrapling escalation backends (v2.0 V1, optional).

Two backends layered above aiohttp, used only when the user opts into
stealth AND the base path looks blocked:

- ``ScraplingTlsBackend`` — ``scrapling.Fetcher`` (curl_cffi TLS
  fingerprint impersonation, HTTP/3). Fast.
- ``ScraplingStealthBackend`` — ``scrapling.StealthyFetcher`` (a real
  browser that solves Cloudflare Turnstile). Slow.

Both lazy-import ``scrapling`` so the install base needs nothing. The
sync Scrapling calls run in a worker thread to stay async-friendly. A
``fetcher`` may be injected for tests so we never need the heavy real
dependency in CI.
"""

from __future__ import annotations

import asyncio
import importlib.util
from typing import Any

from .types import FetchRequest, FetchResult


def _coerce_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        return value
    return ""


def _first_text(resp: Any, names: tuple[str, ...]) -> str:
    for name in names:
        text = _coerce_text(getattr(resp, name, ""))
        if text:
            return text
    return ""


def _int_attr(resp: Any, name: str) -> int:
    try:
        return int(getattr(resp, name, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _headers_dict(resp: Any) -> dict[str, str]:
    raw = getattr(resp, "headers", None)
    if hasattr(raw, "items"):
        return {str(k): str(v) for k, v in raw.items()}
    return {}


def _to_result(resp: Any, backend: str, request_url: str) -> FetchResult:
    return FetchResult(
        body=_first_text(resp, ("body", "html_content", "html", "content", "text")),
        status=_int_attr(resp, "status"),
        final_url=_first_text(resp, ("url", "final_url")) or request_url,
        headers=_headers_dict(resp),
        backend=backend,
    )


class _ScraplingBase:
    name = "scrapling"
    _call_attr = "get"

    def __init__(self, fetcher: Any | None = None) -> None:
        self._injected = fetcher

    def available(self) -> bool:
        if self._injected is not None:
            return True
        return importlib.util.find_spec("scrapling") is not None

    def _resolve_fetcher(self) -> Any:
        if self._injected is not None:
            return self._injected
        from scrapling.fetchers import Fetcher, StealthyFetcher  # lazy, optional

        return self._select(Fetcher, StealthyFetcher)

    def _select(self, fetcher: Any, stealthy: Any) -> Any:  # overridden
        raise NotImplementedError

    async def fetch(self, request: FetchRequest) -> FetchResult:
        fetcher = self._resolve_fetcher()
        call = getattr(fetcher, self._call_attr)
        try:
            resp = await asyncio.to_thread(call, request.url)
        except Exception as exc:  # noqa: BLE001 — any backend error degrades, never raises
            return FetchResult(
                body="",
                status=0,
                final_url=request.url,
                backend=self.name,
                error=f"{type(exc).__name__}: {exc}",
            )
        return _to_result(resp, self.name, request.url)


class ScraplingTlsBackend(_ScraplingBase):
    name = "scrapling-tls"
    _call_attr = "get"

    def _select(self, fetcher: Any, stealthy: Any) -> Any:
        return fetcher


class ScraplingStealthBackend(_ScraplingBase):
    name = "scrapling-stealth"
    _call_attr = "fetch"

    def _select(self, fetcher: Any, stealthy: Any) -> Any:
        return stealthy


__all__ = ["ScraplingStealthBackend", "ScraplingTlsBackend"]
