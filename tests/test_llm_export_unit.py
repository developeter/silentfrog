"""Unit tests for the v2.0 V5 LLM-friendly export."""

from __future__ import annotations

import json

from silentfrog.crawl_types import CrawlPayload
from silentfrog.exporters.llm_export import (
    export_crawl_for_llm,
    export_page_for_llm,
    write_llm_export,
)
from silentfrog.site_crawl_types import SiteCrawlResult


def _payload(url: str, score: int, checks: list[dict]) -> CrawlPayload:
    return CrawlPayload.from_raw(
        {
            "meta": [["title", "My Title", "8"], ["description", "A description.", "14"]],
            "headers": [["h1", "My Title"]],
            "images": [],
            "links": [],
            "schema": {"summary": {"total": 0, "by_type": {}}, "blocks": [], "issues": []},
            "canonical": {"target": url, "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": [url], "hops": 0, "final_status": "200", "final_url": url, "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": "index, follow",
            "hreflang": [],
            "ai_crawl": [],
            "serp": {"title": "T", "description": "", "url": url, "site_name": "", "breadcrumb": "", "favicon": ""},
            "serp_audit": {},
            "keywords": [],
            "content_quality": {"word_count": 412},
            "ai_visibility": {
                "summary": {
                    "verdict": "Needs work",
                    "score": score,
                    "good_count": 1,
                    "warning_count": sum(1 for c in checks if c["status"] == "warning"),
                    "critical_count": sum(1 for c in checks if c["status"] == "critical"),
                },
                "checks": checks,
            },
            "performance": {"summary": {"verdict": "Good"}},
            "social": {},
        }
    )


_CHECKS = [
    {"area": "Access", "check": "robots.txt", "status": "good", "details": "ok", "recommendation": "-", "key": "a"},
    {
        "area": "Content",
        "check": "Thin content",
        "status": "warning",
        "details": "Only 412 words",
        "recommendation": "Add depth",
        "key": "b",
    },
    {
        "area": "Topic clarity",
        "check": "Missing H1",
        "status": "critical",
        "details": "No H1",
        "recommendation": "Add an H1",
        "key": "c",
    },
    {
        "area": "Perf",
        "check": "CrUX LCP",
        "status": "info",
        "details": "Not measured",
        "recommendation": "Enable PSI",
        "key": "d",
    },
]


def test_page_export_has_preamble_and_score() -> None:
    export = export_page_for_llm(_payload("https://e.com/p", 72, _CHECKS), "https://e.com/p")
    assert "for AI analysis" in export.markdown
    assert "priority order" in export.markdown
    assert "GEO Score: 72/100" in export.markdown
    assert "https://e.com/p" in export.markdown


def test_page_export_compact_drops_good_and_info() -> None:
    export = export_page_for_llm(_payload("https://e.com/p", 72, _CHECKS), "https://e.com/p", mode="compact")
    assert "Thin content" in export.markdown  # warning kept
    assert "Missing H1" in export.markdown  # critical kept
    assert "robots.txt" not in export.markdown  # good dropped
    assert "CrUX LCP" not in export.markdown  # info dropped


def test_page_export_full_keeps_all_checks() -> None:
    export = export_page_for_llm(_payload("https://e.com/p", 72, _CHECKS), "https://e.com/p", mode="full")
    assert "robots.txt" in export.markdown
    assert "CrUX LCP" in export.markdown


def test_page_export_critical_sorted_before_warning() -> None:
    export = export_page_for_llm(_payload("https://e.com/p", 72, _CHECKS), "https://e.com/p")
    assert export.markdown.index("Missing H1") < export.markdown.index("Thin content")


def test_page_export_json_mirror() -> None:
    export = export_page_for_llm(_payload("https://e.com/p", 72, _CHECKS), "https://e.com/p")
    data = export.json_data
    assert data["type"] == "page"
    assert data["page"]["geo_score"] == 72
    assert data["page"]["word_count"] == 412
    # JSON text round-trips.
    assert json.loads(export.json_text)["page"]["geo_score"] == 72


def test_crawl_export_rollup_and_worst_pages() -> None:
    results = [
        SiteCrawlResult.from_payload("https://e.com/good", _payload("https://e.com/good", 95, _CHECKS[:1])),
        SiteCrawlResult.from_payload("https://e.com/bad", _payload("https://e.com/bad", 40, _CHECKS)),
        SiteCrawlResult.from_payload("https://e.com/mid", _payload("https://e.com/mid", 70, _CHECKS[:2])),
    ]
    export = export_crawl_for_llm(results, worst_n=2)
    assert "URLs audited: 3" in export.markdown
    assert "min 40" in export.markdown
    assert "max 95" in export.markdown
    # Worst-2 details include the lowest-scoring pages.
    assert "https://e.com/bad" in export.markdown
    assert export.json_data["distribution"]["count"] == 3
    assert export.json_data["worst_pages"][0]["url"] == "https://e.com/bad"


def test_crawl_export_issue_frequency() -> None:
    results = [
        SiteCrawlResult.from_payload("https://e.com/a", _payload("https://e.com/a", 50, _CHECKS)),
        SiteCrawlResult.from_payload("https://e.com/b", _payload("https://e.com/b", 55, _CHECKS)),
    ]
    export = export_crawl_for_llm(results)
    # "Missing H1" appears on both pages.
    assert any(item["check"] == "Missing H1" and item["count"] == 2 for item in export.json_data["common_issues"])


def test_write_llm_export_writes_md_and_json(tmp_path) -> None:
    export = export_page_for_llm(_payload("https://e.com/p", 72, _CHECKS), "https://e.com/p")
    paths = write_llm_export(export, tmp_path / "audit", fmt="both")
    suffixes = {p.suffix for p in paths}
    assert suffixes == {".md", ".json"}
    assert all(p.exists() for p in paths)
    md = (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert "GEO Score" in md


def test_page_export_includes_custom_extraction() -> None:
    payload = _payload("https://e.com/p", 80, _CHECKS)
    # Inject custom extraction (V6) and confirm it surfaces in md + json.
    object.__setattr__(payload, "custom_extraction", {"Price": "29.99", "SKU": "ABC-1"})
    export = export_page_for_llm(payload, "https://e.com/p")
    assert "Custom extraction" in export.markdown
    assert "Price" in export.markdown
    assert "29.99" in export.markdown
    assert export.json_data["custom_extraction"]["SKU"] == "ABC-1"
