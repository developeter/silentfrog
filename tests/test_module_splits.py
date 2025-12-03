from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from silentfrog.schema_extractor import _extract_schema_all  # type: ignore[reportMissingImports]
from silentfrog.perf_metrics import _collect_performance_metrics  # type: ignore[reportMissingImports]
from silentfrog.keywords import _extract_keywords, _keyword_density_threshold  # type: ignore[reportMissingImports]
from silentfrog.http_client import HttpResponse  # type: ignore[reportMissingImports]


def test_schema_extractor_basic_json_ld() -> None:
    html = """
    <html><head>
      <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"WebPage","name":"Example"}
      </script>
    </head><body></body></html>
    """
    result = _extract_schema_all(html, "https://example.com")
    summary = result["summary"]
    assert summary["total"] == 1
    assert summary["by_syntax"].get("json-ld") == 1
    assert summary["by_type"].get("WebPage") == 1
    assert summary["errors"] == []


@pytest.mark.asyncio
async def test_perf_metrics_counts_inline_only() -> None:
    body = "<html><head><script>var x='a';</script></head><body><img src='data:image/png;base64,'></body></html>"
    resp = HttpResponse(
        body=body,
        url="https://example.com",
        status=200,
        headers={},
        total_ms=120.0,
        ttfb_ms=60.0,
    )
    soup = BeautifulSoup(body, "html.parser")
    metrics = await _collect_performance_metrics(resp, soup)
    assert metrics["status"] == 200
    assert metrics["resource_summary"]["js"]["bytes"] > 0
    scripts = metrics["scripts"]
    assert scripts["blocking"]["count"] == 1
    assert metrics["top_offenders"], "Expected at least the inline script as an offender"


def test_keywords_extraction_basics() -> None:
    html = """
    <html>
      <head>
        <title>Hello World</title>
        <meta name="description" content="Hello hello world">
      </head>
      <body>Hello hello world world</body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    keywords = _extract_keywords(soup, text, top_n=3)
    terms = {entry["term"] for entry in keywords}
    assert "hello" in terms or "world" in terms
    assert _keyword_density_threshold() > 0
