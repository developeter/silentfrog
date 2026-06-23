from __future__ import annotations

import dataclasses

import pytest
from aiohttp import web  # type: ignore[reportMissingImports]

from silentfrog import site_crawler  # type: ignore[reportMissingImports]
from silentfrog.crawl_options import CrawlOptions  # type: ignore[reportMissingImports]
from silentfrog.crawl_types import CrawlPayload  # type: ignore[reportMissingImports]
from silentfrog.site_crawl_types import SiteCrawlConfig  # type: ignore[reportMissingImports]
from silentfrog.transport import allow_private_network, open_crawl_session  # type: ignore[reportMissingImports]


def _payload(url: str, title: str = "Example Title") -> CrawlPayload:
    return CrawlPayload.from_raw(
        {
            "meta": [["title", title, str(len(title))], ["description", "A useful page description.", "26"]],
            "headers": [["h1", title]],
            "images": [],
            "links": [],
            "schema": {"summary": {"total": 1, "by_type": {"WebPage": 1}}, "blocks": [], "issues": []},
            "canonical": {"target": url, "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": [url], "hops": 0, "final_status": "200", "final_url": url, "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": "index, follow",
            "hreflang": [],
            "ai_crawl": [],
            "serp": {
                "title": title,
                "description": "",
                "url": url,
                "site_name": "",
                "breadcrumb": "",
                "favicon": "",
            },
            "serp_audit": {},
            "keywords": [],
            "content_quality": {},
            "ai_visibility": {
                "summary": {
                    "verdict": "Needs work",
                    "good_count": 1,
                    "warning_count": 1,
                    "critical_count": 0,
                },
                "checks": [],
            },
            "performance": {"summary": {"verdict": "Good"}},
            "social": {},
        }
    )


def test_site_crawl_result_uses_fetch_status_before_redirect_probe_status() -> None:
    url = "https://example.com/page"
    payload = CrawlPayload.from_raw(
        {
            **_payload(url).to_mapping(),
            "redirect": {"chain": [url], "hops": 0, "final_status": "403", "loop": False},
            "performance": {"status": 200, "summary": {"verdict": "Good"}},
        }
    )

    result = site_crawler.SiteCrawlResult.from_payload(url, payload)

    assert result.status == "200"
    assert result.redirect_status == "403"
    assert result.row()[1:4] == ["200", "403", url]


@pytest.mark.asyncio
async def test_resolve_site_urls_parses_sitemap_index_filters_and_caps(aiohttp_server):
    async def index(_):
        body = f"""<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>{server.make_url("/sitemap-products.xml")}</loc></sitemap>
        </sitemapindex>"""
        return web.Response(text=body, content_type="application/xml")

    async def sitemap(_):
        base = str(server.make_url("/"))
        body = f"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>{base}design/table/</loc><image:image xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"><image:loc>{base}asset.jpg</image:loc></image:image></url>
            <url><loc>{base}design/private/</loc></url>
            <url><loc>{base}news/story/</loc></url>
        </urlset>"""
        return web.Response(text=body, content_type="application/xml")

    app = web.Application()
    app.router.add_get("/sitemap.xml", index)
    app.router.add_get("/sitemap-products.xml", sitemap)
    server = await aiohttp_server(app)

    config = SiteCrawlConfig.from_text(
        base_url=str(server.make_url("/")),
        sitemap_url=str(server.make_url("/sitemap.xml")),
        include_text="/design/",
        exclude_text="private",
        limit=1,
    )

    # The sitemap is served from a loopback test server; opt past the SSRF guard.
    with allow_private_network():
        urls = await site_crawler.resolve_site_urls(config, timeout=5)

    assert urls == [str(server.make_url("/design/table/"))]


@pytest.mark.asyncio
async def test_resolve_site_urls_discovers_sitemap_from_robots(aiohttp_server):
    async def robots(_):
        return web.Response(text=f"Sitemap: {server.make_url('/branch-sitemap.xml')}\n")

    async def sitemap(_):
        body = f"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>{server.make_url("/design/table/")}</loc></url>
            <url><loc>{server.make_url("/news/story/")}</loc></url>
        </urlset>"""
        return web.Response(text=body, content_type="application/xml")

    app = web.Application()
    app.router.add_get("/robots.txt", robots)
    app.router.add_get("/branch-sitemap.xml", sitemap)
    server = await aiohttp_server(app)

    config = SiteCrawlConfig.from_text(base_url=str(server.make_url("/")), include_text="/design/")

    with allow_private_network():
        urls = await site_crawler.resolve_site_urls(config, timeout=5)

    assert urls == [str(server.make_url("/design/table/"))]


@pytest.mark.asyncio
async def test_resolve_site_urls_discovers_common_sitemap_path(aiohttp_server):
    async def sitemap(_):
        body = f"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>{server.make_url("/page-one/")}</loc></url>
        </urlset>"""
        return web.Response(text=body, content_type="application/xml")

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)
    server = await aiohttp_server(app)
    config = SiteCrawlConfig.from_text(base_url=str(server.make_url("/")))

    with allow_private_network():
        urls = await site_crawler.resolve_site_urls(config, timeout=5)

    assert urls == [str(server.make_url("/page-one/"))]


@pytest.mark.asyncio
async def test_resolve_site_urls_uses_base_url_when_sitemap_detection_finds_nothing(monkeypatch):
    async def no_sitemaps(*_args, **_kwargs):
        return []

    monkeypatch.setattr(site_crawler, "_discover_sitemap_urls", no_sitemaps)
    config = SiteCrawlConfig.from_text(base_url="https://example.com")

    urls = await site_crawler.resolve_site_urls(config, timeout=5)

    assert urls == ["https://example.com/"]


@pytest.mark.asyncio
async def test_crawl_site_posture_wraps_discovery(monkeypatch):
    # H7 follow-up: the crawl's TLS/SSRF opt-ins must wrap the whole
    # orchestration, so seed / robots / sitemap discovery runs under the
    # configured posture — not only analyse(). Spy the posture the seam would
    # apply at the very first discovery step (_build_seeds).
    seen: dict[str, object] = {}

    async def spy_build_seeds(config, timeout):
        async with open_crawl_session() as session:
            seen["allow_private"] = session.connector._allow_private
            seen["tls_verified"] = session.connector._ssl is not False
        return []  # no seeds -> the crawl ends immediately

    monkeypatch.setattr(site_crawler, "_build_seeds", spy_build_seeds)

    # Secure defaults: discovery vets SSRF and verifies TLS.
    await site_crawler.crawl_site(SiteCrawlConfig.from_text(base_url="https://example.com"))
    assert seen == {"allow_private": False, "tls_verified": True}

    # Explicit opt-ins reach discovery, not only the per-URL analyse().
    opts = dataclasses.replace(CrawlOptions.default(), allow_insecure_tls=True, allow_private_network=True)
    await site_crawler.crawl_site(SiteCrawlConfig.from_text(base_url="https://example.com", crawl_options=opts))
    assert seen == {"allow_private": True, "tls_verified": False}


@pytest.mark.asyncio
async def test_crawl_site_returns_cached_payloads_and_failed_rows(monkeypatch):
    ok_url = "https://example.com/ok"
    fail_url = "https://example.com/fail"
    events: list[dict] = []

    async def fake_analyse(url: str, timeout: int, options=None):
        if url == fail_url:
            raise RuntimeError("boom")
        return _payload(url, title="OK")

    monkeypatch.setattr(site_crawler, "analyse", fake_analyse)
    config = SiteCrawlConfig.from_text(
        base_url="https://example.com",
        url_list_text=f"{ok_url}\n{fail_url}",
        limit=10,
    )

    report = await site_crawler.crawl_site(config, timeout=5, on_event=events.append)

    assert report.discovered_count == 2
    assert report.failed_count == 1
    assert report.results[0].payload is not None
    assert report.results[1].error == "boom"
    assert any(event["event"] == "discovered" for event in events)
    assert sum(1 for event in events if event["event"] == "row") == 2


@pytest.mark.asyncio
async def test_crawl_site_cancelled_before_start_processes_nothing(monkeypatch):
    # PR-9 cooperative cancellation: a crawl cancelled before any URL is claimed
    # stops cleanly with NO rows processed (the old behavior marked every pending
    # URL "skipped"). A regression that ignores cancel would analyse a + b and
    # produce two rows, failing this guard.
    cancel = __import__("threading").Event()
    cancel.set()
    analysed: list[str] = []

    async def fake_analyse(url: str, timeout: int, options=None):
        analysed.append(url)
        return _payload(url)

    monkeypatch.setattr(site_crawler, "analyse", fake_analyse)
    config = SiteCrawlConfig.from_text(
        base_url="https://example.com",
        url_list_text="https://example.com/a\nhttps://example.com/b",
    )

    report = await site_crawler.crawl_site(config, cancel_event=cancel)

    assert report.results == ()
    assert analysed == []
