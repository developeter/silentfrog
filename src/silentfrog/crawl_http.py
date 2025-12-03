from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse, urlunparse, urljoin
from urllib.robotparser import RobotFileParser

import aiohttp  # type: ignore
from aiohttp import ClientSession, ClientTimeout  # type: ignore

from .http_client import head_status, fetch_text
from .crawl_options import CrawlOptions
from .crawl_constants import _ACCEPT_DEFAULT, _ACCEPT_LANGUAGE_DEFAULT
_HOST_LIMITERS: dict[str, tuple[int, asyncio.Semaphore]] = {}
_HOST_LIMITER_LOCK = asyncio.Lock()
_HOST_DELAYS: dict[str, float] = {}
_BACKOFF_STATUSES = {403, 429}
_BACKOFF_DELAY = 1.5


def _host_key(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path or url
    return host.lower()


async def _get_host_semaphore(host: str, limit: int) -> asyncio.Semaphore:
    async with _HOST_LIMITER_LOCK:
        cached = _HOST_LIMITERS.get(host)
        if cached and cached[0] == limit:
            return cached[1]
        semaphore = asyncio.Semaphore(limit)
        _HOST_LIMITERS[host] = (limit, semaphore)
        return semaphore


@asynccontextmanager
async def _throttle_host(host: str, options: CrawlOptions):
    if not options.gentle_mode:
        yield
        return
    semaphore = await _get_host_semaphore(host, max(1, options.max_concurrent_per_host))
    async with semaphore:
        yield


def _headers_from_options(options: CrawlOptions) -> dict[str, str]:
    base = {
        "User-Agent": options.user_agent,
        "Accept": _ACCEPT_DEFAULT,
        "Accept-Language": _ACCEPT_LANGUAGE_DEFAULT,
    }
    if not options.extra_headers:
        return base
    return {**base, **options.extra_headers}


async def _image_info(session: aiohttp.ClientSession, url: str, timeout: int):
    try:
        async with session.get(url, timeout=ClientTimeout(total=timeout)) as r:
            raw = await r.read()

        size_b = len(raw)
        content_type = (r.headers.get("Content-Type") or "").split(";", 1)[0].lower()
        try:
            from io import BytesIO
            from PIL import Image  # type: ignore

            with Image.open(BytesIO(raw)) as im:
                w, h = im.size
                if not content_type and im.format:
                    content_type = f"image/{im.format.lower()}"
        except Exception:
            w, h = 0, 0

        return url, w, h, size_b, content_type or "-"
    except Exception:
        return "Errore", 0, 0, 0, "-"


async def _link_status(session: ClientSession, url: str, timeout: int, options: CrawlOptions) -> int:
    host = _host_key(url)
    async with _throttle_host(host, options):
        delay = _HOST_DELAYS.get(host, 0.0) if options.gentle_mode and options.respect_crawl_delay else 0.0
        if delay > 0:
            await asyncio.sleep(delay)
        attempts = 2 if options.gentle_mode else 1
        code = 0
        for attempt in range(attempts):
            code = await head_status(session, url, timeout)
            should_retry = code in _BACKOFF_STATUSES and attempt < attempts - 1
            if not should_retry:
                break
            await asyncio.sleep(_BACKOFF_DELAY)
        return code


async def _fetch_robots(url: str, timeout: int = 5) -> str | None:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    return await fetch_text(robots_url, timeout)


async def _parse_robots(url: str, timeout: int = 5) -> dict[str, list[tuple[str, str]]]:
    txt = await _fetch_robots(url, timeout)
    if txt is None:
        return {}

    result: dict[str, list[tuple[str, str]]] = {}
    current_agents: list[str] = ["*"]

    for raw in txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue

        if ":" not in line:
            continue
        key, value = (p.strip() for p in line.split(":", 1))
        key_low = key.lower()

        if key_low == "user-agent":
            current_agents = [a.strip() for a in value.split()]
            for ua in current_agents:
                result.setdefault(ua, [])
            continue

        if key_low in ("allow", "disallow"):
            for ua in current_agents:
                result.setdefault(ua, []).append((key.title(), value))
            continue

        for ua in current_agents:
            result.setdefault(ua, []).append((key.title(), value))

    return result


def _crawl_delay_for(options: CrawlOptions, host: str, robots: dict[str, list[tuple[str, str]]]) -> float:
    if not options.gentle_mode or not options.respect_crawl_delay:
        return 0.0
    ua_key = options.user_agent.lower()
    candidates = robots.get(ua_key) or robots.get("*") or []
    for key, value in candidates:
        if key.lower() == "crawl-delay":
            try:
                return max(0.0, float(value.replace(",", ".").strip()))
            except ValueError:
                return 0.0
    return 0.0


async def _trace_redirects(url: str, timeout: int = 8) -> tuple[list[str], str, int, bool]:
    max_hops = 6
    hop_urls: list[str] = [url]
    try:
        async with aiohttp.ClientSession() as sess:
            cur = url
            for _ in range(max_hops):
                async with sess.head(
                    cur,
                    allow_redirects=False,
                    timeout=ClientTimeout(total=timeout),
                ) as r:
                    status = r.status
                    if 300 <= status < 400 and "Location" in r.headers:
                        nxt = urljoin(cur, r.headers["Location"])
                        if nxt in hop_urls:
                            hop_urls.append(nxt)
                            return hop_urls, str(status), len(hop_urls) - 1, True
                        hop_urls.append(nxt)
                        cur = nxt
                        continue
                    return hop_urls, str(status), len(hop_urls) - 1, False
        return hop_urls, "max-hops", len(hop_urls) - 1, False
    except Exception as exc:
        return hop_urls, f"error {exc.__class__.__name__}", len(hop_urls) - 1, False
