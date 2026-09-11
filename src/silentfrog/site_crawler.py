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

from .crawl_http import _headers_from_options, robots_fetch_scope
from .crawl_mode import CrawlMode
from .crawl_run_repository import CrawlRunRef
from .crawl_store import CrawlStore, StoredAudit
from .discovery_files import discovery_scope
from .frontier import CrawlFrontier, FrontierConfig
from .http_client import fetch_page
from .render_pool import render_pool_scope_async
from .robots_matcher import RobotsCache
from .seo_crawler import analyse
from .site_crawl_types import (
    SiteCrawlConfig,
    SiteCrawlReport,
    SiteCrawlResult,
    normalize_site_url,
)
from .transport import allow_private_network, insecure_tls

ProgressCallback = Callable[[dict[str, Any]], None]
_MAX_SITEMAP_DEPTH = 3
_COMMON_SITEMAP_PATHS = ("sitemap.xml", "sitemap_index.xml", "sitemap-index.xml")
# v2.0 V3.2: when streaming to a store, keep full payloads in memory only
# for the first N results (rich history + instant detail on small crawls).
# Beyond N the payload lives on disk and the in-memory result carries
# lightweight fields only — keeping peak RSS bounded at scale (verified to
# 100k URLs; method + numbers in tools/perf_harness.py).
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
    resume_run_id: str | None = None,
) -> SiteCrawlReport:
    """Crawl ``config``, streaming audits into ``store`` when given.

    Pass ``resume_run_id`` (store-backed only) to resume an interrupted run:
    its ``in_progress`` rows are returned to ``pending`` and the crawl re-runs
    only its unfinished URLs (PR-9). ``cancel_event`` requests a cooperative
    stop — in-flight requests finish, claimed-but-unstarted URLs stay
    ``in_progress`` for a later resume, and the partial run stays queryable.

    The crawl's TLS/SSRF posture (``CrawlOptions.allow_insecure_tls`` /
    ``allow_private_network``, both off by default) wraps the *whole*
    orchestration — seed building, robots and sitemap discovery, and every
    page fetch — so an explicit opt-in reaches discovery, not only
    ``analyse()``. With the defaults it is a no-op: verification on, SSRF
    guarded."""
    opts = config.crawl_options
    with (
        insecure_tls(enabled=opts.allow_insecure_tls),
        allow_private_network(enabled=opts.allow_private_network),
    ):
        return await _orchestrate_crawl(config, timeout, on_event, cancel_event, store, resume_run_id)


async def _orchestrate_crawl(
    config: SiteCrawlConfig,
    timeout: int,
    on_event: ProgressCallback | None,
    cancel_event: threading.Event | None,
    store: CrawlStore | None,
    resume_run_id: str | None,
) -> SiteCrawlReport:
    spider = config.spider
    seeds = await _build_seeds(config, timeout)
    seed_warning = _sitemap_only_empty_warning(config) if spider.mode is CrawlMode.SITEMAP and not seeds else ""
    frontier = _build_frontier(config)
    run_id = _start_or_resume(store, config, resume_run_id)
    work_source = _make_work_source(store, run_id, frontier, spider.max_urls)
    for seed in seeds:
        work_source.admit(seed, "", 0)
    _emit(on_event, "discovered", discovered=work_source.count(), total=work_source.count())
    robots = RobotsCache(config.crawl_options.user_agent, timeout) if spider.respect_robots else None
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
    # H4: site-wide discovery (robots/sitemap/llms.txt/ai.json) is fetched once
    # per origin for the whole crawl, in every profile, instead of per page.
    # robots_fetch_scope covers the separate robots.txt fetch the crawl-delay
    # check (respect_crawl_delay, on by default) makes per page.
    # render_pool_scope_async gives every page of this crawl a shared pool of
    # Chromium browsers (render_js / SSR parity), sized to this crawl's own
    # concurrency so rendering keeps the parallelism the pre-pool direct call
    # had instead of serialising every render behind one worker thread;
    # closed on exit here (normal, cancelled, or errored) so the pool's
    # worker threads never leak, and off the event loop (see its docstring)
    # so a render still in flight at crawl end never freezes progress
    # callbacks. A crawl that never enables rendering never starts a worker
    # thread — see render_pool.RenderPool._ensure_started — so this costs
    # nothing when off.
    async with render_pool_scope_async(workers=ctx.concurrency):
        with discovery_scope(), robots_fetch_scope():
            drive = await _drive_frontier(ctx, work_source)
    # item 5: the last page is fetched; report building (store finish + summaries)
    # starts now. Emit here — not after crawl_site returns — so the GUI shows the
    # finalize phase *while* that work runs, in every crawl mode.
    _emit(on_event, "finalizing")
    return _build_report(config, store, run_id, drive, work_source.count(), _is_cancelled(ctx), seed_warning)


def _start_or_resume(store: CrawlStore | None, config: SiteCrawlConfig, resume_run_id: str | None) -> str:
    """Start a fresh run, or resume an existing one by requeuing its abandoned
    ``in_progress`` rows. Resume needs a store (the durable frontier); a
    store-less resume request is ignored (in-memory crawls do not persist)."""
    if store is None:
        return ""
    if resume_run_id:
        store.requeue_in_progress(resume_run_id)
        return resume_run_id
    return store.start_run(config.base_host, config.base_url, str(config.spider.mode))


def _build_report(
    config: SiteCrawlConfig,
    store: CrawlStore | None,
    run_id: str,
    drive: _Drive,
    discovered: int,
    cancelled: bool,
    seed_warning: str = "",
) -> SiteCrawlReport:
    """Store-less crawls return their bounded in-memory results; store-backed
    crawls return only a CrawlRunRef + counts (H2) so the report stays flat —
    the summary counts come from the store, never an in-memory result list. A
    cancelled run is finished as ``cancelled`` (not ``completed``) but stays
    fully queryable through its CrawlRunRef (partial-run persistence, PR-9).
    ``seed_warning`` (e.g. sitemap-only mode finding nothing) is joined after
    the WAF warning, when both apply."""
    if store is None:
        return SiteCrawlReport.from_results(
            drive.results, discovered_count=discovered, base_url=config.base_url, extra_warning=seed_warning
        )
    store.finish_run(run_id, status="cancelled" if cancelled else "completed")
    summary = store.summary(run_id)
    return SiteCrawlReport.from_run(
        CrawlRunRef(store.db_path, run_id),
        discovered_count=discovered,
        crawled_count=summary.total - summary.skipped,
        skipped_count=summary.skipped,
        failed_count=summary.failed,
        waf_count=drive.waf_count,
        base_url=config.base_url,
        extra_warning=seed_warning,
    )


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


def _sitemap_only_empty_warning(config: SiteCrawlConfig) -> str:
    """The user explicitly chose sitemap-only mode and discovery found no
    sitemap URL, robots.txt Sitemap: line, or sitemap at a common path — so
    ``_build_seeds`` returned nothing and the crawl would otherwise finish
    'successfully' with 0 discovered/crawled and no explanation. Do NOT fall
    back to the base URL here (that would override an explicit user choice) —
    just make the empty result legible."""
    return (
        f"No URLs were found in any sitemap for {config.base_url}, so nothing was crawled. "
        "Check the sitemap URL, or switch Crawl mode to Auto to crawl from the base URL."
    )


async def _seed_from_sitemap(config: SiteCrawlConfig, timeout: int) -> list[str]:
    if config.sitemap_url:
        urls = await _sitemap_urls(config.sitemap_url, config, timeout)
    else:
        urls = await _auto_sitemap_urls(config, timeout)
    return _filter_urls(urls, config)


class _WorkSource(Protocol):
    """The durable frontier of record the producer claims work from, and the
    dedup/scope/cap gate discoveries pass through. Two impls mirror the
    repository's SQLite/in-memory split (locked decisions #2/#4): production
    crawls dedup on the **exact SQLite frontier table** (the seen-set lives on
    disk, not RAM); store-less tests + bounded small programmatic crawls dedup
    in the in-memory ``CrawlFrontier``. Items are ``(url, depth, source_url)``."""

    def admit(self, url: str, source_url: str, depth: int) -> bool: ...

    def claim(self, batch: int) -> list[tuple[str, int, str]]: ...

    def complete(self, url: str, state: str) -> None: ...

    def count(self) -> int: ...


class _SqliteWorkSource:
    """SQLite-backed frontier of record + dedup source of truth (production,
    PR-8b). Admission dedups atomically on the frontier's ``UNIQUE(run_id,
    normalized_url)`` index, so the seen-set is on disk; an O(1) counter bounds
    the cap without an in-RAM set. Scope/depth stay on the stateless frontier
    gate."""

    def __init__(self, store: CrawlStore, run_id: str, frontier: CrawlFrontier, max_urls: int) -> None:
        self._store = store
        self._run_id = run_id
        self._frontier = frontier
        self._max_urls = max_urls
        # Seed the cap counter from the durable frontier: 0 for a fresh run,
        # the already-admitted total when resuming (PR-9) so the cap holds across
        # sessions instead of admitting another ``max_urls`` on resume.
        self._count = store.frontier_count(run_id)

    def admit(self, url: str, source_url: str, depth: int) -> bool:
        if not self._frontier.in_scope(url, depth) or self._count >= self._max_urls:
            return False
        if not self._store.admit(self._run_id, url, source_url, depth):
            return False  # already present in the frontier (UNIQUE) — not newly admitted
        self._count += 1
        return True

    def claim(self, batch: int) -> list[tuple[str, int, str]]:
        return self._store.claim_pending(self._run_id, batch)

    def complete(self, url: str, state: str) -> None:
        self._store.mark(self._run_id, url, state)

    def count(self) -> int:
        return self._count


class _MemoryWorkSource:
    """In-memory frontier of record for store-less crawls (tests + explicitly
    bounded small programmatic crawls). The shared ``CrawlFrontier`` is the
    dedup/scope/cap gate; this holds the pending deque the producer drains."""

    def __init__(self, frontier: CrawlFrontier) -> None:
        self._frontier = frontier
        self._pending: deque[tuple[str, int, str]] = deque()

    def admit(self, url: str, source_url: str, depth: int) -> bool:
        if not self._frontier.admit(url, depth):
            return False
        self._pending.append((url, depth, source_url))
        return True

    def claim(self, batch: int) -> list[tuple[str, int, str]]:
        claimed: list[tuple[str, int, str]] = []
        while self._pending and len(claimed) < batch:
            claimed.append(self._pending.popleft())
        return claimed

    def complete(self, url: str, state: str) -> None:
        pass

    def count(self) -> int:
        return self._frontier.seen_count


def _make_work_source(store: CrawlStore | None, run_id: str, frontier: CrawlFrontier, max_urls: int) -> _WorkSource:
    if store is None:
        return _MemoryWorkSource(frontier)
    return _SqliteWorkSource(store, run_id, frontier, max_urls)


@dataclass
class _Drive:
    """Live state shared by the single producer and the workers within one
    crawl. Mutated only between ``await`` points, so plain ints + an Event are
    safe without locks on the single crawl event loop. ``results`` accumulates
    only for store-less crawls; store-backed crawls keep nothing per-URL."""

    work_source: _WorkSource
    queue: asyncio.Queue[tuple[str, int, str]]
    keep_results: bool
    results: list[SiteCrawlResult] = field(default_factory=list)
    emitted: int = 0
    waf_count: int = 0
    in_flight: int = 0
    wakeup: asyncio.Event = field(default_factory=asyncio.Event)


async def _drive_frontier(ctx: _CrawlContext, work_source: _WorkSource) -> _Drive:
    drive = _Drive(
        work_source=work_source,
        queue=asyncio.Queue(maxsize=_WORK_QUEUE_BOUND),
        keep_results=ctx.store is None,
    )
    workers = [asyncio.create_task(_frontier_worker(ctx, drive)) for _ in range(ctx.concurrency)]
    await _produce(ctx, drive)
    for worker in workers:
        worker.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    return drive


def _is_cancelled(ctx: _CrawlContext) -> bool:
    return ctx.cancel_event is not None and ctx.cancel_event.is_set()


async def _produce(ctx: _CrawlContext, drive: _Drive) -> None:
    """Single producer: claim pending work from the durable frontier and feed
    the bounded queue, blocking when it is full (backpressure). Workers persist
    discoveries back to the frontier, so the producer alone bridges frontier ->
    queue; nothing else enqueues, which is what makes the bounded queue
    deadlock-free. Terminates when no pending work remains and nothing claimed
    is still in flight (so no worker can produce more). The ``wakeup`` is
    cleared BEFORE claiming so a discovery admitted concurrently cannot be
    lost between an empty claim and the wait.

    On cancel (PR-9) the producer stops claiming new work but does NOT return
    while items are still in flight: it waits for the in-flight count to drain
    so no worker is mid-request when the workers are cancelled (in-flight
    requests finish; claimed-but-unstarted URLs are abandoned in ``in_progress``
    by the worker). This keeps cancel deadlock-free — the same bounded drain as
    normal termination, just with claiming switched off."""
    while True:
        drive.wakeup.clear()
        if not _is_cancelled(ctx):
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
    # Cooperative cancellation (PR-9): abandon a claimed-but-unstarted URL by
    # returning before any work — its frontier row stays ``in_progress`` and a
    # later resume requeues it. Re-checked after the politeness wait so a cancel
    # during that wait still skips the (possibly rendering) analyse call. An
    # in-flight request past this point finishes normally and is persisted.
    if _is_cancelled(ctx):
        return
    await ctx.politeness.wait(url)
    if _is_cancelled(ctx):
        return
    result = await _crawl_one(url, ctx.config, ctx.timeout, ctx.on_event)
    if ctx.store is not None:
        ctx.store.save_audit(ctx.run_id, _to_stored_audit(result, depth, source_url))
    # Follow links from the FULL payload before any stripping.
    if ctx.follows_links and result.payload is not None:
        await _enqueue_links(ctx, drive, url, result.payload, depth + 1)
    drive.work_source.complete(url, _FRONTIER_STATES.get(result.status, "completed"))
    if result.has_waf_signal:
        drive.waf_count += 1
    kept = _bounded_result(ctx, result, drive.emitted)
    drive.emitted += 1
    if drive.keep_results:
        drive.results.append(kept)
    _emit(ctx.on_event, "row", result=kept, completed=drive.emitted)


def _bounded_result(ctx: _CrawlContext, result: SiteCrawlResult, emitted: int) -> SiteCrawlResult:
    """Strip the payload off the live row event past the threshold (store-backed
    crawls only) so the live GUI table model stays flat at ~1M URLs; the GUI
    reloads the payload from the store on demand. Store-less crawls keep every
    payload (they have no store to reload from)."""
    if ctx.store is None or emitted < _PAYLOAD_MEMORY_LIMIT:
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
        # Dedup + cap + persist happen in the work source (SQLite frontier for
        # production, in-memory frontier for store-less). The discovery is
        # written to the frontier ONLY — never the bounded queue — so recursive
        # production is a non-blocking write and cannot deadlock the workers.
        drive.work_source.admit(normalize_site_url(url), source_url, depth)


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
) -> SiteCrawlResult:
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
    # robots.txt is authoritative when it names a Sitemap: only fall back to
    # the hardcoded common paths when robots.txt supplied nothing usable, so
    # an unrelated sitemap sitting at a common path can't scope-creep into
    # the crawl once robots.txt already answered the question.
    candidates = await _robots_sitemap_urls(config, timeout)
    if not candidates:
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


__all__ = ["crawl_site"]
