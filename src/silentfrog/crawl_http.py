from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse, urlunparse, urljoin
from urllib.robotparser import RobotFileParser
import re

import aiohttp  # type: ignore[import]  # aiohttp lacks complete stubs in our environment
from aiohttp import ClientSession, ClientTimeout  # type: ignore[import]  # aiohttp stubs missing

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
        cache_hint = _cache_hint(r.headers)
        try:
            from io import BytesIO
            from PIL import Image  # type: ignore

            with Image.open(BytesIO(raw)) as im:
                w, h = im.size
                if not content_type and im.format:
                    content_type = f"image/{im.format.lower()}"
        except Exception:
            w, h = 0, 0

        return url, w, h, size_b, content_type or "-", cache_hint
    except Exception:
        return "Errore", 0, 0, 0, "-", ""


def _cache_hint(headers: Any) -> str:
    cache_control = str(headers.get("Cache-Control", "") or "")
    match = re.search(r"max-age\\s*=\\s*(\\d+)", cache_control, re.I)
    if match:
        return _human_duration(int(match.group(1)))

    expires = headers.get("Expires")
    if expires:
        try:
            dt = parsedate_to_datetime(str(expires))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            remaining = int((dt - datetime.now(timezone.utc)).total_seconds())
            if remaining > 0:
                return _human_duration(remaining)
        except Exception:
            return ""
    return ""


def _human_duration(seconds: int) -> str:
    if seconds <= 0:
        return ""
    parts = []
    units = [("d", 86400), ("h", 3600), ("m", 60)]
    remaining = seconds
    for suffix, span in units:
        if remaining >= span:
            value = remaining // span
            remaining %= span
            parts.append(f"{value}{suffix}")
        if len(parts) == 2:
            break
    if not parts:
        return f"{remaining}s"
    return " ".join(parts)


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


def _redirect_hops_result(hop_urls: list[str], status: str, is_loop: bool) -> tuple[list[str], str, int, bool]:
    return hop_urls, status, len(hop_urls) - 1, is_loop


def _redirect_target(current_url: str, response: Any) -> str | None:
    if not 300 <= response.status < 400:
        return None
    location = response.headers.get("Location")
    if not location:
        return None
    return urljoin(current_url, location)


def _is_redirect_loop(hop_urls: list[str], next_url: str) -> bool:
    return next_url in hop_urls


async def _trace_redirects(url: str, timeout: int = 8) -> tuple[list[str], str, int, bool]:
    max_hops = 6
    hop_urls: list[str] = [url]
    try:
        async with aiohttp.ClientSession() as session:
            current_url = url
            for _ in range(max_hops):
                async with session.head(
                    current_url,
                    allow_redirects=False,
                    timeout=ClientTimeout(total=timeout),
                ) as response:
                    next_url = _redirect_target(current_url, response)
                    if next_url is None:
                        return _redirect_hops_result(hop_urls, str(response.status), False)
                    hop_urls.append(next_url)
                    if _is_redirect_loop(hop_urls[:-1], next_url):
                        return _redirect_hops_result(hop_urls, str(response.status), True)
                    current_url = next_url
        return _redirect_hops_result(hop_urls, "max-hops", False)
    except Exception as exc:
        return _redirect_hops_result(hop_urls, f"error {exc.__class__.__name__}", False)
