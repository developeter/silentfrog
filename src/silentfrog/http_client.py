from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Optional

import aiohttp  # type: ignore[import]  # aiohttp stubs missing
from aiohttp import ClientSession, ClientTimeout  # type: ignore[import]  # aiohttp stubs missing

from .crawl_options import DEFAULT_USER_AGENT
from .transport import open_crawl_session


@dataclass
class HttpResponse:
    body: str
    status: int
    url: str
    headers: dict[str, str]
    ttfb_ms: float
    total_ms: float


async def fetch(session: aiohttp.ClientSession, url: str, timeout: int) -> HttpResponse:
    try:
        start = perf_counter()
        async with session.get(
            url,
            timeout=ClientTimeout(total=timeout),
            allow_redirects=True,
        ) as response:
            ttfb = (perf_counter() - start) * 1000
            text = await response.text("utf-8", errors="ignore")
            total = (perf_counter() - start) * 1000
            return HttpResponse(
                body=text,
                status=response.status,
                url=str(response.url),
                headers=dict(response.headers),
                ttfb_ms=ttfb,
                total_ms=total,
            )
    except Exception:
        return HttpResponse("", 0, url, {}, 0.0, 0.0)


async def fetch_page(url: str, timeout: int = 10, headers: Optional[dict[str, str]] = None) -> HttpResponse:
    base_headers = headers or {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with open_crawl_session(headers=base_headers) as session:
        return await fetch(session, url, timeout)


async def fetch_bytes(session: aiohttp.ClientSession, url: str, timeout: int) -> bytes:
    async with session.get(url, timeout=ClientTimeout(total=timeout)) as response:
        return await response.read()


async def head_status(session: ClientSession, url: str, timeout: int) -> int:
    try:
        async with session.head(url, timeout=ClientTimeout(total=timeout)) as response:
            return response.status
    except Exception:
        return 0


async def fetch_text(url: str, timeout: int = 5) -> Optional[str]:
    try:
        async with open_crawl_session() as session:
            async with session.get(url, timeout=ClientTimeout(total=timeout)) as response:
                return await response.text()
    except Exception:
        return None
