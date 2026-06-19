"""v2.0 V3 — the headline test: the crawl actually follows links.

Proves the spider discovers pages that are NOT in any seed/sitemap by
following <a href> links, respects robots disallow, stays on-host, and
streams to the V2 store.
"""

from __future__ import annotations

import pytest

from silentfrog import site_crawler
from silentfrog.crawl_mode import CrawlMode
from silentfrog.crawl_store import CrawlStore
from silentfrog.crawl_types import CrawlPayload
from silentfrog.site_crawl_types import SiteCrawlConfig, SpiderConfig

# A small site graph. The homepage links to /a, /b and an off-host page.
# /a links to /c — a page reachable ONLY by following links (it is in no
# seed and no sitemap). /b links back to /a (already seen).
_GRAPH = {
    "https://e.com/": ["https://e.com/a", "https://e.com/b", "https://other.com/x"],
    "https://e.com/a": ["https://e.com/c"],
    "https://e.com/b": ["https://e.com/a"],
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
            "content_quality": {},
            "ai_visibility": {"summary": {"verdict": "OK", "score": 80}, "checks": []},
            "performance": {"summary": {"verdict": "Good"}},
            "social": {},
        }
    )


def _spider_config(**spider_kw) -> SiteCrawlConfig:
    spider = SpiderConfig(
        mode=CrawlMode.SPIDER,
        respect_robots=spider_kw.pop("respect_robots", False),
        politeness_delay_ms=0,
        crawl_concurrency=spider_kw.pop("crawl_concurrency", 2),
        **spider_kw,
    )
    return SiteCrawlConfig.from_text(base_url="https://e.com", limit=1000, spider=spider)


def _install_graph_analyser(monkeypatch) -> None:
    async def fake_analyse(url, timeout, options=None):
        return _payload_with_links(url, _GRAPH.get(url, []))

    monkeypatch.setattr(site_crawler, "analyse", fake_analyse)


@pytest.mark.asyncio
async def test_spider_follows_links_to_pages_not_in_seed(monkeypatch) -> None:
    _install_graph_analyser(monkeypatch)
    report = await site_crawler.crawl_site(_spider_config(), timeout=5)
    crawled = {r.url for r in report.results}
    # /c is reachable ONLY by following /a's link — the whole-site fix.
    assert crawled == {
        "https://e.com/",
        "https://e.com/a",
        "https://e.com/b",
        "https://e.com/c",
    }


@pytest.mark.asyncio
async def test_spider_does_not_follow_offsite_links(monkeypatch) -> None:
    _install_graph_analyser(monkeypatch)
    report = await site_crawler.crawl_site(_spider_config(), timeout=5)
    assert all("other.com" not in r.url for r in report.results)


@pytest.mark.asyncio
async def test_spider_respects_max_depth(monkeypatch) -> None:
    _install_graph_analyser(monkeypatch)
    # Depth 1: homepage (0) + its direct links /a, /b (1). /c is at depth 2
    # (homepage -> /a -> /c) and must be excluded.
    report = await site_crawler.crawl_site(_spider_config(max_depth=1), timeout=5)
    crawled = {r.url for r in report.results}
    assert crawled == {"https://e.com/", "https://e.com/a", "https://e.com/b"}
    assert "https://e.com/c" not in crawled


@pytest.mark.asyncio
async def test_spider_respects_robots_disallow(monkeypatch) -> None:
    _install_graph_analyser(monkeypatch)

    class _FakeRobots:
        def __init__(self, *a, **k) -> None: ...

        async def allows(self, url: str) -> bool:
            return "/b" not in url

    monkeypatch.setattr(site_crawler, "RobotsCache", _FakeRobots)
    report = await site_crawler.crawl_site(_spider_config(respect_robots=True), timeout=5)
    crawled = {r.url for r in report.results}
    assert "https://e.com/b" not in crawled  # robots-disallowed, never enqueued
    assert "https://e.com/a" in crawled


@pytest.mark.asyncio
async def test_spider_streams_to_store(monkeypatch) -> None:
    _install_graph_analyser(monkeypatch)
    store = CrawlStore(":memory:")
    await site_crawler.crawl_site(_spider_config(), timeout=5, store=store)
    run_id = store._conn.execute("SELECT run_id FROM runs LIMIT 1").fetchone()[0]
    assert store.count(run_id) == 4
    # Payload round-trips through the store's zlib blob.
    payload = store.load_payload(run_id, "https://e.com/c")
    assert payload is not None
    assert payload["ai_visibility"]["summary"]["score"] == 80
    store.close()


@pytest.mark.asyncio
async def test_spider_persists_discovery_edges_for_link_graph(monkeypatch) -> None:
    # F4 regression: the parent → child relationship must reach the store so
    # the link graph has real edges (not an orphan dump). /c is reachable
    # only via /a, so its edge proves discovery threading end to end.
    _install_graph_analyser(monkeypatch)
    store = CrawlStore(":memory:")
    await site_crawler.crawl_site(_spider_config(), timeout=5, store=store)
    run_id = store._conn.execute("SELECT run_id FROM runs LIMIT 1").fetchone()[0]

    edges = {(source, url) for url, source, _score in store.iter_graph_inputs(run_id) if source}
    assert ("https://e.com/", "https://e.com/a") in edges
    assert ("https://e.com/", "https://e.com/b") in edges
    assert ("https://e.com/a", "https://e.com/c") in edges
    roots = {url for url, source, _score in store.iter_graph_inputs(run_id) if not source}
    assert roots == {"https://e.com/"}  # only the seed has no discovering page

    from silentfrog.link_graph import GraphInput, build_link_graph

    graph = build_link_graph([GraphInput(*row) for row in store.iter_graph_inputs(run_id)], root_url="https://e.com/")
    assert len(graph.edges) == 3
    assert graph.orphans == ()  # every non-root page now has an inbound edge
    store.close()


@pytest.mark.asyncio
async def test_discovery_edge_survives_url_normalization(monkeypatch) -> None:
    # The frontier admission and the saved audit must key on the SAME
    # normalized URL or the graph JOIN silently drops the edge. A link with a
    # '#frag' normalizes the fragment away; the edge must still appear.
    graph = {"https://e.com/": ["https://e.com/p#frag"], "https://e.com/p": []}

    async def fake_analyse(url, timeout, options=None):
        return _payload_with_links(url, graph.get(url, []))

    monkeypatch.setattr(site_crawler, "analyse", fake_analyse)
    store = CrawlStore(":memory:")
    await site_crawler.crawl_site(_spider_config(), timeout=5, store=store)
    run_id = store._conn.execute("SELECT run_id FROM runs LIMIT 1").fetchone()[0]
    edges = {(source, url) for url, source, _score in store.iter_graph_inputs(run_id) if source}
    assert ("https://e.com/", "https://e.com/p") in edges
    store.close()


@pytest.mark.asyncio
async def test_hybrid_is_the_default_mode_for_base_url_only() -> None:
    config = SiteCrawlConfig.from_text(base_url="https://e.com")
    assert config.spider.mode is CrawlMode.HYBRID


@pytest.mark.asyncio
async def test_list_mode_is_auto_selected_for_explicit_urls() -> None:
    config = SiteCrawlConfig.from_text(base_url="https://e.com", url_list_text="https://e.com/a\nhttps://e.com/b")
    assert config.spider.mode is CrawlMode.LIST
