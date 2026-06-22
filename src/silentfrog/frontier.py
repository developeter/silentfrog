"""Crawl frontier (v2.0 V3).

The URL queue that turns the v1.x sitemap enumeration into a real
link-following spider. Pure + synchronous: dedup (in-memory seen set),
depth tracking, scope (same-host / subdomain + include/exclude), and the
``max_urls`` cap all live here. The async robots check stays in the
orchestrator (it is per-host and cacheable) and gates ``enqueue``.

This in-memory seen set backs only store-less crawls (tests + bounded
small programmatic runs). Production crawls are SQLite-backed and dedup on
the exact frontier table (the seen-set lives on disk, not RAM), so peak
RSS stays bounded — measured ~117 MB at 100k URLs, the verified scale gate
(``tools/perf_harness.py``). 1M is a post-gate follow-up.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .site_crawl_types import normalize_site_url


@dataclass(frozen=True)
class FrontierConfig:
    base_host: str
    max_depth: int = 10
    max_urls: int = 100_000
    same_host_only: bool = True
    follow_subdomains: bool = False
    include_patterns: tuple[str, ...] = field(default_factory=tuple)
    exclude_patterns: tuple[str, ...] = field(default_factory=tuple)


def _valid_http(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _host_in_scope(url: str, config: FrontierConfig) -> bool:
    if not config.same_host_only:
        return True
    host = urlparse(url).netloc.lower()
    if host == config.base_host:
        return True
    if config.follow_subdomains:
        return host.endswith("." + config.base_host)
    return False


def _pattern_matches(url: str, pattern: str) -> bool:
    text = pattern.strip()
    if not text:
        return False
    if text.startswith("/"):
        return urlparse(url).path.startswith(text)
    return text.lower() in url.lower()


def _included(url: str, patterns: tuple[str, ...]) -> bool:
    return not patterns or any(_pattern_matches(url, p) for p in patterns)


def _excluded(url: str, patterns: tuple[str, ...]) -> bool:
    return any(_pattern_matches(url, p) for p in patterns)


class CrawlFrontier:
    def __init__(self, config: FrontierConfig) -> None:
        self._config = config
        self._queue: deque[tuple[str, int]] = deque()
        self._seen: set[str] = set()

    def seed(self, urls: list[str]) -> int:
        return sum(1 for url in urls if self.enqueue(url, depth=0))

    def admit(self, url: str, depth: int) -> bool:
        """Dedup + scope + cap gate. Marks the URL seen and returns whether
        it should be crawled — WITHOUT appending to the internal deque.

        The live crawl drives an ``asyncio.Queue`` and uses this as the
        gate; the standalone ``enqueue`` builds on it for the deque-backed
        API the unit tests exercise.
        """
        norm = normalize_site_url(url)
        if not self._acceptable(norm, depth):
            return False
        if norm in self._seen:
            return False
        if len(self._seen) >= self._config.max_urls:
            return False
        self._seen.add(norm)
        return True

    def enqueue(self, url: str, depth: int) -> bool:
        if not self.admit(url, depth):
            return False
        self._queue.append((normalize_site_url(url), depth))
        return True

    def add_links(self, urls: list[str], depth: int) -> int:
        return sum(1 for url in urls if self.enqueue(url, depth))

    def pop(self) -> tuple[str, int] | None:
        return self._queue.popleft() if self._queue else None

    def in_scope(self, url: str, depth: int) -> bool:
        """Scope check exposed so the orchestrator can pre-filter before
        the async robots lookup (avoids a robots fetch for out-of-scope
        links)."""
        return self._acceptable(normalize_site_url(url), depth)

    def _acceptable(self, url: str, depth: int) -> bool:
        if depth > self._config.max_depth:
            return False
        if not _valid_http(url):
            return False
        if not _host_in_scope(url, self._config):
            return False
        if not _included(url, self._config.include_patterns):
            return False
        return not _excluded(url, self._config.exclude_patterns)

    def __len__(self) -> int:
        return len(self._queue)

    @property
    def seen_count(self) -> int:
        return len(self._seen)

    @property
    def is_empty(self) -> bool:
        return not self._queue


__all__ = ["CrawlFrontier", "FrontierConfig"]
