"""Fetcher strategy package (v2.0 V1).

Public surface:

- ``FetchStrategy`` / ``default_backends`` — orchestration.
- ``FetchRequest`` / ``FetchResult`` / ``FetchOptions`` — typed contract.
- ``AiohttpBackend`` — the always-available base backend.
- ``ScraplingTlsBackend`` / ``ScraplingStealthBackend`` — optional
  escalation backends (lazy-import ``scrapling``).
- ``fetch_via_strategy`` — convenience used by the crawl orchestrator.
"""

from __future__ import annotations

from .aiohttp_backend import AiohttpBackend
from .scrapling_backend import ScraplingStealthBackend, ScraplingTlsBackend
from .strategy import FetchStrategy, default_backends
from .types import (
    ESCALATE_STATUSES,
    FetchBackend,
    FetchOptions,
    FetchRequest,
    FetchResult,
)


async def fetch_via_strategy(
    url: str,
    timeout: int = 15,
    headers: dict[str, str] | None = None,
    *,
    use_stealth: bool = False,
) -> FetchResult:
    """One-shot helper: build a strategy and fetch a single URL."""
    strategy = FetchStrategy(FetchOptions(use_stealth=use_stealth))
    return await strategy.fetch(FetchRequest(url=url, timeout=timeout, headers=headers))


__all__ = [
    "ESCALATE_STATUSES",
    "AiohttpBackend",
    "FetchBackend",
    "FetchOptions",
    "FetchRequest",
    "FetchResult",
    "FetchStrategy",
    "ScraplingStealthBackend",
    "ScraplingTlsBackend",
    "default_backends",
    "fetch_via_strategy",
]
