from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from silentfrog.http_client import HttpResponse  # type: ignore[reportMissingImports]
from silentfrog.perf_metrics import (  # type: ignore[reportMissingImports]
    _build_performance_issues,
    _collect_performance_metrics,
    _data_uri_size,
    _format_bytes,
    _measure_remote_resources,
    _normalize_resource_type,
    performance_issue_tooltip,
    performance_resource_tooltip,
    performance_summary_tooltip,
)


def test_data_uri_size_and_format_bytes() -> None:
    # Validate local helpers for sizing data URIs and humanizing byte values.
    assert _data_uri_size("data:image/png;base64,AAAA") == 3
    assert _data_uri_size("data:text/plain,abc") == len("abc")
    assert _format_bytes(-5) == "0 B"
    assert _format_bytes(1024) == "1.0 KB"
    assert _format_bytes(0) == "0 B"
    assert _normalize_resource_type("style") == "css"
    assert _normalize_resource_type("script") == "js"
    assert _normalize_resource_type("image") == "img"
    assert _normalize_resource_type("unknown") == "other"
    assert "Blocking JavaScript" in performance_issue_tooltip("blocking_js")
    assert "Third-party" in performance_summary_tooltip()
    assert "Blocking JS" in performance_resource_tooltip()


def test_build_performance_issues_keeps_thresholds_and_order() -> None:
    resources = {
        "css": {"count": 4, "bytes": 130_000},
        "js": {"count": 7, "bytes": 710_000},
        "img": {"count": 3, "bytes": 1_600_000},
        "font": {"count": 1, "bytes": 40_000},
        "other": {"count": 0, "bytes": 0},
    }
    script_stats = {
        "blocking": {"count": 2, "bytes": 360_000},
        "async": {"count": 5, "bytes": 80_000},
    }
    summary = {
        "total_page_bytes": 2_100_000,
        "total_resource_count": 28,
        "third_party_bytes": 700_000,
        "third_party_count": 6,
    }

    issues = _build_performance_issues(resources, script_stats, summary)

    assert [issue["key"] for issue in issues] == [
        "page_weight",
        "blocking_js",
        "js_weight",
        "css_weight",
        "image_weight",
        "request_count",
        "third_party_weight",
    ]
    assert issues[0]["severity"] == "critical"
    assert issues[1]["severity"] == "critical"
    assert issues[3]["severity"] == "warning"
    assert issues[5]["severity"] == "warning"
    assert issues[6]["severity"] == "critical"


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
    assert summary["other"]["bytes"] == 0
    assert metrics["status"] == 200
    assert metrics["transfer_size"] > 0
    assert metrics["summary"]["total_page_bytes"] >= metrics["transfer_size"]
    assert metrics["summary"]["total_resource_count"] >= 2
    assert metrics["summary"]["warning_issue_count"] >= 1
    assert metrics["summary"]["verdict"] in {"Needs work", "High performance risk"}
    assert any(issue["key"] == "blocking_js" for issue in metrics["issues"])
    breakdown = {entry["type"]: entry for entry in metrics["resource_breakdown"]}
    assert breakdown["html"]["bytes"] == metrics["transfer_size"]
    assert breakdown["js"]["bytes"] == summary["js"]["bytes"]
    assert breakdown["img"]["bytes"] == summary["img"]["bytes"]


@pytest.mark.asyncio
async def test_collect_performance_metrics_builds_verdict_and_third_party_issues(monkeypatch) -> None:
    body = """
    <html>
      <head>
        <link rel="stylesheet" href="https://cdn.third-party.com/app.css" />
        <script src="https://cdn.third-party.com/app.js"></script>
      </head>
      <body>
        <img src="https://cdn.third-party.com/hero.jpg" />
      </body>
    </html>
    """

    async def _fake_measure(targets):
        return (
            {"css": 180_000, "js": 820_000, "img": 1_700_000, "font": 0, "other": 0},
            {
                "css": {"https://cdn.third-party.com/app.css": 180_000},
                "js": {"https://cdn.third-party.com/app.js": 820_000},
                "img": {"https://cdn.third-party.com/hero.jpg": 1_700_000},
                "font": {},
                "other": {},
            },
        )

    monkeypatch.setattr("silentfrog.perf_metrics._measure_remote_resources", _fake_measure)

    resp = HttpResponse(
        body=body,
        url="https://example.com/page",
        status=200,
        headers={},
        total_ms=640.0,
        ttfb_ms=140.0,
    )
    soup = BeautifulSoup(body, "html.parser")

    metrics = await _collect_performance_metrics(resp, soup)

    assert metrics["summary"]["third_party_count"] == 3
    assert metrics["summary"]["critical_issue_count"] >= 1
    assert metrics["summary"]["verdict"] == "High performance risk"
    issue_keys = {issue["key"] for issue in metrics["issues"]}
    assert {"page_weight", "blocking_js", "js_weight", "image_weight", "third_party_weight"} <= issue_keys


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
