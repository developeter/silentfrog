"""PR-G2 audit behaviour that needs a live loopback site: A6 (gentle-mode
parallelism above the spider default) and D7 (no Google favicon lookup for a
private-network audit)."""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web  # type: ignore[reportMissingImports]
from bs4 import BeautifulSoup

from silentfrog import parsers_meta
from silentfrog import seo_crawler as crawler
from silentfrog.crawl_mode import CrawlMode
from silentfrog.crawl_options import AuditProfile, CrawlOptions
from silentfrog.site_crawl_types import SiteCrawlConfig, SpiderConfig
from silentfrog.site_crawler import crawl_site
from silentfrog.transport import allow_private_network

PAGE = "<html><head><title>T</title>{head}</head><body><h1>H</h1>{body}</body></html>"


@pytest.fixture(autouse=True)
async def _allow_loopback_test_servers():
    with allow_private_network():
        yield


async def test_gentle_parallelism_above_four_raises_the_site_crawl_worker_count(aiohttp_server):
    state = {"now": 0, "peak": 0}

    async def slow_page(_request):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.25)
        state["now"] -= 1
        return web.Response(text=PAGE.format(head="", body=""), content_type="text/html")

    async def home(_request):
        links = "".join(f'<a href="/p{i}">p{i}</a>' for i in range(10))
        return web.Response(text=PAGE.format(head="", body=links), content_type="text/html")

    app = web.Application()
    app.router.add_get("/", home)
    app.router.add_get("/{name}", slow_page)
    server = await aiohttp_server(app)
    options = CrawlOptions.from_ui(
        gentle_mode=True, max_parallel=8, respect_crawl_delay=False, profile=AuditProfile.LIGHTWEIGHT
    )
    config = SiteCrawlConfig.from_text(
        base_url=str(server.make_url("/")),
        crawl_options=options,
        spider=SpiderConfig(mode=CrawlMode.SPIDER, politeness_delay_ms=0, max_urls=30),
    )

    await crawl_site(config, timeout=5)

    # 4 is the spider default that used to cap the crawl whatever the setting said (A6).
    assert 4 < state["peak"] <= 8


async def test_private_network_audit_never_asks_google_for_the_favicon(aiohttp_server, monkeypatch):
    fetched: list[str] = []

    async def record(url: str) -> str:
        fetched.append(url)
        return url

    monkeypatch.setattr(parsers_meta, "_to_data_uri", record)

    async def home(_request):
        return web.Response(text=PAGE.format(head="", body=""), content_type="text/html")

    app = web.Application()
    app.router.add_get("/", home)
    server = await aiohttp_server(app)
    options = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, allow_private_network=True)

    await crawler.analyse(str(server.make_url("/")), timeout=5, options=options)

    assert fetched and all("google.com" not in url for url in fetched)
    assert fetched[0].endswith("/favicon.ico")


async def test_public_audit_keeps_the_google_favicon_fallback(monkeypatch):
    fetched: list[str] = []

    async def record(url: str) -> str:
        fetched.append(url)
        return url

    monkeypatch.setattr(parsers_meta, "_to_data_uri", record)
    soup = BeautifulSoup(PAGE.format(head="", body=""), "html.parser")

    await parsers_meta._make_serp_snippet(soup, "https://example.com/")

    assert fetched == ["https://www.google.com/s2/favicons?sz=48&domain=example.com"]
