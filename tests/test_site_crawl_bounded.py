"""v2.0 V3.2 — bounded in-memory payloads + on-demand reload from store."""

from __future__ import annotations

from dataclasses import replace

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
async def test_report_carries_run_id_when_streaming_to_store(graph_analyser) -> None:
    store = CrawlStore(":memory:")
    report = await site_crawler.crawl_site(_spider_config(), timeout=5, store=store)
    assert report.run_id
    assert store.count(report.run_id) == 4
    store.close()


@pytest.mark.asyncio
async def test_payloads_stripped_beyond_threshold_but_links_still_followed(graph_analyser, monkeypatch) -> None:
    # Force stripping after the first 2 results.
    monkeypatch.setattr(site_crawler, "_PAYLOAD_MEMORY_LIMIT", 2)
    store = CrawlStore(":memory:")
    report = await site_crawler.crawl_site(_spider_config(), timeout=5, store=store)

    # Link-following still reached all 4 pages despite stripping — the
    # headline guarantee: /c is reachable only via /a's link.
    crawled = {r.url for r in report.results}
    assert crawled == {"https://e.com/", "https://e.com/a", "https://e.com/b", "https://e.com/c"}

    # First 2 in-memory results keep their payload; the rest are stripped.
    with_payload = sum(1 for r in report.results if r.payload is not None)
    without_payload = sum(1 for r in report.results if r.payload is None)
    assert with_payload == 2
    assert without_payload == 2

    # But the store has every payload — a stripped one reloads from disk.
    stripped = next(r for r in report.results if r.payload is None)
    reloaded = store.load_payload(report.run_id, stripped.url)
    assert reloaded is not None
    assert reloaded["ai_visibility"]["summary"]["score"] == 80
    store.close()


@pytest.mark.asyncio
async def test_no_store_keeps_all_payloads_in_memory(graph_analyser, monkeypatch) -> None:
    # Without a store, nothing is stripped (backward-compatible).
    monkeypatch.setattr(site_crawler, "_PAYLOAD_MEMORY_LIMIT", 1)
    report = await site_crawler.crawl_site(_spider_config(), timeout=5, store=None)
    assert all(r.payload is not None for r in report.results)


def test_gui_loads_stripped_payload_from_store(qtbot, tmp_path) -> None:
    from silentfrog.crawl_store import StoredAudit
    from silentfrog.site_crawl_gui import SiteCrawlWindow
    from silentfrog.site_crawl_types import SiteCrawlReport, SiteCrawlResult

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
    win._crawl_store_path = str(db)
    stripped = replace(SiteCrawlResult.from_payload("https://e.com/p", payload), payload=None)
    win._latest_report = SiteCrawlReport.from_results([stripped], discovered_count=1, run_id=run_id)
    loaded = win._load_payload_for_detail("https://e.com/p")
    assert isinstance(loaded, CrawlPayload)
    assert loaded.ai_visibility.summary.score == 80


def test_gui_load_returns_none_without_store(qtbot) -> None:
    from silentfrog.site_crawl_gui import SiteCrawlWindow
    from silentfrog.site_crawl_types import SiteCrawlReport

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._crawl_store_path = ""
    win._latest_report = SiteCrawlReport.from_results([], discovered_count=0, run_id="r1")
    assert win._load_payload_for_detail("https://e.com/p") is None


def test_detail_load_binds_to_report_run_not_stale_field(qtbot, tmp_path) -> None:
    # The detail load must bind via the displayed report's run_id, NOT the
    # mutable _crawl_run_id (which a newer crawl may have moved on).
    from silentfrog.crawl_store import StoredAudit
    from silentfrog.site_crawl_gui import SiteCrawlWindow
    from silentfrog.site_crawl_types import SiteCrawlReport, SiteCrawlResult

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
    win._crawl_store_path = str(db)
    win._crawl_run_id = "STALE-OTHER-RUN"  # a newer/other crawl moved the mutable field
    stripped = replace(SiteCrawlResult.from_payload(url, payload), payload=None)
    win._latest_report = SiteCrawlReport.from_results([stripped], discovered_count=1, run_id=run_id)
    # Binds via report.run_id, so the load succeeds despite the stale field.
    assert isinstance(win._load_payload_for_detail(url), CrawlPayload)


def test_recap_repository_failure_does_not_escape(qtbot, monkeypatch) -> None:
    # Recap failures must be contained in _handle_report — never propagate.
    from silentfrog.site_crawl_gui import SiteCrawlWindow
    from silentfrog.site_crawl_types import SiteCrawlReport, SiteCrawlResult

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    payload = _payload_with_links("https://e.com/p", [])
    stripped = replace(SiteCrawlResult.from_payload("https://e.com/p", payload), payload=None)
    report = SiteCrawlReport.from_results([stripped], discovered_count=1, run_id="r1")

    def _boom(_report):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(win, "_open_run_repository", _boom)
    win._update_recap_from_report(report)  # must not raise; falls back to in-memory
