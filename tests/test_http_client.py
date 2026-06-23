from __future__ import annotations

import pytest

from silentfrog.http_client import HttpResponse, fetch_page  # type: ignore[reportMissingImports]


@pytest.mark.asyncio
async def test_fetch_page_uses_supplied_headers(monkeypatch):
    captured: dict[str, dict[str, str]] = {}

    class DummySession:
        def __init__(self, *_, headers: dict[str, str] | None = None, **__):
            captured["headers"] = headers or {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_fetch(session, url, timeout):
        return HttpResponse("", 200, url, {}, 0.0, 0.0)

    monkeypatch.setattr("silentfrog.http_client.open_crawl_session", DummySession)
    monkeypatch.setattr("silentfrog.http_client.fetch", fake_fetch)

    custom_headers = {
        "User-Agent": "GentleBot/1.0",
        "Accept": "text/html",
        "Accept-Language": "en-US",
    }

    await fetch_page("https://example.com", headers=custom_headers)

    assert captured["headers"] == custom_headers
