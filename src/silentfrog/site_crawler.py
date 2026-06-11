from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

from .crawl_http import _headers_from_options
from .crawl_mode import CrawlMode
from .crawl_store import CrawlStore, StoredAudit
from .frontier import CrawlFrontier, FrontierConfig
from .http_client import fetch_page
from .robots_matcher import RobotsCache
from .seo_crawler import analyse
from .site_crawl_types import (
    SiteCrawlConfig,
    SiteCrawlReport,
    SiteCrawlResult,
    normalize_site_url,
)

ProgressCallback = Callable[[dict[str, Any]], None]
_MAX_SITEMAP_DEPTH = 3
_COMMON_SITEMAP_PATHS = ("sitemap.xml", "sitemap_index.xml", "sitemap-index.xml")


@dataclass(frozen=True)
class _SitemapItems:
    urls: tuple[str, ...]
    sitemaps: tuple[str, ...]


async def resolve_site_urls(config: SiteCrawlConfig, timeout: int = 15) -> list[str]:
    candidates: list[str] = []
    candidates.extend(config.url_list)
    if config.sitemap_url:
        candidates.extend(await _sitemap_urls(config.sitemap_url, config, timeout))
        return _filter_urls(candidates, config)
    if candidates:
        return _filter_urls(candidates, config)
    sitemap_candidates = await _auto_sitemap_urls(config, timeout)
    filtered = _filter_urls(sitemap_candidates, config)
    if filtered:
        return filtered
    return _filter_urls([config.base_url], config)


class _PolitenessGate:
    """Per-host minimum delay so the spider never hammers a single host."""

    def __init__(self, delay_ms: int) -> None:
        self._delay = max(0.0, delay_ms / 1000.0)
        self._next_at: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait(self, url: str) -> None:
        if self._delay <= 0:
            return
        host = urlparse(url).netloc.lower()
        async with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_at.get(host, 0.0))
            self._next_at[host] = slot + self._delay
            wait_for = slot - now
        if wait_for > 0:
            await asyncio.sleep(wait_for)


@dataclass
class _CrawlContext:
    config: SiteCrawlConfig
    frontier: CrawlFrontier
    robots: RobotsCache | None
    store: CrawlStore | None
    run_id: str
    on_event: ProgressCallback | None
    cancel_event: threading.Event | None
    timeout: int
    politeness: _PolitenessGate
    follows_links: bool

    @property
    def concurrency(self) -> int:
        return max(1, min(16, self.config.spider.crawl_concurrency))


async def crawl_site(
    config: SiteCrawlConfig,
    timeout: int = 15,
    on_event: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
    store: CrawlStore | None = None,
) -> SiteCrawlReport:
    spider = config.spider
    seeds = await _build_seeds(config, timeout)
    frontier = _build_frontier(config)
    frontier.seed(seeds)
    _emit(on_event, "discovered", discovered=frontier.seen_count, total=frontier.seen_count)
    robots = RobotsCache(config.crawl_options.user_agent, timeout) if spider.respect_robots else None
    run_id = store.start_run(config.base_host, config.base_url, str(spider.mode)) if store else ""
    ctx = _CrawlContext(
        config=config,
        frontier=frontier,
        robots=robots,
        store=store,
        run_id=run_id,
        on_event=on_event,
        cancel_event=cancel_event,
        timeout=timeout,
        politeness=_PolitenessGate(spider.politeness_delay_ms),
        follows_links=spider.mode.follows_links,
    )
    results = await _drive_frontier(ctx)
    if store is not None:
        store.finish_run(run_id)
    return SiteCrawlReport.from_results(results, discovered_count=frontier.seen_count)


def _build_frontier(config: SiteCrawlConfig) -> CrawlFrontier:
    spider = config.spider
    return CrawlFrontier(
        FrontierConfig(
            base_host=config.base_host,
            max_depth=spider.max_depth,
            max_urls=spider.max_urls,
            same_host_only=config.same_host_only,
            follow_subdomains=spider.follow_subdomains,
            include_patterns=config.include_patterns,
            exclude_patterns=config.exclude_patterns,
        )
    )


async def _build_seeds(config: SiteCrawlConfig, timeout: int) -> list[str]:
    mode = config.spider.mode
    if mode is CrawlMode.LIST:
        return _filter_urls(list(config.url_list), config)
    if mode is CrawlMode.SITEMAP:
        return await _seed_from_sitemap(config, timeout)
    if mode is CrawlMode.SPIDER:
        return _filter_urls([config.base_url], config)
    sitemap_seeds = await _seed_from_sitemap(config, timeout)
    return _filter_urls([config.base_url, *sitemap_seeds], config)


async def _seed_from_sitemap(config: SiteCrawlConfig, timeout: int) -> list[str]:
    if config.sitemap_url:
        urls = await _sitemap_urls(config.sitemap_url, config, timeout)
    else:
        urls = await _auto_sitemap_urls(config, timeout)
    return _filter_urls(urls, config)


async def _drive_frontier(ctx: _CrawlContext) -> list[SiteCrawlResult]:
    results: list[SiteCrawlResult] = []
    queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
    while not ctx.frontier.is_empty:
        item = ctx.frontier.pop()
        if item is not None:
            queue.put_nowait(item)
    if queue.empty():
        return results
    workers = [asyncio.create_task(_frontier_worker(ctx, queue, results)) for _ in range(ctx.concurrency)]
    await queue.join()
    for worker in workers:
        worker.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    return results


async def _frontier_worker(
    ctx: _CrawlContext,
    queue: asyncio.Queue[tuple[str, int]],
    results: list[SiteCrawlResult],
) -> None:
    while True:
        url, depth = await queue.get()
        try:
            await _process_url(ctx, url, depth, queue, results)
        finally:
            queue.task_done()


async def _process_url(
    ctx: _CrawlContext,
    url: str,
    depth: int,
    queue: asyncio.Queue[tuple[str, int]],
    results: list[SiteCrawlResult],
) -> None:
    await ctx.politeness.wait(url)
    result = await _crawl_one(url, ctx.config, ctx.timeout, ctx.on_event, ctx.cancel_event)
    results.append(result)
    if ctx.store is not None:
        ctx.store.save_audit(ctx.run_id, _to_stored_audit(result, depth))
    _emit(ctx.on_event, "row", result=result, completed=len(results))
    if ctx.follows_links and result.payload is not None:
        await _enqueue_links(ctx, result.payload, depth + 1, queue)


async def _enqueue_links(
    ctx: _CrawlContext,
    payload: Any,
    depth: int,
    queue: asyncio.Queue[tuple[str, int]],
) -> None:
    for url in _payload_link_urls(payload):
        if not ctx.frontier.in_scope(url, depth):
            continue
        if ctx.robots is not None and not await ctx.robots.allows(url):
            continue
        if ctx.frontier.admit(url, depth):
            queue.put_nowait((normalize_site_url(url), depth))


def _payload_link_urls(payload: Any) -> list[str]:
    rows = getattr(payload, "links", []) or []
    return [str(row[0]) for row in rows if row]


def _result_geo_score(result: SiteCrawlResult) -> int:
    if result.payload is None:
        return 0
    return result.payload.ai_visibility.summary.score


def _to_stored_audit(result: SiteCrawlResult, depth: int, discovered_from: str = "") -> StoredAudit:
    return StoredAudit(
        url=result.url,
        depth=depth,
        discovered_from=discovered_from,
        http_status=result.status,
        geo_score=_result_geo_score(result),
        indexability=result.indexability,
        title=result.title,
        issue_summary=result.issue_summary(),
        payload=result.payload.to_mapping() if result.payload is not None else None,
    )


async def _crawl_one(
    url: str,
    config: SiteCrawlConfig,
    timeout: int,
    on_event: ProgressCallback | None,
    cancel_event: threading.Event | None,
) -> SiteCrawlResult:
    if cancel_event and cancel_event.is_set():
        return SiteCrawlResult.skipped(url, "Cancelled")
    _emit(on_event, "running", url=url)
    try:
        payload = await analyse(url, timeout=timeout, options=config.crawl_options)
    except Exception as exc:  # noqa: BLE001
        return SiteCrawlResult.failed(url, str(exc))
    return SiteCrawlResult.from_payload(url, payload)


async def _sitemap_urls(url: str, config: SiteCrawlConfig, timeout: int) -> list[str]:
    seen: set[str] = set()
    pages: list[str] = []
    pending: list[tuple[str, int]] = [(url, 0)]
    while pending:
        current, depth = pending.pop(0)
        if current in seen or depth > _MAX_SITEMAP_DEPTH:
            continue
        seen.add(current)
        items = await _fetch_sitemap(current, config, timeout)
        pages.extend(items.urls)
        pending.extend((child, depth + 1) for child in items.sitemaps)
    return pages


async def _auto_sitemap_urls(config: SiteCrawlConfig, timeout: int) -> list[str]:
    page_urls: list[str] = []
    for sitemap_url in await _discover_sitemap_urls(config, timeout):
        page_urls.extend(await _sitemap_urls(sitemap_url, config, timeout))
    return page_urls


async def _discover_sitemap_urls(config: SiteCrawlConfig, timeout: int) -> list[str]:
    candidates = await _robots_sitemap_urls(config, timeout)
    candidates.extend(_common_sitemap_urls(config))
    return list(dict.fromkeys(url for url in candidates if _valid_http_url(url)))


async def _robots_sitemap_urls(config: SiteCrawlConfig, timeout: int) -> list[str]:
    response = await fetch_page(
        _site_url(config, "robots.txt"), timeout=timeout, headers=_headers_from_options(config.crawl_options)
    )
    if response.status >= 400 or not response.body:
        return []
    return _robots_sitemap_directives(response.body)


def _robots_sitemap_directives(text: str) -> list[str]:
    urls: list[str] = []
    for line in text.splitlines():
        sitemap_url = _normalize_sitemap_directive(line)
        if sitemap_url:
            urls.append(sitemap_url)
    return urls


def _common_sitemap_urls(config: SiteCrawlConfig) -> list[str]:
    return [_site_url(config, path) for path in _COMMON_SITEMAP_PATHS]


def _site_url(config: SiteCrawlConfig, path: str) -> str:
    parsed = urlparse(config.base_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/{path.lstrip('/')}"


def _normalize_sitemap_directive(line: str) -> str:
    value = line.split("#", 1)[0].strip()
    if not value.lower().startswith("sitemap:"):
        return ""
    return normalize_site_url(value.split(":", 1)[1].strip())


async def _fetch_sitemap(url: str, config: SiteCrawlConfig, timeout: int) -> _SitemapItems:
    response = await fetch_page(url, timeout=timeout, headers=_headers_from_options(config.crawl_options))
    if response.status >= 400 or not response.body:
        return _SitemapItems(urls=(), sitemaps=())
    return _parse_sitemap(response.body)


def _parse_sitemap(xml_text: str) -> _SitemapItems:
    try:
        root = ElementTree.fromstring(xml_text.encode("utf-8"))
    except ElementTree.ParseError:
        return _SitemapItems(urls=(), sitemaps=())
    if _local_name(root.tag) == "sitemapindex":
        return _SitemapItems(urls=(), sitemaps=tuple(_direct_loc_children(root, "sitemap")))
    if _local_name(root.tag) == "urlset":
        return _SitemapItems(urls=tuple(_direct_loc_children(root, "url")), sitemaps=())
    return _SitemapItems(urls=(), sitemaps=())


def _direct_loc_children(root: ElementTree.Element, parent_name: str) -> list[str]:
    urls: list[str] = []
    for child in root:
        if _local_name(child.tag) != parent_name:
            continue
        loc = _child_text(child, "loc")
        if loc:
            urls.append(normalize_site_url(loc))
    return urls


def _child_text(element: ElementTree.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _filter_urls(urls: list[str], config: SiteCrawlConfig) -> list[str]:
    normalized = [normalize_site_url(url) for url in urls if _valid_http_url(url)]
    scoped = [url for url in normalized if _same_host_allowed(url, config)]
    included = [url for url in scoped if _included(url, config.include_patterns)]
    filtered = [url for url in included if not _excluded(url, config.exclude_patterns)]
    return list(dict.fromkeys(filtered))[: config.limit]


def _valid_http_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _same_host_allowed(url: str, config: SiteCrawlConfig) -> bool:
    if not config.same_host_only:
        return True
    return urlparse(url).netloc.lower() == config.base_host


def _included(url: str, patterns: tuple[str, ...]) -> bool:
    return not patterns or any(_pattern_matches(url, pattern) for pattern in patterns)


def _excluded(url: str, patterns: tuple[str, ...]) -> bool:
    return any(_pattern_matches(url, pattern) for pattern in patterns)


def _pattern_matches(url: str, pattern: str) -> bool:
    parsed = urlparse(url)
    text = pattern.strip()
    if text.startswith("/"):
        return parsed.path.startswith(text)
    return text.lower() in url.lower()


def _emit(callback: ProgressCallback | None, event: str, **payload: Any) -> None:
    if callback is None:
        return
    callback({"event": event, **payload})


__all__ = ["crawl_site", "resolve_site_urls"]
