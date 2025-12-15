from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from silentfrog.crawl_types import CrawlPayload  # type: ignore[reportMissingImports]
from silentfrog.exporters import export_page_analysis  # type: ignore[reportMissingImports]


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
        "images": [
            ["https://example.com/logo.png", "Alt", "Title", "image/png", "100", "200", "10 KB", "2h", "Yes", "High"]
        ],
        "social": {
            "open_graph": {
                "title": "OG Title",
                "description": "OG Desc",
                "image": "https://example.com/og.png",
                "site_name": "Example",
                "url": "https://example.com",
                "card": "",
                "issues": ["Missing description"],
            },
            "twitter": {
                "title": "TW Title",
                "description": "TW Desc",
                "image": "https://example.com/tw.png",
                "site_name": "Example",
                "url": "https://example.com",
                "card": "summary_large_image",
                "issues": [],
            },
        },
        "links": [
            [
                "https://example.com",
                "Example",
                "Interno",
                "follow",
                "200",
                "OK",
                "Navigation",
                "Header",
                "com",
            ]
        ],
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
            "top_offenders": [
                {"type": "js", "url": "https://example.com/app.js", "bytes": 420000, "blocking": True},
                {"type": "img", "url": "https://example.com/hero.jpg", "bytes": 580000, "blocking": False},
            ],
            "scripts": {
                "blocking": {"count": 4, "bytes": 320000},
                "async": {"count": 31, "bytes": 720000},
            },
            "opportunity_details": [
                {
                    "message": "HTTP Archive Web Almanac (open source): Page weight is above 1.5 MB; compare with the community benchmarks (https://almanac.httparchive.org/en/2023/performance#page-weight)",
                    "severity": "critical",
                },
                {"message": "High stylesheet count; inline critical CSS and combine static files.", "severity": "warning"},
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
        assert "Social" in workbook.sheetnames

        meta_sheet = workbook["Meta"]
        assert meta_sheet["A2"].value == "title"
        assert meta_sheet["B2"].value == "Example Optimized Marketing Title"
        assert meta_sheet["C2"].fill.start_color.rgb == "FFD1E7DD"
        assert meta_sheet["A3"].value == "description"
        assert meta_sheet["B3"].value == "Foo"
        assert meta_sheet["C3"].fill.start_color.rgb == "FFFFF3CD"

        social_sheet = workbook["Social"]
        assert social_sheet["A2"].value == "OpenGraph"
        assert "Missing description" in (social_sheet["I2"].value or "")

        summary_sheet = workbook["Structured summary"]
        assert summary_sheet["A2"].value == "Total items"
        assert summary_sheet["B2"].value == "1"

        structured_sheet = workbook["Structured data"]
        assert structured_sheet["B2"].value == "json-ld"
        assert structured_sheet["C2"].value == "WebPage"

        links_sheet = workbook["Links"]
        assert links_sheet["E2"].fill.start_color.rgb == "FFD1E7DD"
        assert links_sheet["F2"].value == "OK"

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
        assert performance_sheet["A5"].value == "Transfer (KB)"
        assert performance_sheet["B5"].value == f"{2100000 / 1024:.1f}"
        assert performance_sheet["A6"].value == "Page weight (KB)"
        assert performance_sheet["A8"].value == "Resource"
        assert performance_sheet["A9"].value == "CSS"
        assert performance_sheet["B9"].value == "12"
        assert performance_sheet["A13"].value == "Scripts"
        assert performance_sheet["A14"].value == "Blocking"
        assert performance_sheet["B14"].value == "4"
        assert performance_sheet["A17"].value == "Severity"
        assert performance_sheet["A18"].value == "Critical"
        assert "HTTP Archive Web Almanac" in performance_sheet["B18"].value
        assert performance_sheet["A21"].value == "Type"
        assert performance_sheet["B22"].value == "https://example.com/app.js"
        assert performance_sheet["D22"].value == f"{420000 / 1024:.1f} KB"
    finally:
        workbook.close()
