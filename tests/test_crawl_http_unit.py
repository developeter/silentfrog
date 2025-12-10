from __future__ import annotations

import asyncio
from dataclasses import replace
import pytest

from silentfrog import crawl_http  # type: ignore[reportMissingImports]
from silentfrog.crawl_options import CrawlOptions  # type: ignore[reportMissingImports]


def test_host_key_normalizes() -> None:
    # Host key should normalize scheme/case to a consistent lowercased host.
    assert crawl_http._host_key("HTTP://Example.COM/path") == "example.com"
    assert crawl_http._host_key("example.com") == "example.com"


def test_host_semaphore_reuse() -> None:
    # Semaphore per host should be reused to enforce concurrency cap.
    crawl_http._HOST_LIMITERS.clear()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        sem1 = loop.run_until_complete(crawl_http._get_host_semaphore("https://example.com", 2))
        sem2 = loop.run_until_complete(crawl_http._get_host_semaphore("https://example.com", 2))
        assert sem1 is sem2
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


@pytest.mark.asyncio
async def test_link_status_backoff(monkeypatch) -> None:
    # Backoff should retry once on 429/403 and sleep the configured delay.
    calls: list[int] = []
    sleeps: list[float] = []

    async def fake_head_status(_session, _url, _timeout):
        return calls.pop(0)

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    monkeypatch.setattr(crawl_http, "head_status", fake_head_status)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    calls.extend([429, 200])

    options = replace(CrawlOptions.default(), gentle_mode=True, max_concurrent_per_host=2)
    code = await crawl_http._link_status(object(), "https://example.com", timeout=2, options=options)
    assert code == 200
    assert sleeps == [crawl_http._BACKOFF_DELAY]
