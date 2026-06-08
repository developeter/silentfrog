from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from silentfrog.sitemap_geo_aggregate import (
    SitemapGeoReport,
    UrlScore,
    aggregate_sitemap,
    parse_sitemap,
)


@dataclass
class _Summary:
    verdict: str = "Strong"
    score: int = 100
    good_count: int = 0
    warning_count: int = 0
    critical_count: int = 0


@dataclass
class _Check:
    area: str
    check: str
    status: str
    key: str = "x"


@dataclass
class _AiV:
    summary: _Summary
    checks: list[_Check]


@dataclass
class _Payload:
    ai_visibility: _AiV


def _payload(score: int, warnings: tuple[str, ...] = (), area: str = "Topic clarity") -> _Payload:
    return _Payload(
        ai_visibility=_AiV(
            summary=_Summary(score=score, warning_count=len(warnings)),
            checks=[_Check(area=area, check=w, status="warning") for w in warnings],
        )
    )


SITEMAP_3_URLS = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/a</loc></url>
  <url><loc>https://example.com/b</loc></url>
  <url><loc>https://example.com/c</loc></url>
</urlset>
"""

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sm-1.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sm-2.xml</loc></sitemap>
</sitemapindex>
"""


def test_parse_sitemap_extracts_urls() -> None:
    urls = parse_sitemap(SITEMAP_3_URLS)
    assert urls == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]


def test_parse_sitemap_handles_index_form() -> None:
    urls = parse_sitemap(SITEMAP_INDEX)
    assert urls == [
        "https://example.com/sm-1.xml",
        "https://example.com/sm-2.xml",
    ]


def test_parse_sitemap_returns_empty_on_malformed_xml() -> None:
    assert parse_sitemap("not xml at all") == []


@pytest.mark.asyncio
async def test_aggregate_sitemap_collects_scores(monkeypatch) -> None:
    scores_by_url = {
        "https://example.com/a": 90,
        "https://example.com/b": 70,
        "https://example.com/c": 50,
    }

    async def _stub_analyser(url: str) -> Any:
        return _payload(scores_by_url[url], warnings=("Generic warn",))

    async def _stub_fetch(*_args: Any, **_kw: Any) -> str:
        return SITEMAP_3_URLS

    monkeypatch.setattr("silentfrog.sitemap_geo_aggregate.fetch_sitemap", _stub_fetch)

    report = await aggregate_sitemap(
        "https://example.com/sitemap.xml",
        analyser=_stub_analyser,
        max_concurrency=2,
    )
    assert report.count == 3
    assert report.measured_count == 3
    assert report.max_score == 90
    assert report.min_score == 50
    assert report.p50_score == 70.0
    assert "Topic clarity" in report.per_area_means


@pytest.mark.asyncio
async def test_aggregate_sitemap_handles_per_url_errors(monkeypatch) -> None:
    async def _stub_analyser(url: str) -> Any:
        if "b" in url:
            raise RuntimeError("boom")
        return _payload(80)

    async def _stub_fetch(*_args: Any, **_kw: Any) -> str:
        return SITEMAP_3_URLS

    monkeypatch.setattr("silentfrog.sitemap_geo_aggregate.fetch_sitemap", _stub_fetch)
    report = await aggregate_sitemap(
        "https://example.com/sitemap.xml",
        analyser=_stub_analyser,
        max_concurrency=2,
    )
    assert report.measured_count == 2
    assert len(report.error_urls) == 1
    assert report.error_urls[0].url == "https://example.com/b"


@pytest.mark.asyncio
async def test_aggregate_sitemap_respects_concurrency_semaphore(monkeypatch) -> None:
    """Active task count must never exceed max_concurrency."""
    import asyncio as _asyncio

    active = 0
    peak = 0

    async def _stub_analyser(url: str) -> Any:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await _asyncio.sleep(0.01)
        active -= 1
        return _payload(80)

    async def _stub_fetch(*_args: Any, **_kw: Any) -> str:
        return SITEMAP_3_URLS

    monkeypatch.setattr("silentfrog.sitemap_geo_aggregate.fetch_sitemap", _stub_fetch)
    await aggregate_sitemap(
        "https://example.com/sitemap.xml",
        analyser=_stub_analyser,
        max_concurrency=2,
    )
    assert peak <= 2


@pytest.mark.asyncio
async def test_aggregate_sitemap_empty_when_no_urls(monkeypatch) -> None:
    async def _stub_fetch(*_args: Any, **_kw: Any) -> str:
        return ""

    monkeypatch.setattr("silentfrog.sitemap_geo_aggregate.fetch_sitemap", _stub_fetch)

    async def _stub_analyser(url: str) -> Any:
        raise AssertionError("should not be called for empty sitemap")

    report = await aggregate_sitemap(
        "https://example.com/sitemap.xml",
        analyser=_stub_analyser,
    )
    assert report.count == 0
    assert report.measured_count == 0


def test_sitemap_geo_report_to_dict_serializes_worst_urls() -> None:
    report = SitemapGeoReport(
        sitemap_url="https://example.com/sitemap.xml",
        count=2,
        measured_count=2,
        p50_score=75.0,
        p75_score=80.0,
        p95_score=85.0,
        min_score=70,
        max_score=85,
        worst_urls=(UrlScore(url="https://example.com/x", score=70, verdict="Needs work", top_warning="X"),),
    )
    data = report.to_dict()
    assert data["count"] == 2
    assert data["worst_urls"][0]["score"] == 70
    assert "x" in data["worst_urls"][0]["url"]
