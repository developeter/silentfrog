"""v2.0 PR-8a — bounded/backpressured worker queue.

These tests pin the queue architecture, not just the spider outcome:

- **deadlock prevention** — a tiny queue bound + high fan-out + several
  workers must still complete, because workers persist discoveries to the
  frontier (never the bounded queue) and so never block while producing;
- **backpressure** — the single producer does not eagerly drain the frontier
  into memory; with workers stalled, only ``concurrency`` URLs are in flight
  and pending work remains in the durable frontier;
- **termination** — a crawl with worker-produced discoveries and a cycle
  finishes (no hang) and visits each page once;
- **worker-produced discoveries** — link-only pages reach the store and their
  frontier rows transition through the new claim/mark states.

All deterministic: zero politeness delay, no real sleeps, and every crawl is
wrapped in ``asyncio.wait_for`` so a regression to a blocking design fails fast
instead of hanging the suite.
"""

from __future__ import annotations

import asyncio

import pytest

from silentfrog import site_crawler
from silentfrog.crawl_mode import CrawlMode
from silentfrog.crawl_store import CrawlStore
from silentfrog.crawl_types import CrawlPayload
from silentfrog.site_crawl_types import SiteCrawlConfig, SpiderConfig

_TIMEOUT = 10.0  # generous wall-clock ceiling; a deadlock trips it, real runs finish instantly


def _payload_with_links(url: str, links: list[str]) -> CrawlPayload:
    return CrawlPayload.from_raw(
        {
            "meta": [["title", "T", "1"], ["description", "d", "1"]],
            "headers": [["h1", "T"]],
            "images": [],
            "links": [[link, "anchor", "internal", "200"] for link in links],
            "schema": {"summary": {"total": 0, "by_type": {}}, "blocks": [], "issues": []},
            "canonical": {"target": url, "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": [url], "hops": 0, "final_status": "200", "final_url": url, "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": "index, follow",
            "hreflang": [],
            "ai_crawl": [],
            "serp": {"title": "T", "description": "", "url": url, "site_name": "", "breadcrumb": "", "favicon": ""},
            "serp_audit": {},
            "keywords": [],
            "content_quality": {"word_count": 50},
            "ai_visibility": {"summary": {"verdict": "OK", "score": 80}, "checks": []},
            "performance": {"summary": {"verdict": "Good"}},
            "social": {},
        }
    )


def _spider_config(concurrency: int = 4) -> SiteCrawlConfig:
    spider = SpiderConfig(
        mode=CrawlMode.SPIDER,
        respect_robots=False,
        politeness_delay_ms=0,
        crawl_concurrency=concurrency,
    )
    return SiteCrawlConfig.from_text(base_url="https://e.com", limit=10_000, spider=spider)


def _list_config(urls: list[str], concurrency: int) -> SiteCrawlConfig:
    spider = SpiderConfig(
        mode=CrawlMode.LIST,
        respect_robots=False,
        politeness_delay_ms=0,
        crawl_concurrency=concurrency,
    )
    return SiteCrawlConfig.from_text(
        base_url="https://e.com", url_list_text="\n".join(urls), limit=10_000, spider=spider
    )


def _install_graph(monkeypatch, graph: dict[str, list[str]]) -> None:
    async def fake_analyse(url, timeout, options=None):
        return _payload_with_links(url, graph.get(url, []))

    monkeypatch.setattr(site_crawler, "analyse", fake_analyse)


def _shrink_queue(monkeypatch, *, bound: int, batch: int) -> None:
    monkeypatch.setattr(site_crawler, "_WORK_QUEUE_BOUND", bound)
    monkeypatch.setattr(site_crawler, "_CLAIM_BATCH", batch)


def _crawled_urls(store: CrawlStore, report) -> set[str]:
    # A store-backed report keeps no per-URL results (H2); the crawled set lives
    # in the store, read back via the run's CrawlRunRef.
    return {row.url for row in store.iter_lightweight(report.run_ref.run_id, 0, 10_000)}


@pytest.mark.asyncio
async def test_single_worker_with_tiny_queue_does_not_deadlock(monkeypatch) -> None:
    # The sharpest deadlock case: one worker, queue bound 1. In the naive
    # "workers put into the queue" design the lone worker — its own only
    # consumer — discovers two children, fills the queue with the first, and
    # blocks forever on the second. PR-8a routes discoveries to the frontier
    # instead, so the bound never blocks the worker. A regression hangs and
    # trips the wait_for.
    graph = {
        "https://e.com/": ["https://e.com/a", "https://e.com/b"],
        "https://e.com/a": ["https://e.com/c", "https://e.com/d"],
        "https://e.com/b": ["https://e.com/e"],
    }
    _install_graph(monkeypatch, graph)
    _shrink_queue(monkeypatch, bound=1, batch=1)
    store = CrawlStore(":memory:")
    report = await asyncio.wait_for(
        site_crawler.crawl_site(_spider_config(concurrency=1), timeout=5, store=store), _TIMEOUT
    )
    crawled = _crawled_urls(store, report)
    assert crawled == {f"https://e.com/{p}" for p in ("", "a", "b", "c", "d", "e")}
    assert store.count(report.run_ref.run_id) == 6
    store.close()


@pytest.mark.asyncio
async def test_high_fanout_with_tiny_queue_stays_bounded_and_complete(monkeypatch) -> None:
    # Stress the bounded queue: many workers, a queue of size 1, a homepage that
    # fans out to 30 leaves. All 31 pages crawled exactly once with no hang.
    leaves = [f"https://e.com/{i}" for i in range(30)]
    _install_graph(monkeypatch, {"https://e.com/": leaves})
    _shrink_queue(monkeypatch, bound=1, batch=1)
    store = CrawlStore(":memory:")
    report = await asyncio.wait_for(
        site_crawler.crawl_site(_spider_config(concurrency=4), timeout=5, store=store), _TIMEOUT
    )
    crawled = _crawled_urls(store, report)
    assert crawled == {"https://e.com/", *leaves}
    assert store.count(report.run_ref.run_id) == 31
    store.close()


@pytest.mark.asyncio
async def test_terminates_on_cyclic_graph_without_store(monkeypatch) -> None:
    # A -> B -> A cycle: dedup must stop it, and termination must not depend on
    # the store (the in-memory work source path).
    _install_graph(
        monkeypatch,
        {"https://e.com/": ["https://e.com/b"], "https://e.com/b": ["https://e.com/"]},
    )
    report = await asyncio.wait_for(site_crawler.crawl_site(_spider_config(concurrency=3), timeout=5), _TIMEOUT)
    crawled = sorted(r.url for r in report.results)
    assert crawled == ["https://e.com/", "https://e.com/b"]


@pytest.mark.asyncio
async def test_empty_frontier_terminates_immediately(monkeypatch) -> None:
    # No seeds at all: the producer must see no pending work, no in-flight item,
    # and return — workers cancelled cleanly, empty report.
    report = await asyncio.wait_for(site_crawler.crawl_site(_list_config([], concurrency=2), timeout=5), _TIMEOUT)
    assert report.results == ()


@pytest.mark.asyncio
async def test_worker_discoveries_reach_store_and_complete(monkeypatch) -> None:
    # A link-only page (/c via /a) must be crawled, and every frontier row must
    # transition out of 'pending' through the new claim/mark path — the old
    # driver left them all 'pending'.
    graph = {
        "https://e.com/": ["https://e.com/a", "https://e.com/b"],
        "https://e.com/a": ["https://e.com/c"],
    }
    _install_graph(monkeypatch, graph)
    store = CrawlStore(":memory:")
    report = await asyncio.wait_for(
        site_crawler.crawl_site(_spider_config(concurrency=2), timeout=5, store=store), _TIMEOUT
    )
    crawled = _crawled_urls(store, report)
    assert "https://e.com/c" in crawled
    states = {
        row[0]
        for row in store._conn.execute(
            "SELECT DISTINCT state FROM frontier WHERE run_id = ?", (report.run_ref.run_id,)
        ).fetchall()
    }
    assert states == {"completed"}  # claim -> in_progress -> completed for every URL
    store.close()


def _frontier_count(store: CrawlStore, state: str) -> int:
    return store._conn.execute(
        "SELECT COUNT(*) FROM frontier WHERE run_id = (SELECT run_id FROM runs LIMIT 1) AND state = ?",
        (state,),
    ).fetchone()[0]


@pytest.mark.asyncio
async def test_producer_backpressures_instead_of_draining_frontier(monkeypatch) -> None:
    # With workers stalled inside analyse, the system reaches a fixed point: the
    # producer has claimed only a BOUNDED slice of the frontier (queue + workers
    # + one blocked put) and the rest stays 'pending'. This proves the eager
    # full-frontier drain (F2) is gone AND that the new claim-based producer is
    # what bounds it — the old admit-only driver never moved a row off 'pending',
    # so `in_progress > 0` fails against it.
    concurrency, bound, batch = 2, 2, 1
    urls = [f"https://e.com/{i}" for i in range(20)]
    started = 0
    release = asyncio.Event()

    async def blocking_analyse(url, timeout, options=None):
        nonlocal started
        started += 1
        await release.wait()
        return _payload_with_links(url, [])

    monkeypatch.setattr(site_crawler, "analyse", blocking_analyse)
    _shrink_queue(monkeypatch, bound=bound, batch=batch)
    store = CrawlStore(":memory:")
    run = asyncio.ensure_future(site_crawler.crawl_site(_list_config(urls, concurrency), timeout=5, store=store))
    try:
        # Spin the loop (no real sleep) until the producer is quiescent: blocked
        # on a full queue with every worker parked in analyse. Once all
        # coroutines are suspended nothing changes, so a stable count means the
        # fixed point is reached.
        last, stable = -1, 0
        for _ in range(10_000):
            await asyncio.sleep(0)
            in_progress = _frontier_count(store, "in_progress")
            stable = stable + 1 if (started >= concurrency and in_progress == last > 0) else 0
            last = in_progress
            if stable >= 10:
                break
        assert started == concurrency  # never more than one URL per worker in flight
        assert 0 < last <= bound + concurrency + batch  # in flight is BOUNDED, not the whole frontier
        assert _frontier_count(store, "pending") > 0  # the rest was NOT drained into memory
    finally:
        release.set()
    report = await asyncio.wait_for(run, _TIMEOUT)
    assert _crawled_urls(store, report) == set(urls)
    assert store.count(report.run_ref.run_id) == len(urls)
    store.close()
