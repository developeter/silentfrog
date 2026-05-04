from __future__ import annotations

from pathlib import Path
import threading

from qtpy import QtCore, QtWidgets

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
    assert win.stack.currentWidget() is win.setup_page
    assert win.base_url.toolTip()
    assert win.btn_start.toolTip()
    assert win.progress.minimumHeight() >= 32


def test_start_crawl_button_populates_rows(monkeypatch, qtbot) -> None:
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
    win.base_url.setText("https://example.com")
    win.url_list.setPlainText("https://example.com/page")
    qtbot.mouseClick(win.btn_start, QtCore.Qt.MouseButton.LeftButton)

    assert win.model.rowCount() == 1
    assert win.stack.currentWidget() is win.results_page
    assert win.btn_export.isEnabled() is True
    assert win.progress.value() == 100
    assert "Found 1 URLs" in win.lbl_discovery.text()

    qtbot.mouseClick(win.btn_new_crawl, QtCore.Qt.MouseButton.LeftButton)

    assert win.stack.currentWidget() is win.setup_page


def test_site_crawl_highlighted_rows_keep_readable_foreground() -> None:
    model = SiteCrawlTableModel()
    model.set_results([SiteCrawlResult.skipped("https://example.com/skipped", "Cancelled")])
    index = model.index(0, 0)

    assert model.data(index, QtCore.Qt.ItemDataRole.BackgroundRole) is not None
    assert model.data(index, QtCore.Qt.ItemDataRole.ForegroundRole) is not None


def test_row_detail_uses_cached_payload(qtbot) -> None:
    result = SiteCrawlResult.from_payload("https://example.com/page", _payload())
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win.model.set_results([result])

    index = win.proxy.index(0, 0)
    win._open_result_detail(index)

    assert win._detail_windows
    assert isinstance(win._detail_windows[-1], SiteCrawlDetailDialog)
    assert win._detail_windows[-1].tabs.count() == 17
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
