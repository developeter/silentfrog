"""v3 G10 — llms.txt GENERATOR half (build_llms_txt / export_llms_txt) +
the GUI button and CLI flag that expose it."""

from __future__ import annotations

from pathlib import Path

import pytest
from qtpy import QtCore, QtWidgets

from silentfrog import cli
from silentfrog.crawl_run_repository import CrawlRunRef, stream_report_results
from silentfrog.crawl_store import CrawlStore, StoredAudit
from silentfrog.crawl_types import CrawlPayload
from silentfrog.exporters.llms_txt import build_llms_txt, export_llms_txt
from silentfrog.site_crawl_gui import SiteCrawlWindow
from silentfrog.site_crawl_types import SiteCrawlReport, SiteCrawlResult


def _payload(
    url: str,
    *,
    title: str = "Example Title",
    description: str = "Useful description text.",
    meta_robots: str = "index, follow",
    hops: int = 0,
) -> CrawlPayload:
    return CrawlPayload.from_raw(
        {
            "meta": [["title", title, str(len(title))], ["description", description, str(len(description))]],
            "headers": [["h1", title or "Untitled"]],
            "images": [],
            "links": [],
            "schema": {"summary": {"total": 0, "by_type": {}}, "blocks": [], "issues": []},
            "canonical": {"target": url, "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": [url], "hops": hops, "final_status": "200", "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": meta_robots,
            "hreflang": [],
            "ai_crawl": [],
            "serp": {},
            "serp_audit": {},
            "keywords": [],
            "content_quality": {"word_count": 200},
            "ai_visibility": {
                "summary": {"verdict": "Strong", "score": 80, "good_count": 1, "warning_count": 0, "critical_count": 0},
                "checks": [],
            },
            "performance": {"summary": {"verdict": "Good"}},
            "social": {},
        }
    )


def _result(url: str, **payload_kwargs) -> SiteCrawlResult:
    return SiteCrawlResult.from_payload(url, _payload(url, **payload_kwargs))


def _report(results: list[SiteCrawlResult], base_url: str = "https://example.com/") -> SiteCrawlReport:
    return SiteCrawlReport.from_results(results, discovered_count=len(results), base_url=base_url)


# --- build_llms_txt: shape ---------------------------------------------------


def test_build_llms_txt_groups_and_orders_sections_by_page_count() -> None:
    results = [
        _result("https://example.com/blog/a", title="Blog A"),
        _result("https://example.com/blog/b", title="Blog B"),
        _result("https://example.com/blog/c", title="Blog C"),
        _result("https://example.com/docs/x", title="Docs X"),
    ]
    doc = build_llms_txt(_report(results), results)
    assert doc.index("## Blog") < doc.index("## Docs")  # 3 pages beats 1


def test_build_llms_txt_home_page_lands_in_home_section() -> None:
    results = [
        _result("https://example.com/", title="Homepage"),
        _result("https://example.com/about", title="About"),
    ]
    doc = build_llms_txt(_report(results), results)
    assert "## Home" in doc
    assert "- Homepage: https://example.com/" in doc


def test_build_llms_txt_caps_sections_at_twelve() -> None:
    # 13 top-level segments, one page each (tied count) -> tie-break by name,
    # so the alphabetically-last segment is the one dropped by the cap.
    results = [_result(f"https://example.com/seg{index:02d}/page") for index in range(13)]
    doc = build_llms_txt(_report(results), results)
    assert doc.count("## ") == 12
    assert "## Seg00" in doc
    assert "## Seg12" not in doc


def test_build_llms_txt_caps_links_per_section_at_twenty() -> None:
    results = [_result(f"https://example.com/blog/p{index:02d}") for index in range(25)]
    doc = build_llms_txt(_report(results), results)
    assert doc.count("\n- ") == 20


def test_build_llms_txt_links_within_a_section_are_url_sorted() -> None:
    results = [
        _result("https://example.com/blog/z"),
        _result("https://example.com/blog/a"),
    ]
    doc = build_llms_txt(_report(results), results)
    assert doc.index("/blog/a") < doc.index("/blog/z")


def test_build_llms_txt_is_deterministic() -> None:
    results = [
        _result("https://example.com/blog/b", title="B"),
        _result("https://example.com/blog/a", title="A"),
        _result("https://example.com/docs/x", title="X"),
    ]
    report = _report(results)
    assert build_llms_txt(report, results) == build_llms_txt(report, results)


# --- build_llms_txt: eligibility filter --------------------------------------


def test_build_llms_txt_excludes_noindex_and_failed_pages() -> None:
    results = [
        _result("https://example.com/good", title="Good Page"),
        _result("https://example.com/blocked", title="Blocked Page", meta_robots="noindex, follow"),
        _result("https://example.com/redirected", title="Redirected Page", hops=1),
        SiteCrawlResult.failed("https://example.com/broken", "boom"),
        SiteCrawlResult.skipped("https://example.com/skipped", "limit reached"),
    ]
    doc = build_llms_txt(_report(results), results)
    assert "Good Page" in doc
    assert "Blocked Page" not in doc
    assert "Redirected Page" not in doc
    assert "https://example.com/broken" not in doc
    assert "https://example.com/skipped" not in doc


def test_build_llms_txt_no_eligible_pages_still_produces_header() -> None:
    results = [SiteCrawlResult.failed("https://example.com/broken", "boom")]
    doc = build_llms_txt(_report(results), results)
    assert doc.startswith("# ")
    assert "## " not in doc


# --- build_llms_txt: H1 / summary fallbacks ----------------------------------


def test_build_llms_txt_h1_uses_home_title_when_available() -> None:
    results = [_result("https://example.com/", title="My Homepage")]
    doc = build_llms_txt(_report(results), results)
    assert doc.splitlines()[0] == "# My Homepage"


def test_build_llms_txt_h1_falls_back_to_host_without_home_page() -> None:
    results = [_result("https://example.com/about", title="About")]
    doc = build_llms_txt(_report(results), results)
    assert doc.splitlines()[0] == "# example.com"


def test_build_llms_txt_summary_uses_home_meta_description() -> None:
    results = [_result("https://example.com/", title="Home", description="We build tools for AI agents.")]
    doc = build_llms_txt(_report(results), results)
    assert "> We build tools for AI agents." in doc


def test_build_llms_txt_summary_falls_back_to_neutral_line_without_home_description() -> None:
    results = [_result("https://example.com/about", title="About")]
    doc = build_llms_txt(_report(results), results)
    assert "> Curated page index for AI assistants — generated by Silentfrog." in doc


# --- build_llms_txt: sanitization --------------------------------------------


def test_build_llms_txt_sanitizes_hostile_title_with_newline_and_hash() -> None:
    hostile = "Evil\n# Injected Heading"
    results = [_result("https://example.com/evil", title=hostile)]
    doc = build_llms_txt(_report(results), results)
    # Only the real H1 line may start with "# " — the hostile newline must not
    # forge a second heading line at column 0.
    heading_lines = [line for line in doc.splitlines() if line.startswith("# ")]
    assert heading_lines == ["# example.com"]
    assert "- Evil # Injected Heading: https://example.com/evil" in doc


def test_build_llms_txt_hostile_description_does_not_break_blockquote_structure() -> None:
    hostile = "Fine print\n> forged second blockquote line"
    results = [_result("https://example.com/", title="Home", description=hostile)]
    doc = build_llms_txt(_report(results), results)
    blockquote_lines = [line for line in doc.splitlines() if line.startswith(">")]
    assert blockquote_lines == ["> Fine print > forged second blockquote line"]


# --- export_llms_txt: I/O ----------------------------------------------------


def test_export_llms_txt_writes_file_with_trailing_newline(tmp_path: Path) -> None:
    results = [_result("https://example.com/", title="Home")]
    report = _report(results)
    target = tmp_path / "llms.txt"

    export_llms_txt(report, target)

    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_export_llms_txt_streams_only_once(monkeypatch, tmp_path: Path) -> None:
    calls: list[object] = []
    original = stream_report_results

    def _counting_stream(report):
        calls.append(report)
        return original(report)

    monkeypatch.setattr("silentfrog.exporters.llms_txt.stream_report_results", _counting_stream)
    results = [_result("https://example.com/", title="Home")]
    report = _report(results)
    target = tmp_path / "llms.txt"

    export_llms_txt(report, target)

    assert len(calls) == 1


def test_export_llms_txt_store_backed_matches_in_memory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path / "data"))
    url = "https://example.com/only"
    payload = _payload(url, title="Only Page")
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
    target = tmp_path / "llms.txt"
    export_llms_txt(run_report, target)
    text = target.read_text(encoding="utf-8")

    assert "Only Page" in text
    assert url in text


# --- GUI button (cloning tests/test_llm_export_cli_gui.py's pattern) --------


def test_llms_txt_button_present_and_disabled(qtbot) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    assert win.btn_llms_txt.text() == "Generate llms.txt"
    assert win.btn_llms_txt.isEnabled() is False  # nothing crawled yet


def test_llms_txt_button_uses_export_llms_txt(monkeypatch, qtbot, tmp_path: Path) -> None:
    results = [_result("https://example.com/page", title="Page")]
    report = _report(results)
    target = tmp_path / "llms.txt"
    called: dict[str, object] = {}

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(
        "silentfrog.site_crawl_gui.export_llms_txt",
        lambda value, path: called.update(report=value, path=path),
    )

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._latest_report = report
    win.btn_llms_txt.setEnabled(True)
    qtbot.mouseClick(win.btn_llms_txt, QtCore.Qt.MouseButton.LeftButton)

    assert called["report"] is report
    assert called["path"] == target


def test_llms_txt_button_enforces_txt_suffix_and_writes_real_file(monkeypatch, qtbot, tmp_path: Path) -> None:
    results = [_result("https://example.com/page", title="Page")]
    report = _report(results)
    target_stub = tmp_path / "my_llms"  # no suffix supplied by the save dialog

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target_stub), ""))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._latest_report = report
    win.btn_llms_txt.setEnabled(True)
    qtbot.mouseClick(win.btn_llms_txt, QtCore.Qt.MouseButton.LeftButton)

    written = tmp_path / "my_llms.txt"
    assert written.exists()
    assert "Page" in written.read_text(encoding="utf-8")


# --- CLI ----------------------------------------------------------------


def test_build_parser_accepts_out_llms_txt_flag() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["crawl", "https://example.com/"])
    assert args.out_llms_txt is None

    args = parser.parse_args(["crawl", "https://example.com/", "--out-llms-txt", "llms.txt"])
    assert args.out_llms_txt == Path("llms.txt")


async def _stub_crawl_fn(config, timeout, store):
    results = [_result(config.base_url, title="Home")]
    return SiteCrawlReport.from_results(results, discovered_count=1, base_url=config.base_url)


@pytest.mark.asyncio
async def test_crawl_cmd_out_llms_txt_writes_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    out = tmp_path / "llms.txt"
    parser = cli._build_parser()
    args = parser.parse_args(["crawl", "https://example.com/", "--out-llms-txt", str(out)])

    exit_code = await cli._crawl_cmd(args, crawl_fn=_stub_crawl_fn)

    assert exit_code == 0
    assert out.exists()
    assert out.read_text(encoding="utf-8").startswith("# ")
