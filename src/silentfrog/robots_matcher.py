"""robots.txt allow/deny matching for the spider (v2.0 V3).

The v1.x crawler only read ``Sitemap:`` directives from robots.txt and
never honoured ``Disallow`` while crawling. The spider must respect the
disallow rules for its own user-agent. We wrap stdlib
``urllib.robotparser`` (correct longest-match + allow/disallow
precedence) and cache one matcher per host, fetched once.

``RobotsCache`` accepts an injectable ``fetcher`` so tests never hit the
network.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from urllib import robotparser
from urllib.parse import urlparse

from .http_client import fetch_page


class RobotsMatcher:
    def __init__(self, user_agent: str, robots_text: str = "") -> None:
        self._ua = user_agent or "*"
        self._parser = robotparser.RobotFileParser()
        self._has_rules = bool(robots_text.strip())
        if self._has_rules:
            self._parser.parse(robots_text.splitlines())

    def allows(self, url: str) -> bool:
        # No robots.txt (or empty) → allow everything.
        if not self._has_rules:
            return True
        return self._parser.can_fetch(self._ua, url)


def _robots_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def _host_of(url: str) -> str:
    return urlparse(url).netloc.lower()


async def fetch_robots_matcher(url: str, user_agent: str, timeout: int = 10) -> RobotsMatcher:
    """Fetch + parse robots.txt for the host of ``url``. Never raises."""
    robots_url = _robots_url(url)
    if not robots_url:
        return RobotsMatcher(user_agent, "")
    resp = await fetch_page(robots_url, timeout)
    text = resp.body if resp.status and resp.status < 400 else ""
    return RobotsMatcher(user_agent, text)


_FetcherFn = Callable[[str, str, int], Awaitable[RobotsMatcher]]


class RobotsCache:
    """One matcher per host, fetched once (async-safe)."""

    def __init__(
        self,
        user_agent: str,
        timeout: int = 10,
        fetcher: _FetcherFn | None = None,
    ) -> None:
        self._ua = user_agent
        self._timeout = timeout
        self._fetcher: _FetcherFn = fetcher or fetch_robots_matcher
        self._cache: dict[str, RobotsMatcher] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def matcher_for(self, url: str) -> RobotsMatcher:
        host = _host_of(url)
        cached = self._cache.get(host)
        if cached is not None:
            return cached
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            if host not in self._cache:
                self._cache[host] = await self._fetcher(url, self._ua, self._timeout)
            return self._cache[host]

    async def allows(self, url: str) -> bool:
        matcher = await self.matcher_for(url)
        return matcher.allows(url)


__all__ = ["RobotsCache", "RobotsMatcher", "fetch_robots_matcher"]
