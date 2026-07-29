"""v3 G8 — client-ready HTML report."""

from __future__ import annotations

import re
from pathlib import Path

from silentfrog.audit_issues import issues_for_results  # type: ignore[reportMissingImports]
from silentfrog.crawl_history import CrawlHistoryRun, CrawlHistoryStore  # type: ignore[reportMissingImports]
from silentfrog.crawl_run_repository import CrawlRunRef, stream_report_results  # type: ignore[reportMissingImports]
from silentfrog.crawl_store import CrawlStore, StoredAudit  # type: ignore[reportMissingImports]
from silentfrog.crawl_types import CrawlPayload  # type: ignore[reportMissingImports]
from silentfrog.exporters.html_report import (  # type: ignore[reportMissingImports]
    build_site_crawl_html,
    export_site_crawl_html,
)
from silentfrog.site_crawl_types import SiteCrawlReport, SiteCrawlResult  # type: ignore[reportMissingImports]


def _payload(url: str, *, score: int, title: str = "Example Title") -> CrawlPayload:
    return CrawlPayload.from_raw(
        {
            "meta": [["title", title, str(len(title))], ["description", "Useful description text.", "24"]],
            "headers": [["h1", title or "Untitled"]],
            "images": [],
            "links": [],
            "schema": {"summary": {"total": 0, "by_type": {}}, "blocks": [], "issues": []},
            "canonical": {"target": url, "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": [url], "hops": 0, "final_status": "200", "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": "index, follow",
            "hreflang": [],
            "ai_crawl": [],
            "serp": {
                "title": title,
                "description": "",
                "url": url,
                "site_name": "",
                "breadcrumb": "",
                "favicon": "",
            },
            "serp_audit": {},
            "keywords": [],
            "content_quality": {"word_count": 400},
            "ai_visibility": {
                "summary": {
                    "verdict": "Needs work",
                    "score": score,
                    "good_count": 1,
                    "warning_count": 0,
                    "critical_count": 0,
                },
                "checks": [],
            },
            "performance": {"summary": {"verdict": "Good"}},
            "social": {},
        }
    )


def _build_report() -> tuple[SiteCrawlReport, list[SiteCrawlResult]]:
    """3 low scorers (bin 0-19), one mid, one high, one missing-title page
    (single known hint), one failed page (single known critical issue)."""
    results = [
        SiteCrawlResult.from_payload("https://example.com/low1", _payload("https://example.com/low1", score=5)),
        SiteCrawlResult.from_payload("https://example.com/low2", _payload("https://example.com/low2", score=8)),
        SiteCrawlResult.from_payload("https://example.com/low3", _payload("https://example.com/low3", score=15)),
        SiteCrawlResult.from_payload("https://example.com/mid", _payload("https://example.com/mid", score=45)),
        SiteCrawlResult.from_payload("https://example.com/best", _payload("https://example.com/best", score=95)),
        SiteCrawlResult.from_payload(
            "https://example.com/no-title", _payload("https://example.com/no-title", score=30, title="")
        ),
        SiteCrawlResult.failed("https://example.com/broken", "boom"),
    ]
    report = SiteCrawlReport.from_results(results, discovered_count=len(results), base_url="https://example.com")
    return report, results


def test_build_site_crawl_html_renders_core_sections() -> None:
    report, results = _build_report()
    issues = issues_for_results(results)

    doc = build_site_crawl_html(report, results, issues, generated_at="2026-07-29T12:00:00Z")

    assert "https://example.com" in doc
    assert "Generated 2026-07-29T12:00:00Z" in doc
    # Executive summary: exactly one critical (the failed row) rendered as a stat card.
    assert '<div class="stat-card stat-bad"><div class="stat-value">1</div>' in doc
    # Prioritized actions: the missing-title page yields exactly this known headline
    # (a single affected URL, so Hint.headline() adds no "- N pages" suffix).
    assert "The page has no title tag." in doc
    # GEO Score distribution: three pages (scores 5, 8, 15) land in the 0-19 bin.
    svg_match = re.search(r"<svg[^>]*GEO Score distribution.*?</svg>", doc, re.DOTALL)
    assert svg_match is not None
    assert ">3</text>" in svg_match.group(0)
    assert ">0-19</text>" in svg_match.group(0)
    # Worst pages: the lowest-scoring page is listed.
    assert "https://example.com/low1" in doc
    # No history saved for this scope in this test -> the quiet trend line.
    assert "Trend appears after two crawls of this site." in doc
    assert "<script" not in doc.lower()


def test_build_site_crawl_html_escapes_hostile_title() -> None:
    hostile = "<script>alert(1)</script>"
    payload = _payload("https://example.com/hostile", score=10, title=hostile)
    result = SiteCrawlResult.from_payload("https://example.com/hostile", payload)
    report = SiteCrawlReport.from_results([result], discovered_count=1, base_url="https://example.com")
    issues = issues_for_results([result])

    doc = build_site_crawl_html(report, [result], issues, generated_at="2026-07-29T12:00:00Z")

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in doc
    assert hostile not in doc
    assert "<script" not in doc.lower()


def test_build_site_crawl_html_degrades_on_failed_only_crawl() -> None:
    result = SiteCrawlResult.failed("https://example.com/broken", "boom")
    report = SiteCrawlReport.from_results([result], discovered_count=1, base_url="https://example.com")
    issues = issues_for_results([result])

    doc = build_site_crawl_html(report, [result], issues, generated_at="2026-07-29T12:00:00Z")

    assert "No data measured." in doc
    assert "<script" not in doc.lower()


def test_export_site_crawl_html_store_backed_matches_in_memory_essentials(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path / "data"))
    url = "https://example.com/only"
    payload = _payload(url, score=40)
    db = tmp_path / "crawl.db"
    store = CrawlStore(db)
    run_id = store.start_run("example.com", "https://example.com/", "list")
    store.save_audit(run_id, StoredAudit(url=url, http_status="200", payload=payload.to_mapping()))
    store.finish_run(run_id)
    store.close()

    run_report = SiteCrawlReport.from_run(
        CrawlRunRef(db, run_id),
        discovered_count=1,
        crawled_count=1,
        skipped_count=0,
        failed_count=0,
        base_url="https://example.com/",
    )
    output = tmp_path / "report.html"
    export_site_crawl_html(run_report, output)
    doc = output.read_text(encoding="utf-8")

    assert "https://example.com" in doc
    assert "Generated" in doc
    assert url in doc
    assert "0-100, higher is better" in doc
    assert "<script" not in doc.lower()


def test_export_site_crawl_html_print_friendly_and_self_contained(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path / "data"))
    report, results = _build_report()
    output = tmp_path / "report.html"
    export_site_crawl_html(report, output)
    doc = output.read_text(encoding="utf-8")

    assert "@media print" in doc
    assert "<script" not in doc.lower()
    for match in re.finditer(r'(?:src|href)\s*=\s*"([^"]*)"', doc):
        assert not match.group(1).startswith(("http://", "https://"))


def _history_run(scope: str, run_id: str, created_at: str) -> CrawlHistoryRun:
    return CrawlHistoryRun(
        run_id=run_id,
        created_at=created_at,
        scope_key=scope,
        discovered_count=1,
        crawled_count=1,
        failed_count=0,
        skipped_count=0,
        issues=(),
    )


def test_export_site_crawl_html_renders_trend_with_two_scoped_runs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path / "data"))
    store = CrawlHistoryStore()
    store.save_run(_history_run("example.com", "example.com_1", "2026-01-01T00:00:00Z"))
    store.save_run(_history_run("example.com", "example.com_2", "2026-01-02T00:00:00Z"))

    result = SiteCrawlResult.from_payload("https://example.com/page", _payload("https://example.com/page", score=60))
    report = SiteCrawlReport.from_results([result], discovered_count=1, base_url="https://example.com")
    output = tmp_path / "report.html"
    export_site_crawl_html(report, output)
    doc = output.read_text(encoding="utf-8")

    assert "lower is better" in doc
    assert "trend-line" in doc
    assert "Trend appears after two crawls of this site." not in doc


def test_export_site_crawl_html_shows_quiet_line_with_no_history(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path / "data"))
    result = SiteCrawlResult.from_payload("https://example.com/page", _payload("https://example.com/page", score=60))
    report = SiteCrawlReport.from_results([result], discovered_count=1, base_url="https://example.com")
    output = tmp_path / "report.html"
    export_site_crawl_html(report, output)
    doc = output.read_text(encoding="utf-8")

    assert "Trend appears after two crawls of this site." in doc


def test_export_site_crawl_html_streams_only_once(monkeypatch, tmp_path: Path) -> None:
    """H1/H2 guard: exactly one stream_report_results call backs the whole
    document (issues + aggregates + worst pages), never a second full stream."""
    calls: list[object] = []
    original = stream_report_results

    def _counting_stream(report):
        calls.append(report)
        return original(report)

    monkeypatch.setattr("silentfrog.exporters.html_report.stream_report_results", _counting_stream)
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path / "data"))
    result = SiteCrawlResult.from_payload("https://example.com/page", _payload("https://example.com/page", score=60))
    report = SiteCrawlReport.from_results([result], discovered_count=1, base_url="https://example.com")
    output = tmp_path / "report.html"

    export_site_crawl_html(report, output)

    assert len(calls) == 1
