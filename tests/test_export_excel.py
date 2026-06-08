from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from silentfrog.crawl_types import CrawlPayload  # type: ignore[reportMissingImports]
from silentfrog.exporters import export_page_analysis  # type: ignore[reportMissingImports]
from silentfrog.exporters.action_workbook import ACTION_SHEET_NAMES  # type: ignore[reportMissingImports]
from silentfrog.image_diagnostics import normalize_image_row  # type: ignore[reportMissingImports]


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
            normalize_image_row(
                [
                    "https://example.com/logo.png",
                    "Alt",
                    "Title",
                    "image/png",
                    "100",
                    "200",
                    "10 KB",
                    "2h",
                    "Yes",
                    "High",
                    "100",
                    "200",
                    "",
                    "",
                    "",
                    "",
                ]
            )
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
            "summary": {"total": 1, "by_syntax": {"json-ld": 1}, "by_type": {"WebPage": 1}, "errors": []},
            "eligibility": [
                {
                    "type": "Product",
                    "detected": True,
                    "count": 1,
                    "eligibility": "Incomplete",
                    "missing_fields": ["missing offers.price", "missing offers.priceCurrency"],
                    "warnings": ["Missing required fields"],
                }
            ],
            "blocks": [
                {
                    "@context": "https://schema.org",
                    "@type": "WebPage",
                    "name": "Example Page",
                    "url": "https://example.com/page",
                    "_extracted_via": "json-ld",
                }
            ],
            "issues": [],
            "fallback_raw": [],
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
        "ai_crawl": [
            [
                "GPTBot",
                "gptbot",
                "Yes",
                "-",
                "-",
                "Allowed",
                "No explicit AI restrictions detected",
            ]
        ],
        "ai_visibility": {
            "summary": {
                "verdict": "Needs work",
                "good_count": 6,
                "warning_count": 2,
                "critical_count": 0,
            },
            "checks": [
                {
                    "area": "Access",
                    "check": "Audited AI and search agents can access the page",
                    "status": "good",
                    "details": "Allowed: GPTBot; Limited: -; Blocked: -.",
                    "recommendation": "Keep robots.txt open for the official AI and search agents you want to allow.",
                    "key": "access_agents",
                },
                {
                    "area": "Citation readiness",
                    "check": "Cross-surface metadata is present",
                    "status": "warning",
                    "details": "OpenGraph title/description: Yes; Twitter title/description: No.",
                    "recommendation": "Keep OpenGraph and Twitter metadata complete so the page is consistently represented outside the page body.",
                    "key": "citation_social",
                },
            ],
        },
        "content_quality": {
            "language": "English (en-US)",
            "word_count": 520,
            "paragraph_count": 8,
            "substantial_paragraph_count": 6,
            "average_words_per_paragraph": 24.5,
            "title_present": True,
            "meta_description_present": True,
            "h1_count": 1,
            "h2_h6_count": 3,
            "title_h1_alignment": "Aligned",
            "intro_paragraph": "Present",
            "thin_content_risk": "Low",
            "heading_structure": "Good",
            "verdict": "Strong",
        },
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
            "summary": {
                "transfer_size": 2100000,
                "total_resource_bytes": 1096000,
                "total_page_bytes": 3196000,
                "total_resource_count": 65,
                "third_party_bytes": 420000,
                "third_party_count": 8,
                "critical_issue_count": 2,
                "warning_issue_count": 2,
                "info_issue_count": 0,
                "verdict": "High performance risk",
            },
            "resource_summary": {
                "css": {"count": 12, "bytes": 96000},
                "js": {"count": 35, "bytes": 420000},
                "img": {"count": 18, "bytes": 580000},
            },
            "resource_breakdown": [
                {"type": "html", "count": 1, "bytes": 2100000},
                {"type": "css", "count": 12, "bytes": 96000},
                {"type": "js", "count": 35, "bytes": 420000},
                {"type": "img", "count": 18, "bytes": 580000},
                {"type": "font", "count": 0, "bytes": 0},
                {"type": "other", "count": 0, "bytes": 0},
            ],
            "issues": [
                {
                    "key": "page_weight",
                    "severity": "critical",
                    "message": "Total page weight is very high.",
                    "evidence": "Measured page weight is 3.0 MB.",
                    "recommendation": "Reduce heavy assets, defer non-critical resources, and compress media.",
                },
                {
                    "key": "js_weight",
                    "severity": "warning",
                    "message": "JavaScript payload is heavier than ideal.",
                    "evidence": "Measured JavaScript weight is 410.2 KB.",
                    "recommendation": "Review bundle size and defer non-critical scripts.",
                },
            ],
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
                {
                    "message": "High stylesheet count; inline critical CSS and combine static files.",
                    "severity": "warning",
                },
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

        def _row_values(sheet_name: str) -> list[list[object]]:
            sheet = workbook[sheet_name]
            return [[cell.value for cell in row] for row in sheet.iter_rows()]

        assert workbook.sheetnames[: len(ACTION_SHEET_NAMES)] == ACTION_SHEET_NAMES
        assert workbook["Executive summary"]["B2"].value == "Single page"
        assert workbook["Prioritized issues"]["A1"].value == "Severity"
        assert workbook["Prioritized issues"]["D2"].value == "Total page weight is very high."
        assert workbook["Affected URLs"]["A2"].value == "https://example.com"
        assert workbook["Technical actions"]["B2"].value == "Performance"
        assert (
            workbook["AI-GEO actions"]["D2"].value == "OpenGraph title/description: Yes; Twitter title/description: No."
        )
        assert workbook["Appendix - raw data"]["A2"].value == "Meta / Headers / Images"
        assert "Meta" in workbook.sheetnames
        assert "SERP Preview" in workbook.sheetnames
        assert "Structured summary" in workbook.sheetnames
        assert "Structured data" in workbook.sheetnames
        assert "Structured eligibility" in workbook.sheetnames
        assert "Performance" in workbook.sheetnames
        assert "Social" in workbook.sheetnames
        assert "Indexability" in workbook.sheetnames
        assert "Content quality" in workbook.sheetnames
        assert "AI crawl" in workbook.sheetnames
        assert "AI Visibility" in workbook.sheetnames

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

        images_sheet = workbook["Images"]
        assert images_sheet["E1"].value == "W"
        assert images_sheet["K1"].value == "Declared W"
        assert images_sheet["N1"].value == "Sizes"
        assert images_sheet["P2"].value

        summary_sheet = workbook["Structured summary"]
        assert summary_sheet["A2"].value == "Total items"
        assert summary_sheet["B2"].value == "1"

        eligibility_sheet = workbook["Structured eligibility"]
        assert eligibility_sheet["A2"].value == "Product"
        assert eligibility_sheet["C2"].value == "Incomplete"
        assert "missing offers.price" in (eligibility_sheet["D2"].value or "")

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

        ai_sheet = workbook["AI crawl"]
        assert ai_sheet["A1"].value == "Agent"
        assert ai_sheet["B1"].value == "Token"
        assert ai_sheet["D1"].value == "Nonstandard directive"
        assert ai_sheet["F2"].value == "Allowed"
        assert ai_sheet["F2"].fill.start_color.rgb == "FFD1E7DD"
        assert ai_sheet["G2"].value == "No explicit AI restrictions detected"

        ai_visibility_sheet = workbook["AI Visibility"]
        ai_visibility_rows = _row_values("AI Visibility")
        assert ai_visibility_sheet["A2"].value == "Verdict"
        assert ai_visibility_sheet["B2"].value == "Needs work"
        assert ai_visibility_sheet["B2"].fill.start_color.rgb == "FFFFF3CD"
        assert ai_visibility_sheet["A6"].value == "Total checks"
        assert ai_visibility_sheet["B6"].value == "2"
        assert ai_visibility_sheet["A9"].value == "Area"
        assert ai_visibility_sheet["B10"].value == "Audited AI and search agents can access the page"
        assert ai_visibility_sheet["C10"].value == "Good"
        assert ai_visibility_sheet["C10"].fill.start_color.rgb == "FFD1E7DD"
        assert ai_visibility_sheet["A11"].value == "Citation readiness"
        assert ai_visibility_sheet["C11"].value == "Warning"
        assert ai_visibility_sheet["C11"].fill.start_color.rgb == "FFFFF3CD"
        assert any(
            row[0] == "Citation readiness"
            and row[1] == "Cross-surface metadata is present"
            and "Twitter metadata complete" in str(row[4] or "")
            for row in ai_visibility_rows
        )

        indexability_sheet = workbook["Indexability"]
        assert indexability_sheet["A2"].value == "Requested URL"
        assert indexability_sheet["A4"].value == "Final status"
        assert indexability_sheet["B4"].value == "200"
        assert indexability_sheet["A14"].value == "Overall verdict"
        assert indexability_sheet["B14"].value == "Indexable"
        assert indexability_sheet["B14"].fill.start_color.rgb == "FFD1E7DD"

        content_quality_sheet = workbook["Content quality"]
        assert content_quality_sheet["A2"].value == "Page language"
        assert content_quality_sheet["B2"].value == "English (en-US)"
        assert content_quality_sheet["A14"].value == "Heading structure"
        assert content_quality_sheet["B15"].value == "Strong"
        assert content_quality_sheet["B15"].fill.start_color.rgb == "FFD1E7DD"

        performance_sheet = workbook["Performance"]
        performance_rows = _row_values("Performance")
        assert performance_sheet["A2"].value == "Verdict"
        assert performance_sheet["B2"].value == "High performance risk"
        assert performance_sheet["B2"].fill.start_color.rgb == "FFF8D7DA"
        assert performance_sheet["A6"].value == "Transfer (KB)"
        assert performance_sheet["B6"].value == f"{2100000 / 1024:.1f}"
        assert performance_sheet["A7"].value == "Resource bytes (KB)"
        assert performance_sheet["A8"].value == "Page weight (KB)"
        assert ["Resource", "Count", "Bytes", None] in performance_rows
        assert ["HTML", "1", f"{2100000 / 1024:.1f} KB", None] in performance_rows
        assert ["CSS", "12", f"{96000 / 1024:.1f} KB", None] in performance_rows
        assert ["Scripts", "Count", "Bytes", None] in performance_rows
        assert ["Blocking", "4", f"{320000 / 1024:.1f} KB", None] in performance_rows
        assert ["Severity", "Issue", "Evidence", "Recommendation"] in performance_rows
        assert any(
            row[0] == "Critical"
            and row[1] == "Total page weight is very high."
            and "Reduce heavy assets" in str(row[3] or "")
            for row in performance_rows
        )
        assert ["Severity", "Opportunity", None, None] in performance_rows
        assert any(
            "HTTP Archive Web Almanac" in str(row[1] or "") for row in performance_rows if row and row[0] == "Critical"
        )
        assert ["Type", "URL", "Script", "Bytes"] in performance_rows
        assert any(
            row[0] == "JS" and row[1] == "https://example.com/app.js" and row[3] == f"{420000 / 1024:.1f} KB"
            for row in performance_rows
        )
    finally:
        workbook.close()


def test_export_page_analysis_writes_ai_visibility_placeholder_when_empty(tmp_path: Path) -> None:
    payload = _sample_payload()
    payload = CrawlPayload.from_raw(
        {
            **payload.to_mapping(),
            "ai_visibility": {
                "summary": {"verdict": "", "good_count": 0, "warning_count": 0, "critical_count": 0},
                "checks": [],
            },
        }
    )
    out_file = tmp_path / "report-empty-ai.xlsx"

    export_page_analysis(payload, out_file)

    workbook = load_workbook(out_file)
    try:
        sheet = workbook["AI Visibility"]
        assert sheet["A2"].value == "Verdict"
        assert sheet["B2"].value == "-"
        assert sheet["A9"].value == "Area"
        assert sheet["A10"].value == "Info"
        assert sheet["B10"].value == "No AI visibility data yet"
        assert sheet["D10"].value == "Run an analysis to populate this sheet."
    finally:
        workbook.close()
