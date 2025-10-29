from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from silentfrog.crawl_types import CrawlPayload
from silentfrog.exporters import export_page_analysis


def _sample_payload() -> CrawlPayload:
    raw = {
        "meta": [
            ["title", "Example Optimized Marketing Title", "35"],
            ["description", "Foo", "123"],
            ["robots", "index, follow", "12"],
            ["viewport", "width=device-width, initial-scale=1", "40"],
            ["charset", "utf-8", "5"],
        ],
        "headers": [["h1", "Title"]],
        "images": [["https://example.com/logo.png", "Alt", "Title", "image/png", "100", "200", "10 KB", "Yes"]],
        "links": [["https://example.com", "Example", "Follow", "200"]],
        "schema": {
            "summary": {
                "total": 1,
                "by_syntax": {"json-ld": 1},
                "by_type": {"WebPage": 1},
                "errors": []
            },
            "blocks": [
                {
                    "@context": "https://schema.org",
                    "@type": "WebPage",
                    "name": "Example Page",
                    "url": "https://example.com/page",
                    "_extracted_via": "json-ld"
                }
            ],
            "issues": [],
            "fallback_raw": []
        },
        "canonical": {
            "target": "https://example.com",
            "self": True,
            "multiple": False,
            "status": "200",
        },
        "redirect": {
            "chain": ["https://example.com"],
            "hops": 0,
            "final_status": "200",
            "loop": False,
        },
        "robots": {"*": [("Allow", "/"), ("Disallow", "/tmp")]},
        "meta_robots": "index, follow",
        "hreflang": [["en", "https://example.com", "200", "Yes", "Yes"]],
        "ai_crawl": [["GPTBot", "Yes", "No", "Allowed"]],
        "serp": {
            "title": "Example Title",
            "description": "Example description",
            "url": "https://example.com",
            "site_name": "Example",
            "breadcrumb": "example.com > page",
            "favicon": "data:image/png;base64,abc",
        },
        "serp_audit": {
            "too_long": "No",
            "too_short": "No",
            "px_over": "No",
            "px_under": "No",
            "equals_h1": "No",
            "missing": "No",
            "px_len": "100",
            "char_len": "10",
        },
        "keywords": [
            {
                "term": "example",
                "length": 1,
                "frequency": 5,
                "density": 3.2,
                "density_threshold": 4.0,
                "density_warning": False,
                "in_title": True,
                "in_description": True,
                "heading_count": 1,
                "first_position": 0,
            }
        ],
        "performance": {
            "nav_ttfb_ms": 220.0,
            "nav_total_ms": 4200.0,
            "transfer_size": 2100000,
            "status": 200,
            "resource_summary": {
                "css": {"count": 12, "bytes": 96000},
                "js": {"count": 35, "bytes": 420000},
                "img": {"count": 18, "bytes": 580000},
            },
            "opportunities": [
                "HTTP Archive Web Almanac (open source): Page weight is above 1.5 MB; compare with the community benchmarks (https://almanac.httparchive.org/en/2023/performance#page-weight)",
                "High stylesheet count; inline critical CSS and combine static files.",
            ],
        },
    }
    return CrawlPayload.from_raw(raw)


def test_export_page_analysis_creates_workbook(tmp_path: Path) -> None:
    payload = _sample_payload()
    out_file = tmp_path / "report.xlsx"

    export_page_analysis(payload, out_file)

    assert out_file.exists()

    workbook = load_workbook(out_file)
    try:
        assert "Meta" in workbook.sheetnames
        assert "SERP Preview" in workbook.sheetnames
        assert "Structured summary" in workbook.sheetnames
        assert "Structured data" in workbook.sheetnames
        assert "Performance" in workbook.sheetnames

        meta_sheet = workbook["Meta"]
        assert meta_sheet["A2"].value == "title"
        assert meta_sheet["B2"].value == "Example Optimized Marketing Title"
        assert meta_sheet["C2"].fill.start_color.rgb == "FFD1E7DD"
        assert meta_sheet["A3"].value == "description"
        assert meta_sheet["B3"].value == "Foo"
        assert meta_sheet["C3"].fill.start_color.rgb == "FFFFF3CD"

        summary_sheet = workbook["Structured summary"]
        assert summary_sheet["A2"].value == "Total items"
        assert summary_sheet["B2"].value == "1"

        structured_sheet = workbook["Structured data"]
        assert structured_sheet["B2"].value == "json-ld"
        assert structured_sheet["C2"].value == "WebPage"

        links_sheet = workbook["Links"]
        assert links_sheet["D2"].fill.start_color.rgb == "FFD1E7DD"

        redirect_sheet = workbook["Redirect"]
        assert redirect_sheet["A2"].value == "Redirect chain"
        assert redirect_sheet["B3"].value == "0"
        assert redirect_sheet["B4"].value == "200"
        assert redirect_sheet["B4"].fill.start_color.rgb == "FFD1E7DD"

        robots_sheet = workbook["Robots"]
        assert robots_sheet["A2"].value == "Meta robots"
        assert robots_sheet["A4"].value == "Allow"
        assert robots_sheet["B4"].value == "/"
        assert robots_sheet["B4"].fill.start_color.rgb == "FFD1E7DD"

        performance_sheet = workbook["Performance"]
        assert performance_sheet["A2"].value == "HTTP status"
        assert performance_sheet["B2"].value == "200"
        assert performance_sheet["A7"].value == "Resource"
        assert performance_sheet["A8"].value == "CSS"
        assert performance_sheet["B8"].value == "12"
        assert performance_sheet["A12"].value == "Opportunities"
        assert "HTTP Archive Web Almanac" in performance_sheet["A13"].value
    finally:
        workbook.close()
