"""v2.0 V5 — CLI `export` subcommand + Site Crawl AI-export button."""

from __future__ import annotations

import pytest

from silentfrog import cli
from silentfrog.crawl_types import CrawlPayload
from silentfrog.site_crawl_gui import SiteCrawlWindow
from silentfrog.site_crawl_types import SiteCrawlReport, SiteCrawlResult


def _payload(url: str, score: int = 60) -> CrawlPayload:
    return CrawlPayload.from_raw(
        {
            "meta": [["title", "T", "1"], ["description", "d", "1"]],
            "headers": [["h1", "T"]],
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
            "content_quality": {"word_count": 100},
            "ai_visibility": {
                "summary": {
                    "verdict": "Needs work",
                    "score": score,
                    "good_count": 0,
                    "warning_count": 1,
                    "critical_count": 0,
                },
                "checks": [
                    {
                        "area": "Content",
                        "check": "Thin content",
                        "status": "warning",
                        "details": "100 words",
                        "recommendation": "Add depth",
                        "key": "x",
                    }
                ],
            },
            "performance": {"summary": {"verdict": "Good"}},
            "social": {},
        }
    )


def test_cli_export_parser_accepts_command() -> None:
    args = cli._build_parser().parse_args(["export", "https://e.com/p", "--mode", "full"])
    assert args.command == "export"
    assert args.url == "https://e.com/p"
    assert args.mode == "full"


@pytest.mark.asyncio
async def test_cli_export_writes_md_and_json(tmp_path) -> None:
    args = cli._build_parser().parse_args(["export", "https://e.com/p", "--out", str(tmp_path / "audit")])

    async def _stub_analyser(url: str):
        return _payload(url, 60)

    code = await cli._export_cmd(args, analyser=_stub_analyser)
    assert code == 0
    assert (tmp_path / "audit.md").exists()
    assert (tmp_path / "audit.json").exists()
    assert "GEO Score: 60/100" in (tmp_path / "audit.md").read_text(encoding="utf-8")


def test_site_crawl_ai_export_button_present_and_disabled(qtbot) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    assert win.btn_export_ai.text() == "Export for AI analysis"
    assert win.btn_export_ai.isEnabled() is False  # nothing crawled yet


def test_site_crawl_ai_export_writes_files(qtbot, monkeypatch, tmp_path) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    results = [SiteCrawlResult.from_payload("https://e.com/p", _payload("https://e.com/p", 55))]
    win._latest_report = SiteCrawlReport.from_results(results, discovered_count=1)

    monkeypatch.setattr(
        "qtpy.QtWidgets.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(tmp_path / "crawl_ai.md"), "Markdown (*.md)"),
    )
    monkeypatch.setattr("qtpy.QtWidgets.QMessageBox.information", lambda *a, **k: None)
    win._export_ai()
    assert (tmp_path / "crawl_ai.md").exists()
    assert (tmp_path / "crawl_ai.json").exists()


def test_single_page_ai_export_writes_files(qtbot, monkeypatch, tmp_path) -> None:
    from silentfrog.seo_gui import WebpageSeoWindow

    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    win._latest_payload = _payload("https://e.com/page", 60)
    win.url_edit.setEditText("https://e.com/page")

    monkeypatch.setattr(
        "qtpy.QtWidgets.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(tmp_path / "page_ai.md"), "Markdown (*.md)"),
    )
    monkeypatch.setattr("qtpy.QtWidgets.QMessageBox.information", lambda *a, **k: None)
    win._export_ai()
    assert (tmp_path / "page_ai.md").exists()
    assert (tmp_path / "page_ai.json").exists()
    assert "https://e.com/page" in (tmp_path / "page_ai.md").read_text(encoding="utf-8")
