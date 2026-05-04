from __future__ import annotations

from aiohttp import web  # type: ignore[reportMissingImports]
import pytest

from silentfrog.crawl_types import CrawlPayload  # type: ignore[reportMissingImports]
from silentfrog.site_crawl_types import SiteCrawlConfig  # type: ignore[reportMissingImports]
from silentfrog import site_crawler  # type: ignore[reportMissingImports]


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
            "serp": {"title": title, "description": "", "url": url, "site_name": "", "breadcrumb": "", "favicon": ""},
            "serp_audit": {},
            "keywords": [],
            "content_quality": {},
            "ai_visibility": {"summary": {"verdict": "Needs work", "good_count": 1, "warning_count": 1, "critical_count": 0}, "checks": []},
            "performance": {"summary": {"verdict": "Good"}},
            "social": {},
        }
    )


@pytest.mark.asyncio
async def test_resolve_site_urls_parses_sitemap_index_filters_and_caps(aiohttp_server):
    async def index(_):
        body = f"""<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>{server.make_url('/sitemap-products.xml')}</loc></sitemap>
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

    urls = await site_crawler.resolve_site_urls(config, timeout=5)

    assert urls == [str(server.make_url("/design/table/"))]


@pytest.mark.asyncio
async def test_resolve_site_urls_discovers_sitemap_from_robots(aiohttp_server):
    async def robots(_):
        return web.Response(text=f"Sitemap: {server.make_url('/branch-sitemap.xml')}\n")

    async def sitemap(_):
        body = f"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>{server.make_url('/design/table/')}</loc></url>
            <url><loc>{server.make_url('/news/story/')}</loc></url>
        </urlset>"""
        return web.Response(text=body, content_type="application/xml")

    app = web.Application()
    app.router.add_get("/robots.txt", robots)
    app.router.add_get("/branch-sitemap.xml", sitemap)
    server = await aiohttp_server(app)

    config = SiteCrawlConfig.from_text(base_url=str(server.make_url("/")), include_text="/design/")

    urls = await site_crawler.resolve_site_urls(config, timeout=5)

    assert urls == [str(server.make_url("/design/table/"))]


@pytest.mark.asyncio
async def test_resolve_site_urls_discovers_common_sitemap_path(aiohttp_server):
    async def sitemap(_):
        body = f"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>{server.make_url('/page-one/')}</loc></url>
        </urlset>"""
        return web.Response(text=body, content_type="application/xml")

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)
    server = await aiohttp_server(app)
    config = SiteCrawlConfig.from_text(base_url=str(server.make_url("/")))

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
async def test_crawl_site_marks_pending_urls_skipped_when_cancelled(monkeypatch):
    cancel = __import__("threading").Event()
    cancel.set()

    async def fake_analyse(url: str, timeout: int, options=None):
        return _payload(url)

    monkeypatch.setattr(site_crawler, "analyse", fake_analyse)
    config = SiteCrawlConfig.from_text(
        base_url="https://example.com",
        url_list_text="https://example.com/a\nhttps://example.com/b",
    )

    report = await site_crawler.crawl_site(config, cancel_event=cancel)

    assert {result.status for result in report.results} == {"skipped"}
