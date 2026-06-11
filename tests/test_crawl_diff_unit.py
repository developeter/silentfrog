"""Unit tests for the v2.0 V8 crawl diff."""

from __future__ import annotations

from dataclasses import replace

from silentfrog.crawl_diff import diff_reports, diff_to_markdown
from silentfrog.site_crawl_types import SiteCrawlReport, SiteCrawlResult


def _result(url: str, status: str = "200", score: int = 80) -> SiteCrawlResult:
    base = SiteCrawlResult.failed(url, "")  # lightweight shell
    return replace(base, status=status, geo_score=score, indexability="Indexable")


def _report(results: list[SiteCrawlResult]) -> SiteCrawlReport:
    return SiteCrawlReport.from_results(results, discovered_count=len(results))


def test_new_and_removed_urls() -> None:
    prev = _report([_result("https://e.com/a"), _result("https://e.com/b")])
    curr = _report([_result("https://e.com/a"), _result("https://e.com/c")])
    diff = diff_reports(prev, curr)
    assert diff.new_urls == ("https://e.com/c",)
    assert diff.removed_urls == ("https://e.com/b",)


def test_status_change_detected() -> None:
    prev = _report([_result("https://e.com/a", status="200")])
    curr = _report([_result("https://e.com/a", status="404")])
    diff = diff_reports(prev, curr)
    assert len(diff.status_changes) == 1
    assert diff.status_changes[0].previous == "200"
    assert diff.status_changes[0].current == "404"


def test_score_improved_and_regressed_split() -> None:
    prev = _report([_result("https://e.com/up", score=60), _result("https://e.com/down", score=90)])
    curr = _report([_result("https://e.com/up", score=80), _result("https://e.com/down", score=70)])
    diff = diff_reports(prev, curr)
    assert [d.url for d in diff.improved] == ["https://e.com/up"]
    assert diff.improved[0].delta == 20
    assert [d.url for d in diff.regressed] == ["https://e.com/down"]
    assert diff.regressed[0].delta == -20


def test_regressed_sorted_most_negative_first() -> None:
    prev = _report([_result("https://e.com/a", score=90), _result("https://e.com/b", score=90)])
    curr = _report([_result("https://e.com/a", score=80), _result("https://e.com/b", score=50)])
    diff = diff_reports(prev, curr)
    assert [d.url for d in diff.regressed] == ["https://e.com/b", "https://e.com/a"]  # -40 before -10


def test_no_changes_is_empty() -> None:
    prev = _report([_result("https://e.com/a", score=80)])
    curr = _report([_result("https://e.com/a", score=80)])
    diff = diff_reports(prev, curr)
    assert diff.is_empty


def test_diff_to_markdown_lists_sections() -> None:
    prev = _report([_result("https://e.com/a", status="200", score=90), _result("https://e.com/gone")])
    curr = _report([_result("https://e.com/a", status="500", score=70), _result("https://e.com/new")])
    md = diff_to_markdown(diff_reports(prev, curr))
    assert "New URLs" in md
    assert "https://e.com/new" in md
    assert "Removed URLs" in md
    assert "https://e.com/gone" in md
    assert "Status changes" in md
    assert "200 -> 500" in md
    assert "Regressed" in md


def test_diff_to_markdown_empty() -> None:
    prev = _report([_result("https://e.com/a")])
    curr = _report([_result("https://e.com/a")])
    assert "No changes" in diff_to_markdown(diff_reports(prev, curr))


def test_diff_to_dict_roundtrips_shape() -> None:
    prev = _report([_result("https://e.com/a", score=90)])
    curr = _report([_result("https://e.com/a", score=70), _result("https://e.com/b")])
    data = diff_reports(prev, curr).to_dict()
    assert data["new_urls"] == ["https://e.com/b"]
    assert data["regressed"][0]["url"] == "https://e.com/a"


def test_gui_diff_button_disabled_without_previous(qtbot) -> None:
    from silentfrog.site_crawl_gui import SiteCrawlWindow

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    assert win.btn_diff.isEnabled() is False  # no previous crawl yet


def test_gui_diff_dialog_opens_with_both_reports(qtbot, monkeypatch) -> None:
    from silentfrog.site_crawl_gui import SiteCrawlWindow

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._previous_report = _report([_result("https://e.com/a", score=90)])
    win._latest_report = _report([_result("https://e.com/a", score=70), _result("https://e.com/new")])

    captured: dict[str, str] = {}
    monkeypatch.setattr(
        "qtpy.QtWidgets.QDialog.show",
        lambda self: captured.setdefault("title", self.windowTitle()),
    )
    win._show_diff()
    assert "comparison" in captured["title"].lower()
