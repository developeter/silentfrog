"""v2.0 PR-9 (H3) — cooperative cancellation + resume + partial-run persistence.

These tests pin the cancel/resume contract end-to-end, not just store internals:

- **cooperative cancellation** — once cancel is requested the producer stops
  claiming, in-flight requests finish, and claimed-but-unstarted URLs are
  abandoned in ``in_progress`` (never forced to a terminal state);
- **partial-run persistence** — a cancelled run is flushed, marked ``cancelled``,
  and stays fully queryable through its ``CrawlRunRef``;
- **resume** — ``in_progress`` rows return to ``pending`` and the crawl re-runs
  ONLY its unfinished URLs, with no duplicate audits;
- **deadlock prevention under cancel** — cancelling while workers are stalled and
  the bounded queue is full must still terminate.

Deterministic: zero politeness delay, no real sleeps, every crawl wrapped in
``asyncio.wait_for`` so a hang trips the ceiling instead of stalling the suite.
"""

from __future__ import annotations

import asyncio
import threading
from collections import Counter

import pytest

from silentfrog import site_crawler
from silentfrog.crawl_mode import CrawlMode
from silentfrog.crawl_run_repository import CrawlRunRef
from silentfrog.crawl_store import CrawlStore
from silentfrog.crawl_types import CrawlPayload
from silentfrog.site_crawl_types import SiteCrawlConfig, SpiderConfig

_TIMEOUT = 10.0  # generous wall-clock ceiling; a deadlock trips it, real runs finish instantly


def _payload(url: str) -> CrawlPayload:
    # No links: the frontier equals the seed set, so the cancel/resume split is
    # deterministic regardless of crawl mode.
    return CrawlPayload.from_raw(
        {
            "meta": [["title", "T", "1"], ["description", "d", "1"]],
            "headers": [["h1", "T"]],
            "images": [],
            "links": [],
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


def _list_config(urls: list[str], concurrency: int = 1) -> SiteCrawlConfig:
    spider = SpiderConfig(
        mode=CrawlMode.LIST,
        respect_robots=False,
        politeness_delay_ms=0,
        crawl_concurrency=concurrency,
    )
    return SiteCrawlConfig.from_text(
        base_url="https://e.com", url_list_text="\n".join(urls), limit=10_000, spider=spider
    )


def _frontier_states(store: CrawlStore, run_id: str) -> Counter:
    return Counter(
        row[0] for row in store._conn.execute("SELECT state FROM frontier WHERE run_id = ?", (run_id,)).fetchall()
    )


def _run_status(store: CrawlStore, run_id: str) -> str:
    return store._conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0]


def _seeds(count: int) -> list[str]:
    return [f"https://e.com/{i}" for i in range(count)]


def _cancel_after(cancel: threading.Event, analysed: Counter, limit: int):
    """A fake analyse that records each call and trips ``cancel`` once ``limit``
    URLs have been analysed (the limit-th URL still completes)."""

    async def fake_analyse(url, timeout, options=None):
        analysed[url] += 1
        if sum(analysed.values()) >= limit:
            cancel.set()
        return _payload(url)

    return fake_analyse


@pytest.mark.asyncio
async def test_cancel_leaves_inflight_in_progress_and_persists_partial_run(monkeypatch, tmp_path) -> None:
    # Single worker, 5 seeds: the producer claims all 5 (pending -> in_progress)
    # before the worker starts, so when cancel fires after 2 completions the
    # remaining 3 claims are abandoned IN PLACE (in_progress), never marked
    # terminal. A file-backed store so the partial run is reachable from a fresh
    # read connection (each ``:memory:`` connection is a separate database).
    cancel = threading.Event()
    analysed: Counter = Counter()
    monkeypatch.setattr(site_crawler, "analyse", _cancel_after(cancel, analysed, limit=2))
    store = CrawlStore(tmp_path / "crawl.db")

    report = await asyncio.wait_for(
        site_crawler.crawl_site(_list_config(_seeds(5)), timeout=5, cancel_event=cancel, store=store), _TIMEOUT
    )
    run_id = report.run_ref.run_id

    states = _frontier_states(store, run_id)
    assert states == Counter({"completed": 2, "in_progress": 3})  # abandoned claims stay in_progress
    assert store.count(run_id) == 2  # only completed URLs wrote an audit
    assert _run_status(store, run_id) == "cancelled"  # finished as cancelled, not completed

    # Partial run is fully queryable through its CrawlRunRef (separate read-only
    # connection), exactly as the GUI/exporters would reach it after a stop.
    with CrawlRunRef(store.db_path, run_id).open() as repo:
        assert repo.count() == 2
        assert len(list(repo.stream_results())) == 2
    store.close()


@pytest.mark.asyncio
async def test_resume_requeues_in_progress_and_completes_without_dupes(monkeypatch) -> None:
    cancel = threading.Event()
    analysed: Counter = Counter()
    monkeypatch.setattr(site_crawler, "analyse", _cancel_after(cancel, analysed, limit=2))
    store = CrawlStore(":memory:")
    config = _list_config(_seeds(5))

    cancelled = await asyncio.wait_for(
        site_crawler.crawl_site(config, timeout=5, cancel_event=cancel, store=store), _TIMEOUT
    )
    run_id = cancelled.run_ref.run_id
    assert _frontier_states(store, run_id)["in_progress"] == 3

    # Resume the SAME run with no active cancel: in_progress -> pending, then the
    # remaining URLs are crawled to completion.
    resumed = await asyncio.wait_for(
        site_crawler.crawl_site(config, timeout=5, store=store, resume_run_id=run_id), _TIMEOUT
    )

    assert resumed.run_ref.run_id == run_id  # same run, not a fresh one
    assert _frontier_states(store, run_id) == Counter({"completed": 5})
    assert _run_status(store, run_id) == "completed"
    assert store.count(run_id) == 5  # exactly one audit per URL — no duplicates
    assert all(count == 1 for count in analysed.values())  # every URL analysed once across both sessions
    store.close()


@pytest.mark.asyncio
async def test_resume_does_not_reanalyse_completed_urls(monkeypatch) -> None:
    # The two URLs completed before cancel must NOT be analysed again on resume —
    # resume re-runs ONLY unfinished URLs.
    cancel = threading.Event()
    analysed: Counter = Counter()
    monkeypatch.setattr(site_crawler, "analyse", _cancel_after(cancel, analysed, limit=2))
    store = CrawlStore(":memory:")
    config = _list_config(_seeds(5))

    cancelled = await asyncio.wait_for(
        site_crawler.crawl_site(config, timeout=5, cancel_event=cancel, store=store), _TIMEOUT
    )
    run_id = cancelled.run_ref.run_id
    completed_before = {row.url for row in store.iter_lightweight(run_id, 0, 10_000)}
    assert len(completed_before) == 2

    await asyncio.wait_for(site_crawler.crawl_site(config, timeout=5, store=store, resume_run_id=run_id), _TIMEOUT)

    # Each completed-before URL was analysed exactly once (session 1 only).
    assert all(analysed[url] == 1 for url in completed_before)
    assert sum(analysed.values()) == 5  # 2 in session 1 + 3 on resume, none repeated


@pytest.mark.asyncio
async def test_cancel_during_backpressure_terminates_without_deadlock(monkeypatch) -> None:
    # Workers stalled in analyse, the bounded queue full: cancelling here must not
    # hang. A regression that returns from the producer while workers are mid-
    # request (then cancels them) or mishandles the in-flight drain trips wait_for.
    concurrency, bound, batch = 2, 1, 1
    cancel = threading.Event()
    started = 0
    release = asyncio.Event()

    async def blocking_analyse(url, timeout, options=None):
        nonlocal started
        started += 1
        await release.wait()
        return _payload(url)

    monkeypatch.setattr(site_crawler, "analyse", blocking_analyse)
    monkeypatch.setattr(site_crawler, "_WORK_QUEUE_BOUND", bound)
    monkeypatch.setattr(site_crawler, "_CLAIM_BATCH", batch)
    store = CrawlStore(":memory:")
    run = asyncio.ensure_future(
        site_crawler.crawl_site(_list_config(_seeds(20), concurrency), timeout=5, cancel_event=cancel, store=store)
    )

    # Spin (no real sleep) until both workers are parked in analyse and the
    # producer is blocked on the full queue — the backpressure fixed point.
    for _ in range(10_000):
        await asyncio.sleep(0)
        if started >= concurrency:
            break
    assert started == concurrency
    cancel.set()
    release.set()

    report = await asyncio.wait_for(run, _TIMEOUT)  # terminates despite the stall
    run_id = report.run_ref.run_id
    states = _frontier_states(store, run_id)
    assert 0 < states["completed"] < 20  # cancel took effect: some done, not all
    assert states["pending"] + states["in_progress"] > 0  # remainder is resumable
    assert store.count(run_id) == states["completed"]  # audits match completed rows
    store.close()
