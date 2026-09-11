from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from silentfrog.http_client import HttpResponse  # type: ignore[reportMissingImports]
from silentfrog.perf_metrics import (  # type: ignore[reportMissingImports]
    _build_heaviest_resources,
    _build_performance_issues,
    _build_third_party_hosts,
    _collect_performance_metrics,
    _data_uri_size,
    _format_bytes,
    _measure_remote_resources,
    _normalize_resource_type,
    performance_heaviest_resources_tooltip,
    performance_issue_tooltip,
    performance_resource_tooltip,
    performance_summary_tooltip,
    performance_third_party_hosts_tooltip,
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
    assert "registrable" in performance_heaviest_resources_tooltip().lower()
    assert "registrable" in performance_third_party_hosts_tooltip().lower()


def test_build_heaviest_resources_orders_caps_and_flags_third_party() -> None:
    resource_entries = {
        "js": [
            {"type": "JS", "url": "https://example.com/app.js", "bytes": 50_000, "blocking": True},
            {"type": "JS", "url": "https://cdn.other.com/tag.js", "bytes": 120_000, "blocking": False},
        ],
        "img": [
            {"type": "IMG", "url": "https://example.com/hero.jpg", "bytes": 300_000, "blocking": False},
        ],
    }

    heaviest = _build_heaviest_resources("https://example.com/page", resource_entries, limit=2)

    assert [item["url"] for item in heaviest] == [
        "https://example.com/hero.jpg",
        "https://cdn.other.com/tag.js",
    ]
    assert heaviest[0]["third_party"] is False
    assert heaviest[1]["third_party"] is True
    assert heaviest[1]["bytes"] == 120_000
    assert heaviest[1]["type"] == "JS"


def test_build_heaviest_resources_empty_case() -> None:
    assert _build_heaviest_resources("https://example.com", {}) == []
    assert _build_heaviest_resources("https://example.com", {"js": []}) == []


def test_build_third_party_hosts_groups_by_host_and_sorts_by_bytes() -> None:
    resource_entries = {
        "js": [
            {"type": "JS", "url": "https://cdn.other.com/a.js", "bytes": 40_000, "blocking": False},
            {"type": "JS", "url": "https://cdn.other.com/b.js", "bytes": 10_000, "blocking": False},
        ],
        "img": [
            {"type": "IMG", "url": "https://images.thirdparty.com/x.jpg", "bytes": 200_000, "blocking": False},
            {"type": "IMG", "url": "https://example.com/local.jpg", "bytes": 999_999, "blocking": False},
        ],
    }

    hosts = _build_third_party_hosts("https://example.com/page", resource_entries)

    assert [item["host"] for item in hosts] == ["images.thirdparty.com", "cdn.other.com"]
    other_host = hosts[1]
    assert other_host["bytes"] == 50_000
    assert other_host["count"] == 2
    assert other_host["types"] == ["JS"]


def test_build_third_party_hosts_caps_at_limit_and_handles_empty() -> None:
    assert _build_third_party_hosts("https://example.com", {}) == []
    resource_entries = {
        "js": [
            {"type": "JS", "url": f"https://host{i}.example-cdn.com/a.js", "bytes": 1000 - i, "blocking": False}
            for i in range(5)
        ]
    }
    hosts = _build_third_party_hosts("https://example.com", resource_entries, limit=3)
    assert len(hosts) == 3
    assert hosts[0]["host"] == "host0.example-cdn.com"


def test_third_party_issue_evidence_names_top_hosts() -> None:
    resources = {
        "css": {"count": 0, "bytes": 0},
        "js": {"count": 0, "bytes": 0},
        "img": {"count": 0, "bytes": 0},
        "font": {"count": 0, "bytes": 0},
        "other": {"count": 0, "bytes": 0},
    }
    script_stats = {"blocking": {"count": 0, "bytes": 0}, "async": {"count": 0, "bytes": 0}}
    summary = {
        "total_page_bytes": 0,
        "total_resource_count": 0,
        "third_party_bytes": 700_000,
        "third_party_count": 6,
    }
    third_party_hosts = [
        {"host": "a.example.com", "bytes": 400_000, "count": 3, "types": ["JS"]},
        {"host": "b.example.com", "bytes": 200_000, "count": 2, "types": ["IMG"]},
        {"host": "c.example.com", "bytes": 100_000, "count": 1, "types": ["CSS"]},
    ]

    issues = _build_performance_issues(resources, script_stats, summary, third_party_hosts)

    assert len(issues) == 1
    evidence = issues[0]["evidence"]
    assert "a.example.com" in evidence
    assert "b.example.com" in evidence
    assert "c.example.com" in evidence


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
    # Inline script and data-URI image are same-page content: nothing here is third-party.
    assert metrics["heaviest_resources"]
    assert all(not item["third_party"] for item in metrics["heaviest_resources"])
    assert metrics["third_party_hosts"] == []


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

    heaviest = metrics["heaviest_resources"]
    assert heaviest, "heaviest_resources must be populated"
    assert [item["bytes"] for item in heaviest] == sorted((item["bytes"] for item in heaviest), reverse=True)
    assert all(item["third_party"] for item in heaviest)

    hosts = metrics["third_party_hosts"]
    assert [host["host"] for host in hosts] == ["cdn.third-party.com"]
    assert hosts[0]["count"] == 3
    assert hosts[0]["bytes"] == 180_000 + 820_000 + 1_700_000
    assert hosts[0]["types"] == sorted(hosts[0]["types"])

    third_party_issue = next(issue for issue in metrics["issues"] if issue["key"] == "third_party_weight")
    assert "cdn.third-party.com" in third_party_issue["evidence"]


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

    monkeypatch.setattr("silentfrog.perf_metrics._RESOURCE_FETCH_LIMIT", 2, raising=False)
    monkeypatch.setattr("silentfrog.perf_metrics.open_crawl_session", _FakeSession)

    aggregated, per_url = await _measure_remote_resources(targets)
    assert aggregated["js"] == 0 and aggregated["css"] == 0
    # limit applied per resource type
    assert len(per_url["js"]) <= 2
    assert len(per_url["css"]) <= 2
