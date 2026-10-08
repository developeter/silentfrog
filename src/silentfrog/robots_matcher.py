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
from dataclasses import replace
from functools import partial
from urllib.parse import urlparse

from .crawl_http import _request_headers
from .crawl_options import DEFAULT_USER_AGENT, CrawlOptions
from .http_client import fetch_page
from .robots_simulator import parse_robots


class RobotsMatcher:
    def __init__(self, user_agent: str, robots_text: str = "") -> None:
        self._ua = user_agent or "*"
        # Single live engine (H3): the spider gate, Bot Matrix, and crawl-delay
        # all evaluate through robots_simulator, so their verdicts agree.
        self._rules = parse_robots(robots_text)

    def allows(self, url: str) -> bool:
        # Empty robots.txt → no group → allowed (RFC 9309 permissive default).
        return self._rules.allows(self._ua, url)


def _robots_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def _host_of(url: str) -> str:
    return urlparse(url).netloc.lower()


async def fetch_robots_matcher(
    url: str,
    user_agent: str,
    timeout: int = 10,
    *,
    options: CrawlOptions | None = None,
    origin: str = "",
) -> RobotsMatcher:
    """Fetch + parse robots.txt for the host of ``url``. Never raises.

    Requests carry the configured ``user_agent`` and, only when ``url`` is on
    the audited ``origin``, the user's custom headers / Cookie (so a
    cookie-gated robots.txt is honoured without leaking them elsewhere)."""
    robots_url = _robots_url(url)
    if not robots_url:
        return RobotsMatcher(user_agent, "")
    opts = replace(options or CrawlOptions.default(), user_agent=user_agent or DEFAULT_USER_AGENT)
    resp = await fetch_page(robots_url, timeout, headers=_request_headers(opts, origin=origin, target=robots_url))
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
        *,
        options: CrawlOptions | None = None,
        origin: str = "",
    ) -> None:
        self._ua = user_agent
        self._timeout = timeout
        self._fetcher: _FetcherFn = fetcher or partial(fetch_robots_matcher, options=options, origin=origin)
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
