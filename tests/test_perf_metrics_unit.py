from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from silentfrog.http_client import HttpResponse  # type: ignore[reportMissingImports]
from silentfrog.perf_metrics import (  # type: ignore[reportMissingImports]
    _collect_performance_metrics,
    _data_uri_size,
    _format_bytes,
    _measure_remote_resources,
)


def test_data_uri_size_and_format_bytes() -> None:
    # Validate local helpers for sizing data URIs and humanizing byte values.
    assert _data_uri_size("data:image/png;base64,AAAA") == 3
    assert _data_uri_size("data:text/plain,abc") == len("abc")
    assert _format_bytes(-5) == "0 B"
    assert _format_bytes(1024) == "1.0 KB"
    assert _format_bytes(0) == "0 B"


@pytest.mark.asyncio
async def test_collect_performance_metrics_inline_resources() -> None:
    # Inline scripts and data URIs should be counted in resource summary without network access.
    body = """
    <html>
      <head>
        <script>var x='inline';</script>
      </head>
      <body>
        <img src="data:image/png;base64,AAAA" />
      </body>
    </html>
    """
    resp = HttpResponse(
        body=body,
        url="https://example.com",
        status=200,
        headers={},
        total_ms=100.0,
        ttfb_ms=50.0,
    )
    soup = BeautifulSoup(body, "html.parser")
    metrics = await _collect_performance_metrics(resp, soup)
    summary = metrics["resource_summary"]
    assert summary["js"]["bytes"] > 0
    assert summary["img"]["bytes"] > 0
    assert metrics["status"] == 200
    assert metrics["transfer_size"] > 0


@pytest.mark.asyncio
async def test_measure_remote_resources_honors_limit(monkeypatch) -> None:
    # Ensure the fetch limit caps per-resource downloads and zero-byte responses don't inflate totals.
    urls = [f"https://example.com/{i}" for i in range(5)]
    targets = {"js": urls, "css": urls}

    class _FakeContent:
        async def iter_chunked(self, _size):
            if False:
                yield b""  # pragma: no cover

    class _FakeResponse:
        def __init__(self, headers: dict[str, str]):
            self.headers = headers
            self.content = _FakeContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeSession:
        def __init__(self, *args, **kwargs):
            self.calls: list[str] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def head(self, url, **kwargs):
            self.calls.append(url)
            return _FakeResponse({})

        def get(self, url, **kwargs):
            self.calls.append(url)
            return _FakeResponse({})

    class _FakeConnector:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr("silentfrog.perf_metrics._RESOURCE_FETCH_LIMIT", 2, raising=False)
    monkeypatch.setattr("silentfrog.perf_metrics.aiohttp.ClientSession", _FakeSession)
    monkeypatch.setattr("silentfrog.perf_metrics.aiohttp.TCPConnector", _FakeConnector)

    aggregated, per_url = await _measure_remote_resources(targets)
    assert aggregated["js"] == 0 and aggregated["css"] == 0
    # limit applied per resource type
    assert len(per_url["js"]) <= 2
    assert len(per_url["css"]) <= 2
