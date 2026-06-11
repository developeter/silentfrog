"""Integration of the V1 fetcher strategy into the crawl orchestrator."""

from __future__ import annotations

import pytest

from silentfrog import seo_crawler
from silentfrog.crawl_options import CrawlOptions
from silentfrog.fetchers import FetchResult
from silentfrog.http_client import HttpResponse


def test_stealth_enabled_reads_options_flag() -> None:
    opts = CrawlOptions.from_ui(gentle_mode=False, max_parallel=2, use_stealth=True)
    assert seo_crawler._stealth_enabled(opts) is True


def test_stealth_disabled_by_default() -> None:
    opts = CrawlOptions.default()
    assert seo_crawler._stealth_enabled(opts) is False


def test_stealth_enabled_via_env(monkeypatch) -> None:
    monkeypatch.setenv("SILENTFROG_STEALTH_ENABLE", "1")
    opts = CrawlOptions.default()
    assert seo_crawler._stealth_enabled(opts) is True


@pytest.mark.asyncio
async def test_strategy_fetch_adapts_result_to_http_response(monkeypatch) -> None:
    async def _stub_strategy_fetch(self, request):
        return FetchResult(
            body="<html>ok</html>",
            status=200,
            final_url="https://example.com/final",
            headers={"X-Test": "1"},
            ttfb_ms=12.0,
            total_ms=34.0,
            backend="aiohttp",
        )

    monkeypatch.setattr("silentfrog.fetchers.FetchStrategy.fetch", _stub_strategy_fetch)
    resp = await seo_crawler._strategy_fetch("https://example.com/", 15, {"User-Agent": "x"}, CrawlOptions.default())
    assert isinstance(resp, HttpResponse)
    assert resp.status == 200
    assert resp.url == "https://example.com/final"
    assert resp.body == "<html>ok</html>"
    assert resp.ttfb_ms == 12.0
