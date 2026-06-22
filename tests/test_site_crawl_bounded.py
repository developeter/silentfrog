"""v2.0 V3.2 — bounded in-memory payloads + on-demand reload from store."""

from __future__ import annotations

import pytest

from silentfrog import site_crawler
from silentfrog.crawl_mode import CrawlMode
from silentfrog.crawl_store import CrawlStore
from silentfrog.crawl_types import CrawlPayload
from silentfrog.site_crawl_types import SiteCrawlConfig, SpiderConfig

# Reuse the spider graph: homepage -> /a, /b; /a -> /c (link-only page).
_GRAPH = {
    "https://e.com/": ["https://e.com/a", "https://e.com/b"],
    "https://e.com/a": ["https://e.com/c"],
    "https://e.com/b": [],
    "https://e.com/c": [],
}


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


def _spider_config() -> SiteCrawlConfig:
    return SiteCrawlConfig.from_text(
        base_url="https://e.com",
        spider=SpiderConfig(mode=CrawlMode.SPIDER, respect_robots=False, politeness_delay_ms=0, crawl_concurrency=1),
    )


@pytest.fixture
def graph_analyser(monkeypatch):
    async def fake_analyse(url, timeout, options=None):
        return _payload_with_links(url, _GRAPH.get(url, []))

    monkeypatch.setattr(site_crawler, "analyse", fake_analyse)


@pytest.mark.asyncio
async def test_report_carries_run_ref_when_streaming_to_store(graph_analyser) -> None:
    store = CrawlStore(":memory:")
    report = await site_crawler.crawl_site(_spider_config(), timeout=5, store=store)
    # H2: the store-backed report carries a CrawlRunRef + counts, no results.
    assert report.run_ref is not None
    assert report.run_ref.run_id
    assert report.results == ()
    assert report.crawled_count == 4
    assert store.count(report.run_ref.run_id) == 4
    store.close()


@pytest.mark.asyncio
async def test_live_row_events_strip_payload_beyond_threshold(graph_analyser, monkeypatch) -> None:
    # Force stripping of the LIVE row events after the first 2 (store-backed). The
    # report itself keeps no results (H2); the store holds every payload.
    monkeypatch.setattr(site_crawler, "_PAYLOAD_MEMORY_LIMIT", 2)
    store = CrawlStore(":memory:")
    emitted: list = []

    def on_event(event) -> None:
        if event.get("event") == "row":
            emitted.append(event["result"])

    report = await site_crawler.crawl_site(_spider_config(), timeout=5, store=store, on_event=on_event)

    # Link-following still reached all 4 pages despite stripping — the headline
    # guarantee: /c is reachable only via /a's link.
    assert report.results == ()
    assert store.count(report.run_ref.run_id) == 4

    # The first 2 live events keep their payload (so the GUI model + detail are
    # instant for small crawls); past the threshold they are stripped so the live
    # table model stays flat. The store still has every payload.
    assert sum(1 for r in emitted if r.payload is not None) == 2
    assert sum(1 for r in emitted if r.payload is None) == 2
    reloaded = store.load_payload(report.run_ref.run_id, "https://e.com/c")
    assert reloaded is not None
    assert reloaded["ai_visibility"]["summary"]["score"] == 80
    store.close()


@pytest.mark.asyncio
async def test_no_store_keeps_all_payloads_in_memory(graph_analyser, monkeypatch) -> None:
    # Without a store, nothing is stripped and the report carries inline results.
    monkeypatch.setattr(site_crawler, "_PAYLOAD_MEMORY_LIMIT", 1)
    report = await site_crawler.crawl_site(_spider_config(), timeout=5, store=None)
    assert report.run_ref is None
    assert all(r.payload is not None for r in report.results)


def test_gui_loads_payload_from_run_ref(qtbot, tmp_path) -> None:
    from silentfrog.crawl_run_repository import CrawlRunRef
    from silentfrog.crawl_store import StoredAudit
    from silentfrog.site_crawl_gui import SiteCrawlWindow
    from silentfrog.site_crawl_types import SiteCrawlReport

    # Seed a store on disk with one payload.
    db = tmp_path / "crawl.db"
    store = CrawlStore(db)
    run_id = store.start_run("e.com", "https://e.com/", "spider")
    payload = _payload_with_links("https://e.com/p", [])
    store.save_audit(run_id, StoredAudit(url="https://e.com/p", http_status="200", payload=payload.to_mapping()))
    store.finish_run(run_id)
    store.close()

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._latest_report = SiteCrawlReport.from_run(
        CrawlRunRef(db, run_id), discovered_count=1, crawled_count=1, skipped_count=0, failed_count=0
    )
    loaded = win._load_payload_for_detail("https://e.com/p")
    assert isinstance(loaded, CrawlPayload)
    assert loaded.ai_visibility.summary.score == 80


def test_gui_load_returns_none_without_store(qtbot) -> None:
    from silentfrog.site_crawl_gui import SiteCrawlWindow
    from silentfrog.site_crawl_types import SiteCrawlReport

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._latest_report = SiteCrawlReport.from_results([], discovered_count=0)
    assert win._load_payload_for_detail("https://e.com/p") is None


def test_detail_load_binds_to_report_run_ref_not_stale_field(qtbot, tmp_path) -> None:
    # The detail load must bind via the displayed report's CrawlRunRef, NOT the
    # mutable _crawl_run_id (which a newer crawl may have moved on).
    from silentfrog.crawl_run_repository import CrawlRunRef
    from silentfrog.crawl_store import StoredAudit
    from silentfrog.site_crawl_gui import SiteCrawlWindow
    from silentfrog.site_crawl_types import SiteCrawlReport

    url = "https://e.com/p"
    payload = _payload_with_links(url, [])
    db = tmp_path / "crawl.db"
    store = CrawlStore(db)
    run_id = store.start_run("e.com", "https://e.com/", "spider")
    store.save_audit(run_id, StoredAudit(url=url, http_status="200", payload=payload.to_mapping()))
    store.finish_run(run_id)
    store.close()

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._crawl_run_id = "STALE-OTHER-RUN"  # a newer/other crawl moved the mutable field
    win._latest_report = SiteCrawlReport.from_run(
        CrawlRunRef(db, run_id), discovered_count=1, crawled_count=1, skipped_count=0, failed_count=0
    )
    # Binds via report.run_ref, so the load succeeds despite the stale field.
    assert isinstance(win._load_payload_for_detail(url), CrawlPayload)


def test_recap_build_failure_does_not_escape(qtbot, monkeypatch) -> None:
    # Recap failures must be contained in _handle_report — never propagate.
    from silentfrog import site_crawl_gui as gui_mod
    from silentfrog.site_crawl_gui import SiteCrawlWindow
    from silentfrog.site_crawl_types import SiteCrawlReport

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    report = SiteCrawlReport.from_results([], discovered_count=1)

    def _boom(_report):
        raise RuntimeError("issues unavailable")

    monkeypatch.setattr(gui_mod, "issues_for_site_report", _boom)
    win._update_recap_from_report(report)  # must not raise; recap degrades to empty
