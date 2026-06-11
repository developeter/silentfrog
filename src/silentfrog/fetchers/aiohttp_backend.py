"""Default fetcher backend — wraps the existing aiohttp path (v2.0 V1).

Always available, zero new dependencies. This is the fast base path; the
strategy only escalates to stealth backends when this returns a blocked
status and the user has opted in.
"""

from __future__ import annotations

from ..http_client import fetch_page
from .types import FetchRequest, FetchResult


class AiohttpBackend:
    name = "aiohttp"

    def available(self) -> bool:
        return True

    async def fetch(self, request: FetchRequest) -> FetchResult:
        resp = await fetch_page(request.url, request.timeout, headers=request.headers)
        return FetchResult(
            body=resp.body,
            status=resp.status,
            final_url=resp.url,
            headers=resp.headers,
            ttfb_ms=resp.ttfb_ms,
            total_ms=resp.total_ms,
            backend=self.name,
        )


__all__ = ["AiohttpBackend"]
