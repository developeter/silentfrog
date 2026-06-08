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
    sleeps: list[float] = []

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    session = _HeadSession([_HeadResponse(429), _HeadResponse(200)], [_HeadResponse(429)])
    options = replace(CrawlOptions.default(), gentle_mode=True, max_concurrent_per_host=2)
    code = await crawl_http._link_status(session, "https://example.com", timeout=2, options=options)
    assert code == 200
    assert sleeps == [crawl_http._BACKOFF_DELAY]


class _HeadResponse:
    def __init__(self, status: int, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _HeadSession:
    def __init__(self, responses, get_responses=None) -> None:
        self._responses = responses
        self._get_responses = get_responses or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def head(self, url: str, **kwargs):
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url: str, **kwargs):
        response = self._get_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_trace_redirects_reports_normal_chain(monkeypatch) -> None:
    responses = [
        _HeadResponse(301, {"Location": "/step-2"}),
        _HeadResponse(200),
    ]
    monkeypatch.setattr(crawl_http.aiohttp, "ClientSession", lambda **_kwargs: _HeadSession(responses))

    hops, status, hop_count, is_loop = await crawl_http._trace_redirects("https://example.com/start", timeout=2)

    assert hops == ["https://example.com/start", "https://example.com/step-2"]
    assert status == "200"
    assert hop_count == 1
    assert is_loop is False


@pytest.mark.asyncio
async def test_trace_redirects_reports_loop(monkeypatch) -> None:
    responses = [
        _HeadResponse(302, {"Location": "/b"}),
        _HeadResponse(302, {"Location": "/a"}),
        _HeadResponse(302, {"Location": "/b"}),
    ]
    monkeypatch.setattr(crawl_http.aiohttp, "ClientSession", lambda **_kwargs: _HeadSession(responses))

    hops, status, hop_count, is_loop = await crawl_http._trace_redirects("https://example.com/a", timeout=2)

    assert hops == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/a",
    ]
    assert status == "302"
    assert hop_count == 2
    assert is_loop is True


@pytest.mark.asyncio
async def test_trace_redirects_reports_max_hops(monkeypatch) -> None:
    responses = [_HeadResponse(301, {"Location": f"/hop-{index}"}) for index in range(10)]
    monkeypatch.setattr(crawl_http.aiohttp, "ClientSession", lambda **_kwargs: _HeadSession(responses))

    hops, status, hop_count, is_loop = await crawl_http._trace_redirects("https://example.com/start", timeout=2)

    assert status == "max-hops"
    assert hop_count == 6
    assert is_loop is False


@pytest.mark.asyncio
async def test_trace_redirects_reports_exception(monkeypatch) -> None:
    monkeypatch.setattr(crawl_http.aiohttp, "ClientSession", lambda **_kwargs: _HeadSession([RuntimeError("boom")]))

    hops, status, hop_count, is_loop = await crawl_http._trace_redirects("https://example.com/start", timeout=2)

    assert hops == ["https://example.com/start"]
    assert status == "error RuntimeError"
    assert hop_count == 0
    assert is_loop is False


@pytest.mark.asyncio
async def test_probe_status_falls_back_to_get_when_head_is_blocked() -> None:
    session = _HeadSession([_HeadResponse(403)], [_HeadResponse(200)])

    code = await crawl_http._link_status(session, "https://example.com/page", timeout=2, options=CrawlOptions.default())

    assert code == 200


@pytest.mark.asyncio
async def test_probe_status_falls_back_to_get_when_head_is_not_allowed() -> None:
    session = _HeadSession([_HeadResponse(405)], [_HeadResponse(200)])

    code = await crawl_http._link_status(session, "https://example.com/page", timeout=2, options=CrawlOptions.default())

    assert code == 200


@pytest.mark.asyncio
async def test_probe_status_keeps_unresolved_403_after_get_fallback() -> None:
    session = _HeadSession([_HeadResponse(403)], [_HeadResponse(403)])

    code = await crawl_http._link_status(session, "https://example.com/page", timeout=2, options=CrawlOptions.default())

    assert code == 403


@pytest.mark.asyncio
async def test_trace_redirects_uses_get_fallback_for_blocked_head(monkeypatch) -> None:
    monkeypatch.setattr(
        crawl_http.aiohttp,
        "ClientSession",
        lambda **_kwargs: _HeadSession([_HeadResponse(403)], [_HeadResponse(200)]),
    )

    hops, status, hop_count, is_loop = await crawl_http._trace_redirects("https://example.com/start", timeout=2)

    assert hops == ["https://example.com/start"]
    assert status == "200"
    assert hop_count == 0
    assert is_loop is False
