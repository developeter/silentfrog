"""Fetcher strategy — escalate past WAF blocks on opt-in (v2.0 V1).

The base path is always aiohttp (zero deps, fast). When the user has
enabled stealth AND the base result looks blocked (0/403/429/503), the
strategy escalates through the available Scrapling backends in order:
TLS impersonation first, then a real browser. If nothing is installed or
nothing unblocks, the best result seen is returned — the call never
raises.
"""

from __future__ import annotations

from collections.abc import Sequence

from .aiohttp_backend import AiohttpBackend
from .scrapling_backend import ScraplingStealthBackend, ScraplingTlsBackend
from .types import FetchBackend, FetchOptions, FetchRequest, FetchResult


def default_backends() -> list[FetchBackend]:
    """Base aiohttp + the two escalation backends, in escalation order."""
    return [AiohttpBackend(), ScraplingTlsBackend(), ScraplingStealthBackend()]


class FetchStrategy:
    def __init__(
        self,
        options: FetchOptions | None = None,
        backends: Sequence[FetchBackend] | None = None,
    ) -> None:
        self._options = options or FetchOptions()
        self._backends = list(backends) if backends is not None else default_backends()

    async def fetch(self, request: FetchRequest) -> FetchResult:
        base = self._backends[0]
        result = await base.fetch(request)
        if not self._options.use_stealth or not self._escalating(result):
            return result
        return await self._escalate(request, result)

    def _escalating(self, result: FetchResult) -> bool:
        return result.looks_blocked(self._options.escalate_statuses)

    async def _escalate(self, request: FetchRequest, base_result: FetchResult) -> FetchResult:
        best = base_result
        for backend in self._backends[1:]:
            if not backend.available():
                continue
            escalated = await backend.fetch(request)
            if not self._escalating(escalated):
                return escalated
            best = escalated
        return best


__all__ = ["FetchStrategy", "default_backends"]
