from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from silentfrog.crawl_types import CrawlPayload
from silentfrog.exporters import export_page_analysis


def _sample_payload() -> CrawlPayload:
    raw = {
        "meta": [["description", "Foo", "123"], ["robots", "index, follow", "12"]],
        "headers": [["h1", "Title"]],
        "images": [["https://example.com/logo.png", "Alt", "Title", "100", "200", "10 KB"]],
        "links": [["https://example.com", "Example", "Follow", "200"]],
        "schema": [{"@context": "https://schema.org", "_extracted_via": "json-ld"}],
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
        "keywords": [["keyword", "5"]],
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

        meta_sheet = workbook["Meta"]
        assert meta_sheet["A2"].value == "description"
        assert meta_sheet["B2"].value == "Foo"
        assert meta_sheet["C2"].fill.start_color.rgb == "FFD1E7DD"

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
    finally:
        workbook.close()
