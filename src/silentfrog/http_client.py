from __future__ import annotations
from dataclasses import dataclass
import ssl
from typing import Optional

import aiohttp  # type: ignore
from aiohttp import ClientSession, ClientTimeout  # type: ignore


@dataclass
class HttpResponse:
    body: str
    status: int
    url: str
    headers: dict[str, str]


async def fetch(session: aiohttp.ClientSession, url: str, timeout: int) -> HttpResponse:
    try:
        async with session.get(
            url,
            timeout=ClientTimeout(total=timeout),
            allow_redirects=True,
        ) as response:
            text = await response.text("utf-8", errors="ignore")
            return HttpResponse(
                body=text,
                status=response.status,
                url=str(response.url),
                headers=dict(response.headers),
            )
    except Exception:
        return HttpResponse("", 0, url, {})


async def fetch_page(url: str, timeout: int = 10) -> HttpResponse:
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    headers = {"User-Agent": "SilentFrog/1.0 (+https://example.com)"}
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
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
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=ClientTimeout(total=timeout)) as response:
                return await response.text()
    except Exception:
        return None
