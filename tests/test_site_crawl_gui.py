from __future__ import annotations

from pathlib import Path
import threading

from qtpy import QtCore, QtWidgets

import silentfrog.site_crawl_gui as site_crawl_gui  # type: ignore[reportMissingImports]
from silentfrog.crawl_history import CrawlHistoryStore  # type: ignore[reportMissingImports]
from silentfrog.crawl_types import CrawlPayload  # type: ignore[reportMissingImports]
from silentfrog.image_diagnostics import ACTUAL_WIDTH_COL, CACHE_COL, SIZE_COL, normalize_image_row  # type: ignore[reportMissingImports]
from silentfrog.site_crawl_gui import SiteCrawlDetailDialog, SiteCrawlTableModel, SiteCrawlWindow  # type: ignore[reportMissingImports]
from silentfrog.site_crawl_types import DEFAULT_SITE_CRAWL_LIMIT, SiteCrawlReport, SiteCrawlResult  # type: ignore[reportMissingImports]


def _payload(url: str = "https://example.com/page", images: list[list[str]] | None = None) -> CrawlPayload:
    return CrawlPayload.from_raw(
        {
            "meta": [["title", "Example Title", "13"], ["description", "Useful description text.", "24"]],
            "headers": [["h1", "Example Title"]],
            "images": images or [],
            "links": [],
            "schema": {"summary": {"total": 1, "by_type": {"WebPage": 1}}, "blocks": [], "issues": []},
            "canonical": {"target": url, "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": [url], "hops": 0, "final_status": "200", "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": "index, follow",
            "hreflang": [],
            "ai_crawl": [],
            "serp": {"title": "Example Title", "description": "", "url": url, "site_name": "", "breadcrumb": "", "favicon": ""},
            "serp_audit": {},
            "keywords": [],
            "content_quality": {},
            "ai_visibility": {"summary": {"verdict": "Strong", "good_count": 1, "warning_count": 0, "critical_count": 0}, "checks": []},
            "performance": {"summary": {"verdict": "Good"}},
            "social": {},
        }
    )


def test_site_crawl_window_defaults(qtbot) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)

    assert win.windowTitle() == "Silentfrog - Site Crawl"
    assert win.limit_spin.value() == DEFAULT_SITE_CRAWL_LIMIT
    assert win._crawl_options.gentle_mode is True
    assert win.btn_export.isEnabled() is False
    assert win.btn_stop.isEnabled() is False
    assert win.btn_stop.isHidden() is True
    assert win.stack.currentWidget() is win.setup_page
    assert win.base_url.toolTip()
    assert win.btn_start.toolTip()
    assert win.btn_history_setup.text() == "View past scans"
    assert win.btn_history.text() == "View past scans"
    assert win.progress.minimumHeight() >= 32
    assert win.lbl_eta.text() == "ETA: -"
    assert win.recap_widget.health_text().startswith("<b>Ready</b>")
    assert win.lbl_history.text() == "History: no completed crawl yet."


def test_site_crawl_setup_form_grows_fields_to_row_width(qtbot) -> None:
    """Regression: macOS Qt 6.11 defaults a QFormLayout to
    `FieldsStayAtSizeHint`, so the LineEdits ended up small and
    centred in the window. We pin the policy on every platform.
    """
    from qtpy import QtWidgets

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    forms = win.setup_page.findChildren(QtWidgets.QFormLayout)
    assert forms, "setup page must own at least one QFormLayout"
    form = forms[0]
    assert (
        form.fieldGrowthPolicy()
        == QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
    )
    assert (
        form.rowWrapPolicy()
        == QtWidgets.QFormLayout.RowWrapPolicy.DontWrapRows
    )


def test_site_crawl_window_opens_history_browser(monkeypatch, qtbot, tmp_path: Path) -> None:
    opened: dict[str, object] = {}

    class FakeHistoryDialog:
        def __init__(self, store, parent=None) -> None:
            opened["store"] = store
            opened["parent"] = parent

        def exec(self) -> int:
            opened["exec"] = True
            return QtWidgets.QDialog.Accepted

    monkeypatch.setattr("silentfrog.site_crawl_gui.CrawlHistoryDialog", FakeHistoryDialog)

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._history_store = CrawlHistoryStore(tmp_path)
    qtbot.mouseClick(win.btn_history_setup, QtCore.Qt.MouseButton.LeftButton)

    assert opened["store"] is win._history_store
    assert opened["parent"] is win
    assert opened["exec"] is True


def test_start_crawl_button_populates_rows(monkeypatch, qtbot, tmp_path: Path) -> None:
    payload = _payload()
    result = SiteCrawlResult.from_payload("https://example.com/page", payload)
    report = SiteCrawlReport.from_results([result], discovered_count=1)

    def fake_run_site_crawl(config, timeout, on_progress, on_success, on_error):
        on_progress({"event": "discovered", "total": 1})
        on_progress({"event": "row", "result": result, "completed": 1})
        on_success(report)
        return threading.Thread(), threading.Event()

    monkeypatch.setattr("silentfrog.site_crawl_gui.run_site_crawl", fake_run_site_crawl)

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._history_store = CrawlHistoryStore(tmp_path)
    win.base_url.setText("https://example.com")
    win.url_list.setPlainText("https://example.com/page")
    qtbot.mouseClick(win.btn_start, QtCore.Qt.MouseButton.LeftButton)

    assert win.model.rowCount() == 1
    assert win.stack.currentWidget() is win.results_page
    assert win.btn_export.isEnabled() is True
    assert win.btn_stop.isHidden() is True
    assert win.lbl_eta.text() == "ETA: complete"
    assert win.progress.value() == 100
    assert "Found 1 URLs" in win.lbl_discovery.text()
    assert "Healthy" in win.recap_widget.health_text()
    assert "saved first run" in win.lbl_history.text()

    qtbot.mouseClick(win.btn_new_crawl, QtCore.Qt.MouseButton.LeftButton)

    assert win.stack.currentWidget() is win.setup_page


def test_site_crawl_stop_button_only_visible_while_running(qtbot) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)

    win._set_running(True)

    assert win.btn_stop.isHidden() is False
    assert win.btn_stop.isEnabled() is True

    win._set_running(False)

    assert win.btn_stop.isHidden() is True


def test_site_crawl_eta_updates_from_completed_rows(monkeypatch, qtbot) -> None:
    current_time = {"value": 100.0}
    monkeypatch.setattr(site_crawl_gui, "monotonic", lambda: current_time["value"])
    win = SiteCrawlWindow()
    qtbot.addWidget(win)

    win._handle_progress({"event": "discovered", "total": 4})
    current_time["value"] = 110.0
    win._append_progress_row({"event": "row", "completed": 1})

    assert win.lbl_eta.text() == "ETA: 30s remaining"


def test_site_crawl_recap_issue_activation_filters_to_url(qtbot, tmp_path: Path) -> None:
    result = SiteCrawlResult.failed("https://example.com/fail", "boom")
    report = SiteCrawlReport.from_results([result], discovered_count=1)
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._history_store = CrawlHistoryStore(tmp_path)

    win._show_results()
    win._handle_report(report)
    item = win.recap_widget.action_list.item(0)
    win.recap_widget.action_list.itemActivated.emit(item)

    assert win.search_edit.text() == "https://example.com/fail"
    assert win.table.selectionModel().hasSelection()


def test_site_crawl_history_label_compares_previous_run(qtbot, tmp_path: Path) -> None:
    failed = SiteCrawlResult.failed("https://example.com/fail", "boom")
    fixed = SiteCrawlResult.from_payload("https://example.com/fail", _payload("https://example.com/fail"))
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._history_store = CrawlHistoryStore(tmp_path)

    win._handle_report(SiteCrawlReport.from_results([failed], discovered_count=1))
    win._handle_report(SiteCrawlReport.from_results([fixed], discovered_count=1))

    assert "1 fixed" in win.lbl_history.text()
    assert "Health improved" in win.lbl_history.text()


def test_site_crawl_coloring_keeps_skipped_neutral_and_errors_readable() -> None:
    model = SiteCrawlTableModel()
    model.set_results([
        SiteCrawlResult.skipped("https://example.com/skipped", "Cancelled"),
        SiteCrawlResult.failed("https://example.com/error", "boom"),
    ])

    skipped = model.index(0, 0)
    error = model.index(1, 0)

    assert model.data(skipped, QtCore.Qt.ItemDataRole.BackgroundRole) is None
    assert model.data(error, QtCore.Qt.ItemDataRole.BackgroundRole) is not None
    assert model.data(error, QtCore.Qt.ItemDataRole.ForegroundRole) is not None


def test_site_crawl_table_uses_crawler_overview_columns() -> None:
    raw = _payload("https://example.com/page").to_mapping()
    payload = CrawlPayload.from_raw(
        {
            **raw,
            "headers": [["h1", "First"], ["h1", "Second"]],
            "links": [["https://example.com/missing", "Missing", "Interno", "follow", "404", "Client error", "Body", "", "com"]],
            "content_quality": {"word_count": 240},
        }
    )
    result = SiteCrawlResult.from_payload("https://example.com/page", payload)
    model = SiteCrawlTableModel()
    model.set_results([result])

    headers = [
        model.headerData(column, QtCore.Qt.Orientation.Horizontal, QtCore.Qt.ItemDataRole.DisplayRole)
        for column in range(model.columnCount())
    ]
    row = [model.index(0, column).data() for column in range(model.columnCount())]

    assert headers == [
        "URL",
        "Status",
        "Indexability",
        "Title",
        "Meta desc",
        "Canonical",
        "H1",
        "Words",
        "Img issues",
        "Link issues",
        "Schema",
        "Hreflang",
        "Issues",
    ]
    assert "Final URL" not in headers
    assert "Performance" not in headers
    assert "AI Visibility" not in headers
    assert row[6] == "Multiple (2)"
    assert row[7] == 240
    assert row[9] == 1
    assert "H1: Multiple (2)" in str(row[-1])
    assert model.headerData(12, QtCore.Qt.Orientation.Horizontal, QtCore.Qt.ItemDataRole.ToolTipRole)


def test_row_detail_uses_cached_payload(qtbot) -> None:
    result = SiteCrawlResult.from_payload("https://example.com/page", _payload())
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win.model.set_results([result])

    index = win.proxy.index(0, 0)
    win._open_result_detail(index)

    assert win._detail_windows
    assert isinstance(win._detail_windows[-1], SiteCrawlDetailDialog)
    assert win._detail_windows[-1].tabs.count() == 18
    assert win._detail_windows[-1].tabs.tabText(0) == "Recap"
    assert win._detail_windows[-1].btn_img_dl.text() == "Analyze images"


def test_site_crawl_detail_can_analyze_images(monkeypatch, qtbot) -> None:
    image_row = normalize_image_row(["https://example.com/img.png", "Alt", "Title", "-", "", "", "", "", "Lazy", "High"])
    updates: list[CrawlPayload] = []

    def fake_run_image_analysis(base, rows, timeout, on_success, on_error):
        on_success([[rows[0][0], 640, 320, "42 KB", "image/png", "30m"]])
        return threading.Thread()

    monkeypatch.setattr("silentfrog.site_crawl_gui.run_image_analysis", fake_run_image_analysis)

    dialog = SiteCrawlDetailDialog(
        _payload(images=[image_row]),
        "https://example.com/page",
        on_payload_updated=updates.append,
    )
    qtbot.addWidget(dialog)
    qtbot.mouseClick(dialog.btn_img_dl, QtCore.Qt.MouseButton.LeftButton)

    row = dialog.images_tab.rows()[0]
    assert row[ACTUAL_WIDTH_COL] == "640"
    assert row[SIZE_COL] == "42 KB"
    assert row[CACHE_COL] == "30m"
    assert updates[-1].images[0][SIZE_COL] == "42 KB"


def test_export_site_crawl_button_uses_bulk_export(monkeypatch, qtbot, tmp_path: Path) -> None:
    result = SiteCrawlResult.from_payload("https://example.com/page", _payload())
    report = SiteCrawlReport.from_results([result], discovered_count=1)
    target = tmp_path / "site-crawl.xlsx"
    called: dict[str, object] = {}

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr("silentfrog.site_crawl_gui.export_site_crawl_report", lambda value, path: called.update(report=value, path=path))

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._latest_report = report
    win.btn_export.setEnabled(True)
    qtbot.mouseClick(win.btn_export, QtCore.Qt.MouseButton.LeftButton)

    assert called["report"] is report
    assert called["path"] == target
