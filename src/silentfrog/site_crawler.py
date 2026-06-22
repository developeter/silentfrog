from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Protocol
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
# v2.0 V3.2: when streaming to a store, keep full payloads in memory only
# for the first N results (rich history + instant detail on small crawls).
# Beyond N the payload lives on disk and the in-memory result carries
# lightweight fields only — bounding RAM at ~1M URLs.
_PAYLOAD_MEMORY_LIMIT = 2000
# v2.0 PR-8a: the worker queue is bounded so memory stays flat at ~1M URLs.
# A single producer claims pending work from the durable frontier and feeds
# this queue; it blocks (backpressure) when the queue is full. Workers persist
# their discoveries to the frontier — NOT this queue — so they never block
# while producing, which is what keeps the bounded queue deadlock-free.
_WORK_QUEUE_BOUND = 256
_CLAIM_BATCH = 64
# Terminal frontier states for a processed URL (default ``completed``).
_FRONTIER_STATES = {"error": "failed", "skipped": "skipped"}


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
    admitted_seeds = _admit_seeds(frontier, seeds)
    _emit(on_event, "discovered", discovered=frontier.seen_count, total=frontier.seen_count)
    robots = RobotsCache(config.crawl_options.user_agent, timeout) if spider.respect_robots else None
    run_id = store.start_run(config.base_host, config.base_url, str(spider.mode)) if store else ""
    work_source = _make_work_source(store, run_id)
    work_source.seed([(url, 0, "") for url in admitted_seeds])
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
    results = await _drive_frontier(ctx, work_source)
    if store is not None:
        store.finish_run(run_id)
    return SiteCrawlReport.from_results(results, discovered_count=frontier.seen_count, run_id=run_id)


def _admit_seeds(frontier: CrawlFrontier, seeds: list[str]) -> list[str]:
    """Pass seeds through the in-memory dedup/scope gate (marking them seen) and
    return the normalized URLs that were newly admitted — the work the producer
    starts from. The gate, not this list, is the dedup source of truth in PR-8a."""
    admitted: list[str] = []
    for url in seeds:
        if frontier.admit(url, 0):
            admitted.append(normalize_site_url(url))
    return admitted


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


class _WorkSource(Protocol):
    """The durable frontier of record the producer claims work from. Two impls
    mirror the repository's SQLite/in-memory split (locked decisions #2/#4):
    production crawls use SQLite; store-less tests + bounded small programmatic
    crawls use an in-memory deque. Items are ``(url, depth, source_url)``."""

    def seed(self, items: list[tuple[str, int, str]]) -> None: ...

    def claim(self, batch: int) -> list[tuple[str, int, str]]: ...

    def put_discovery(self, url: str, source_url: str, depth: int) -> None: ...

    def complete(self, url: str, state: str) -> None: ...


class _SqliteWorkSource:
    """SQLite-backed frontier of record (production). The producer claims
    ``pending`` rows; workers persist discoveries as new ``pending`` rows. Dedup
    still happens in the in-memory frontier gate in PR-8a; PR-8b makes this
    table the dedup source of truth."""

    def __init__(self, store: CrawlStore, run_id: str) -> None:
        self._store = store
        self._run_id = run_id

    def seed(self, items: list[tuple[str, int, str]]) -> None:
        for url, depth, source_url in items:
            self._store.admit(self._run_id, url, source_url, depth)

    def claim(self, batch: int) -> list[tuple[str, int, str]]:
        return self._store.claim_pending(self._run_id, batch)

    def put_discovery(self, url: str, source_url: str, depth: int) -> None:
        self._store.admit(self._run_id, url, source_url, depth)

    def complete(self, url: str, state: str) -> None:
        self._store.mark(self._run_id, url, state)


class _MemoryWorkSource:
    """In-memory frontier of record for store-less crawls (tests + explicitly
    bounded small programmatic crawls). Holds its own pending deque; the shared
    in-memory ``CrawlFrontier`` stays the dedup/scope gate."""

    def __init__(self) -> None:
        self._pending: deque[tuple[str, int, str]] = deque()

    def seed(self, items: list[tuple[str, int, str]]) -> None:
        self._pending.extend(items)

    def claim(self, batch: int) -> list[tuple[str, int, str]]:
        claimed: list[tuple[str, int, str]] = []
        while self._pending and len(claimed) < batch:
            claimed.append(self._pending.popleft())
        return claimed

    def put_discovery(self, url: str, source_url: str, depth: int) -> None:
        self._pending.append((url, depth, source_url))

    def complete(self, url: str, state: str) -> None:
        pass


def _make_work_source(store: CrawlStore | None, run_id: str) -> _WorkSource:
    if store is None:
        return _MemoryWorkSource()
    return _SqliteWorkSource(store, run_id)


@dataclass
class _Drive:
    """Live state shared by the single producer and the workers within one
    crawl. Mutated only between ``await`` points, so a plain int + Event are
    safe without locks on the single crawl event loop."""

    work_source: _WorkSource
    queue: asyncio.Queue[tuple[str, int, str]]
    results: list[SiteCrawlResult] = field(default_factory=list)
    in_flight: int = 0
    wakeup: asyncio.Event = field(default_factory=asyncio.Event)


async def _drive_frontier(ctx: _CrawlContext, work_source: _WorkSource) -> list[SiteCrawlResult]:
    drive = _Drive(work_source=work_source, queue=asyncio.Queue(maxsize=_WORK_QUEUE_BOUND))
    workers = [asyncio.create_task(_frontier_worker(ctx, drive)) for _ in range(ctx.concurrency)]
    await _produce(drive)
    for worker in workers:
        worker.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    return drive.results


async def _produce(drive: _Drive) -> None:
    """Single producer: claim pending work from the durable frontier and feed
    the bounded queue, blocking when it is full (backpressure). Workers persist
    discoveries back to the frontier, so the producer alone bridges frontier ->
    queue; nothing else enqueues, which is what makes the bounded queue
    deadlock-free. Terminates when no pending work remains and nothing claimed
    is still in flight (so no worker can produce more). The ``wakeup`` is
    cleared BEFORE claiming so a discovery admitted concurrently cannot be
    lost between an empty claim and the wait."""
    while True:
        drive.wakeup.clear()
        claimed = drive.work_source.claim(_CLAIM_BATCH)
        if claimed:
            await _dispatch(drive, claimed)
            continue
        if drive.in_flight == 0:
            return
        await drive.wakeup.wait()


async def _dispatch(drive: _Drive, claimed: list[tuple[str, int, str]]) -> None:
    # Count claimed work as in flight BEFORE putting, so termination never
    # concludes early while items wait on a full queue.
    drive.in_flight += len(claimed)
    for item in claimed:
        await drive.queue.put(item)


async def _frontier_worker(ctx: _CrawlContext, drive: _Drive) -> None:
    while True:
        url, depth, source_url = await drive.queue.get()
        try:
            await _process_url(ctx, drive, url, depth, source_url)
        finally:
            # Discoveries are already admitted (inside _process_url) before this
            # decrement, so in_flight hitting 0 means no more work can appear.
            drive.in_flight -= 1
            drive.wakeup.set()


async def _process_url(ctx: _CrawlContext, drive: _Drive, url: str, depth: int, source_url: str) -> None:
    await ctx.politeness.wait(url)
    result = await _crawl_one(url, ctx.config, ctx.timeout, ctx.on_event, ctx.cancel_event)
    if ctx.store is not None:
        ctx.store.save_audit(ctx.run_id, _to_stored_audit(result, depth, source_url))
    # Follow links from the FULL payload before any stripping.
    if ctx.follows_links and result.payload is not None:
        await _enqueue_links(ctx, drive, url, result.payload, depth + 1)
    drive.work_source.complete(url, _FRONTIER_STATES.get(result.status, "completed"))
    kept = _bounded_result(ctx, result, len(drive.results))
    drive.results.append(kept)
    _emit(ctx.on_event, "row", result=kept, completed=len(drive.results))


def _bounded_result(ctx: _CrawlContext, result: SiteCrawlResult, current_count: int) -> SiteCrawlResult:
    """Keep the full payload in memory only below the threshold (and only
    when streaming to a store that holds the payload durably). Beyond it,
    strip the payload so the in-memory list + live table model stay flat
    at ~1M URLs; the GUI reloads it from the store on demand."""
    if ctx.store is None or current_count < _PAYLOAD_MEMORY_LIMIT:
        return result
    if result.payload is None:
        return result
    return replace(result, payload=None)


async def _enqueue_links(ctx: _CrawlContext, drive: _Drive, source_url: str, payload: Any, depth: int) -> None:
    for url in _payload_link_urls(payload):
        if not ctx.frontier.in_scope(url, depth):
            continue
        if ctx.robots is not None and not await ctx.robots.allows(url):
            continue
        if ctx.frontier.admit(url, depth):
            # Persist the discovery to the frontier ONLY (never the bounded
            # queue): an unbounded, non-blocking write, so recursive production
            # cannot deadlock the workers.
            drive.work_source.put_discovery(normalize_site_url(url), source_url, depth)


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
