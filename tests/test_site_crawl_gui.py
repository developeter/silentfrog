from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from qtpy import QtCore, QtWidgets

import silentfrog.site_crawl_gui as site_crawl_gui  # type: ignore[reportMissingImports]
from silentfrog.audit_issues import (  # type: ignore[reportMissingImports]
    AuditIssue,
    IssueCategory,
    IssueSeverity,
)
from silentfrog.content_clusters import ClusterMap, ClusterPoint  # type: ignore[reportMissingImports]
from silentfrog.crawl_diff import diff_reports  # type: ignore[reportMissingImports]
from silentfrog.crawl_history import CrawlHistoryStore  # type: ignore[reportMissingImports]
from silentfrog.crawl_run_repository import CrawlRunRef  # type: ignore[reportMissingImports]
from silentfrog.crawl_store import CrawlStore, StoredAudit  # type: ignore[reportMissingImports]
from silentfrog.crawl_types import CrawlPayload  # type: ignore[reportMissingImports]
from silentfrog.image_diagnostics import (  # type: ignore[reportMissingImports]
    ACTUAL_WIDTH_COL,
    CACHE_COL,
    SIZE_COL,
    normalize_image_row,
)
from silentfrog.link_graph import GraphInput, build_link_graph  # type: ignore[reportMissingImports]
from silentfrog.link_graph.cluster_view import ClusterMapView  # type: ignore[reportMissingImports]
from silentfrog.link_graph.graph_view import LinkGraphView  # type: ignore[reportMissingImports]
from silentfrog.site_crawl_gui import (  # type: ignore[reportMissingImports]
    SiteCrawlDetailDialog,
    SiteCrawlTableModel,
    SiteCrawlWindow,
    StoredCrawlTableModel,
)
from silentfrog.site_crawl_types import (  # type: ignore[reportMissingImports]
    DEFAULT_SITE_CRAWL_LIMIT,
    SiteCrawlReport,
    SiteCrawlResult,
)


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
            "serp": {
                "title": "Example Title",
                "description": "",
                "url": url,
                "site_name": "",
                "breadcrumb": "",
                "favicon": "",
            },
            "serp_audit": {},
            "keywords": [],
            "content_quality": {},
            "ai_visibility": {
                "summary": {"verdict": "Strong", "good_count": 1, "warning_count": 0, "critical_count": 0},
                "checks": [],
            },
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
    assert win.btn_redirect_map.text() == "Map redirects"
    assert win.btn_redirect_map.isEnabled() is False
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
    assert form.fieldGrowthPolicy() == QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
    assert form.rowWrapPolicy() == QtWidgets.QFormLayout.RowWrapPolicy.DontWrapRows


def test_site_crawl_window_opens_history_browser(monkeypatch, qtbot, tmp_path: Path) -> None:
    opened: dict[str, object] = {}

    class _FakeSignal:
        def connect(self, *_a, **_k) -> None:
            pass

    class FakeHistoryDialog:
        openRunRequested = _FakeSignal()

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

    def fake_run_site_crawl(config, timeout, on_progress, on_success, on_error, store_path=None):
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


def test_second_button_driven_crawl_retains_previous_report(monkeypatch, qtbot, tmp_path: Path) -> None:
    # The only UI path to a second crawl is Results -> "New crawl" -> "Start crawl".
    # _start_crawl() used to null out _latest_report before the crawl ran, so
    # _handle_report's "previous = latest" always captured None instead of the
    # just-finished prior run -- permanently disabling "Compare with previous"
    # and "Map redirects" after a user's very first re-crawl.
    result1 = SiteCrawlResult.from_payload("https://example.com/run1", _payload("https://example.com/run1"))
    result2 = SiteCrawlResult.from_payload("https://example.com/run2", _payload("https://example.com/run2"))
    report1 = SiteCrawlReport.from_results([result1], discovered_count=1)
    report2 = SiteCrawlReport.from_results([result2], discovered_count=1)
    calls = {"n": 0}

    def fake_run_site_crawl(config, timeout, on_progress, on_success, on_error, store_path=None):
        calls["n"] += 1
        report, result = (report1, result1) if calls["n"] == 1 else (report2, result2)
        on_progress({"event": "discovered", "total": 1})
        on_progress({"event": "row", "result": result, "completed": 1})
        on_success(report)
        return threading.Thread(), threading.Event()

    monkeypatch.setattr("silentfrog.site_crawl_gui.run_site_crawl", fake_run_site_crawl)

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._history_store = CrawlHistoryStore(tmp_path)
    win.base_url.setText("https://example.com")
    win.url_list.setPlainText("https://example.com/run1")
    qtbot.mouseClick(win.btn_start, QtCore.Qt.MouseButton.LeftButton)

    assert win._latest_report is report1
    assert win._previous_report is None  # no prior run yet -- expected

    qtbot.mouseClick(win.btn_new_crawl, QtCore.Qt.MouseButton.LeftButton)
    win.url_list.setPlainText("https://example.com/run2")
    qtbot.mouseClick(win.btn_start, QtCore.Qt.MouseButton.LeftButton)

    assert win._latest_report is report2
    assert win._previous_report is report1
    assert win.btn_diff.isEnabled() is True
    assert win.btn_redirect_map.isEnabled() is True


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


def test_finalizing_event_enters_finalizing_state(qtbot) -> None:
    # item 5: the worker's 'finalizing' event (emitted before the report is built)
    # shows the post-fetch phase and disables Stop with an explanatory tooltip.
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._set_running(True)  # Stop visible + enabled while running

    win._handle_progress({"event": "finalizing"})

    assert win.btn_stop.isEnabled() is False
    assert "cannot be stopped" in win.btn_stop.toolTip()
    assert "Finalizing" in win.progress.format()
    assert "finalizing" in win.lbl_eta.text().lower()


def test_progress_does_not_finalize_when_completed_reaches_seed_total(qtbot) -> None:
    # item 5 regression: a spider/hybrid crawl's discovered total is only the seed
    # count and is never bumped as links are found, so `completed` reaches it
    # mid-crawl. Reaching it must NOT finalize or disable Stop — only the worker's
    # explicit 'finalizing' event does. Reintroducing a completed>=total trigger
    # would disable Stop here and fail this test.
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._set_running(True)
    win._handle_progress({"event": "discovered", "total": 1})  # one seed

    win._append_progress_row({"event": "row", "completed": 1})  # completed == seed total

    assert win.btn_stop.isEnabled() is True
    assert "Finalizing" not in win.progress.format()


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


def test_site_crawl_recap_issue_activation_resets_active_status_filter(qtbot, tmp_path: Path) -> None:
    healthy = SiteCrawlResult.from_payload("https://example.com/ok", _payload("https://example.com/ok"))
    failed = SiteCrawlResult.failed("https://example.com/fail", "boom")
    # A healthy "200" row alongside the failed one: item 4's status filter now
    # only offers statuses this run actually has, so "200" must be present
    # for setCurrentText("200") below to take effect.
    report = SiteCrawlReport.from_results([healthy, failed], discovered_count=2)
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._history_store = CrawlHistoryStore(tmp_path)

    win._show_results()
    win._handle_report(report)
    win.status_filter.setCurrentText("200")  # excludes the "error"-status row
    item = win.recap_widget.action_list.item(0)
    win.recap_widget.action_list.itemActivated.emit(item)

    assert win.status_filter.currentText() == "All"
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
    model.set_results(
        [
            SiteCrawlResult.skipped("https://example.com/skipped", "Cancelled"),
            SiteCrawlResult.failed("https://example.com/error", "boom"),
        ]
    )

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
            "links": [
                [
                    "https://example.com/missing",
                    "Missing",
                    "Interno",
                    "follow",
                    "404",
                    "Client error",
                    "Body",
                    "",
                    "com",
                ]
            ],
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
        "GEO",  # v3: GEO Score column ported from the retired Multi-URL Dashboard
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
    assert row[3] == result.geo_score
    assert row[7] == "Multiple (2)"
    assert row[8] == 240
    assert row[10] == 1
    assert "H1: Multiple (2)" in str(row[-1])
    assert model.headerData(13, QtCore.Qt.Orientation.Horizontal, QtCore.Qt.ItemDataRole.ToolTipRole)


def test_row_detail_uses_cached_payload(qtbot) -> None:
    result = SiteCrawlResult.from_payload("https://example.com/page", _payload())
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win.model.set_results([result])

    index = win.proxy.index(0, 0)
    win._open_result_detail(index)

    assert win._detail_windows
    detail = win._detail_windows[-1]
    assert isinstance(detail, SiteCrawlDetailDialog)
    # V19-A2: the detail dialog groups the same tab classes into Overview + 5 buckets.
    outer_labels = [detail.tabs.tabText(i) for i in range(detail.tabs.count())]
    assert outer_labels == ["Recap", "Indexability", "Content", "Speed", "Trust", "AI/GEO"]
    for label in [
        "Meta tag",
        "Header H1-H6",
        "Images",
        "Social",
        "Link",
        "Redirect",
        "Canonical",
        "Indexability",
        "Robots",
        "Hreflang",
        "Structured data",
        "Content quality",
        "Keywords",
        "Bot Matrix",
        "AI Visibility",
        "Performance",
        "SERP",
        "Accessibility",
    ]:
        assert detail._bucketed.contains(label)
    assert detail.btn_img_dl.text() == "Analyze images"


def test_site_crawl_detail_recap_navigates_to_bucketed_tab(qtbot) -> None:
    # V19-A2: the detail dialog's recap is now wired to bucketed navigation.
    dialog = SiteCrawlDetailDialog(_payload(), "https://example.com/page")
    qtbot.addWidget(dialog)
    issue = AuditIssue(
        issue_id="perf_demo",
        category=IssueCategory.PERFORMANCE,
        severity=IssueSeverity.CRITICAL,
        source="Performance",
        reason="demo",
        recommendation="demo",
        evidence=(),
    )

    dialog.recap_tab.issueActivated.emit(issue)

    assert dialog.tabs.tabText(dialog.tabs.currentIndex()) == "Speed"
    speed_bucket = dialog.tabs.currentWidget()
    assert speed_bucket.tabText(speed_bucket.currentIndex()) == "Performance"


def test_site_crawl_results_charts_populate_from_report(qtbot) -> None:
    # V19-A3: the results screen renders crawl-level distribution charts fed by
    # read-only repository aggregates (the in-memory seam for a store-less report).
    from silentfrog.charts import DistributionChart, charts_available

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    results = [
        SiteCrawlResult.from_payload("https://e.com/a", _payload()),
        SiteCrawlResult.failed("https://e.com/b", "boom"),
    ]
    report = SiteCrawlReport.from_results(results, discovered_count=2, base_url="https://e.com/")

    assert win._charts_strip.isHidden()  # 6a: hidden during discovery / before data

    win._update_charts(report)

    assert not win._charts_strip.isHidden()  # shown once populated
    assert isinstance(win._status_chart, DistributionChart)
    assert isinstance(win._score_chart, DistributionChart)
    if not charts_available():
        status_text = " ".join(lbl.text() for lbl in win._status_chart.findChildren(QtWidgets.QLabel))
        score_text = " ".join(lbl.text() for lbl in win._score_chart.findChildren(QtWidgets.QLabel))
        assert status_text and status_text != "No data yet."
        assert "0-20" in score_text


def test_site_crawl_detail_can_analyze_images(monkeypatch, qtbot) -> None:
    image_row = normalize_image_row(
        ["https://example.com/img.png", "Alt", "Title", "-", "", "", "", "", "Lazy", "High"]
    )
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


# --- PR-10: SQL-backed paged/sorted/filtered model + diff DB lifecycle ---


def _build_store(tmp_path: Path, name: str, rows: list[tuple[str, str, int]]) -> tuple[Path, SiteCrawlReport]:
    """A file-backed store + store-backed report (rows = url, http_status, score)."""
    db = tmp_path / name
    store = CrawlStore(db)
    run_id = store.start_run("e.com", "https://e.com/", "spider")
    for url, status, score in rows:
        store.save_audit(
            run_id, StoredAudit(url=url, http_status=status, indexability="Indexable", title=url, geo_score=score)
        )
    store.finish_run(run_id)
    store.close()
    report = SiteCrawlReport.from_run(
        CrawlRunRef(db, run_id),
        discovered_count=len(rows),
        crawled_count=len(rows),
        skipped_count=0,
        failed_count=0,
    )
    return db, report


def test_store_backed_report_drives_sql_paged_model(qtbot, tmp_path: Path) -> None:
    _, report = _build_store(tmp_path, "crawl.db", [(f"https://e.com/{i}", "200", 80) for i in range(5)])
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._history_store = CrawlHistoryStore(tmp_path)

    win._handle_report(report)

    assert win._stored_model is not None
    assert win.table.model() is win._stored_model
    assert win._stored_model.rowCount() == 5
    assert win.model.rowCount() == 0  # live in-memory rows are freed (no materialisation)
    urls = {win._stored_model.index(r, 0).data() for r in range(win._stored_model.rowCount())}
    assert urls == {f"https://e.com/{i}" for i in range(5)}


def test_stored_model_filters_and_sorts_via_sql(qtbot, tmp_path: Path) -> None:
    rows = [("https://e.com/a", "200", 90), ("https://e.com/b", "404", 0), ("https://e.com/c", "200", 70)]
    _, report = _build_store(tmp_path, "crawl.db", rows)
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._history_store = CrawlHistoryStore(tmp_path)
    win._handle_report(report)
    model = win._stored_model

    win.status_filter.setCurrentText("404")  # routed through the GUI combo
    assert model.rowCount() == 1
    assert model.index(0, 0).data() == "https://e.com/b"

    win.status_filter.setCurrentText("All")
    assert model.rowCount() == 3
    win.search_edit.setText("e.com/c")
    assert model.rowCount() == 1
    assert model.index(0, 0).data() == "https://e.com/c"

    win.search_edit.clear()
    model.sort(0, QtCore.Qt.SortOrder.DescendingOrder)
    assert model.index(0, 0).data() == "https://e.com/c"  # url DESC


def test_paged_model_keeps_memory_bounded(qtbot, tmp_path: Path) -> None:
    rows = [(f"https://e.com/{i:05d}", "200", 80) for i in range(1000)]
    _, report = _build_store(tmp_path, "crawl.db", rows)
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._history_store = CrawlHistoryStore(tmp_path)
    win._handle_report(report)
    model = win._stored_model

    assert model.rowCount() == 1000
    for row in (0, 150, 350, 550, 750, 999):  # touch rows spread across many pages
        assert model.index(row, 0).data() is not None
    assert len(model._pages) <= site_crawl_gui._MAX_CACHED_PAGES  # bounded window, not all rows


def test_in_memory_model_caps_live_window() -> None:
    # The live stream is capped to a rolling window so an in-progress store-backed
    # crawl never materialises all rows; the most recent rows are kept.
    model = SiteCrawlTableModel(max_rows=3)
    for i in range(5):
        model.add_result(SiteCrawlResult.failed(f"https://e.com/{i}", "x"))
    assert model.rowCount() == 3
    assert [model.index(r, 0).data() for r in range(3)] == [f"https://e.com/{i}" for i in (2, 3, 4)]


def test_previous_run_retained_so_diff_sees_both(qtbot, tmp_path: Path) -> None:
    # Repairs the dead "Compare with previous" path: the immediately-previous run's
    # store must survive the next crawl so the diff can stream both runs. If the
    # lifecycle regressed to deleting the current store, the previous DB would be
    # gone and the diff would see an empty "previous" (everything "new").
    db_a, report_a = _build_store(
        tmp_path, "a.db", [("https://e.com/gone", "200", 80), ("https://e.com/keep", "200", 80)]
    )
    _, report_b = _build_store(tmp_path, "b.db", [("https://e.com/keep", "404", 80), ("https://e.com/new", "200", 80)])
    win = SiteCrawlWindow()
    qtbot.addWidget(win)

    win._crawl_store_path = str(db_a)
    win._roll_store_generation()  # db_a becomes "previous" and must be retained

    assert db_a.exists()
    assert win._previous_store_path == str(db_a)
    win._previous_report = report_a
    win._latest_report = report_b
    diff = diff_reports(win._previous_report, win._latest_report)
    assert "https://e.com/gone" in diff.removed_urls
    assert "https://e.com/new" in diff.new_urls
    assert any(change.url == "https://e.com/keep" for change in diff.status_changes)


def test_roll_store_generation_retains_stores_and_prunes_beyond_cap(monkeypatch, qtbot, tmp_path: Path) -> None:
    # v3 retention: rolling no longer unlinks two-crawls-ago (saved scans must
    # stay openable from history); instead a prune caps crawl_*.db files.
    import os as _os

    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    crawls = tmp_path / "crawls"
    crawls.mkdir()
    stale: list[Path] = []
    for i in range(12):
        p = crawls / f"crawl_stale{i:02d}.db"
        p.write_bytes(b"x")
        _os.utime(p, (1_000_000 + i, 1_000_000 + i))  # oldest-first mtimes
        stale.append(p)
    older = crawls / "crawl_older.db"
    older.write_bytes(b"z")  # two-crawls-ago; fresh mtime -> retained
    previous = crawls / "crawl_previous.db"
    previous.write_bytes(b"y")
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._previous_store_path = str(older)
    win._crawl_store_path = str(previous)

    win._roll_store_generation()

    assert older.exists()  # v3: two-crawls-ago is RETAINED (was unlinked pre-v3)
    assert previous.exists()
    assert win._previous_store_path == str(previous)
    survivors = sorted(p.name for p in crawls.glob("crawl_stale*.db"))
    # 13 prunable candidates (12 stale + older), cap 10 -> the 3 oldest go.
    assert len(survivors) == 9
    assert stale[0].name not in survivors


def test_close_event_keeps_stores_on_disk(qtbot, tmp_path: Path) -> None:
    # v3 retention regression: closing the window used to unlink both stores,
    # which made every saved scan unopenable the moment the window closed.
    live = tmp_path / "crawl_live.db"
    live.write_bytes(b"x")
    previous = tmp_path / "crawl_prev.db"
    previous.write_bytes(b"y")
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._crawl_store_path = str(live)
    win._previous_store_path = str(previous)
    win.close()
    assert live.exists()
    assert previous.exists()


def test_close_event_stops_eta_timer_and_detaches_crawl_signals(qtbot) -> None:
    # Regression: closeEvent used to request cancellation but leave the ETA
    # QTimer running and the crawl worker's cross-thread signals connected --
    # safe only because the window was never actually destroyed. Once a
    # window CAN be destroyed on close (WA_DeleteOnClose in gui.py), a
    # callback landing on a dangling connection is the crash class the
    # R1/R3/R4 lifetime work removed.
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    bridge = win._attach_crawl_bridge()
    win._eta_timer.start()
    assert win._eta_timer.isActive()

    win.close()

    assert not win._eta_timer.isActive()
    # A stray callback from the still-running background thread must no
    # longer reach the window's own handlers.
    assert win._crawl_bridge is None
    before = win._discovered_total
    bridge.progress.emit({"event": "discovered", "total": 5})
    QtWidgets.QApplication.processEvents()
    assert win._discovered_total == before

    # A second close (Qt permits calling closeEvent more than once) must not
    # raise despite everything already being disconnected/stopped.
    win.close()


def test_close_event_closes_tracked_detail_windows(qtbot) -> None:
    # Regression: SiteCrawlDetailDialog (and the graph/cluster/diff dialogs
    # that share _detail_windows) are independent top-level QDialogs, not
    # embedded in the parent -- closing the Site Crawl window used to leave
    # any open one fully visible.
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    dialog = QtWidgets.QDialog(win)
    dialog.show()
    win._detail_windows.append(dialog)
    assert dialog.isVisible()

    win.close()

    assert not dialog.isVisible()


def test_detach_crawl_signals_targets_only_this_windows_own_slot(qtbot) -> None:
    # Regression: _detach_crawl_signals used to call signal.disconnect() with
    # no argument, dropping every receiver on the crawl bridge's
    # progress/report/error -- harmless only because each signal happened to
    # have exactly one connection. An unrelated receiver added by something
    # else must survive this window's own close.
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    bridge = win._attach_crawl_bridge()
    calls: list[dict] = []
    bridge.progress.connect(calls.append)

    win.close()
    bridge.progress.emit({"event": "discovered", "total": 3})
    QtWidgets.QApplication.processEvents()

    assert calls == [{"event": "discovered", "total": 3}]
    # This window's own handler is still gone.
    before = win._discovered_total
    assert before != 3


def test_close_event_unparents_tracked_detail_windows(qtbot) -> None:
    # Regression: a tracked SiteCrawlDetailDialog is opened with parent=self,
    # so leaving it parented after close() (which only hides it) means this
    # window's own later destruction (WA_DeleteOnClose in gui.py) cascades
    # into destroying the dialog too -- and an in-flight run_image_analysis
    # callback that still holds a reference to the dialog then raises
    # RuntimeError on dialog.imageSig.emit(...) the same way a callback into
    # a destroyed SiteCrawlWindow does. Dropping the parent link on close
    # means this window's destruction cannot take the dialog down with it.
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    dialog = QtWidgets.QDialog(win)
    dialog.show()
    win._detail_windows.append(dialog)
    assert dialog.parent() is win

    win.close()

    assert dialog.parent() is None
    assert win._detail_windows == []


def test_status_filter_reflects_statuses_present_in_report(qtbot, tmp_path: Path) -> None:
    # Regression: the status dropdown was a fixed curated list, not
    # exhaustive of what the crawler can emit, with no other way to isolate
    # an unlisted status. It must instead reflect what THIS run actually has.
    healthy = SiteCrawlResult.from_payload("https://example.com/ok", _payload("https://example.com/ok"))
    failed = SiteCrawlResult.failed("https://example.com/fail", "boom")
    report = SiteCrawlReport.from_results([healthy, failed], discovered_count=2)
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._history_store = CrawlHistoryStore(tmp_path)

    win._handle_report(report)

    items = [win.status_filter.itemText(i) for i in range(win.status_filter.count())]
    assert items[0] == "All"
    assert set(items[1:]) == {"200", "error"}
    assert "404" not in items  # never crawled, so never offered


def test_status_filter_gains_live_statuses_before_any_report_lands(qtbot) -> None:
    # Regression: _sync_status_filter_items only ran from _update_charts (report
    # completion / history reopen) and _start_crawl clears the table, so during a
    # live crawl the dropdown offered nothing to filter the rows already on
    # screen by. Each progress row must contribute its own unseen status.
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win.status_filter.setCurrentText("All")
    assert win._latest_report is None

    for url, status in (("https://example.com/a", "418"), ("https://example.com/b", "503")):
        result = replace(SiteCrawlResult.from_payload(url, _payload(url)), status=status)
        win._handle_progress({"event": "row", "completed": 1, "result": result})

    items = [win.status_filter.itemText(i) for i in range(win.status_filter.count())]
    assert items[0] == "All"  # "All" stays first
    assert "418" in items
    assert "503" in items
    assert len(items) == len(set(items))  # no duplicates
    assert win.status_filter.currentText() == "All"  # selection untouched
    assert win._latest_report is None  # still mid-crawl: no report has landed

    # A repeat of an already-listed status must not append a second entry.
    repeat = replace(
        SiteCrawlResult.from_payload("https://example.com/c", _payload("https://example.com/c")),
        status="418",
    )
    win._handle_progress({"event": "row", "completed": 2, "result": repeat})
    assert [win.status_filter.itemText(i) for i in range(win.status_filter.count())] == items


def test_status_filter_drops_the_previous_runs_statuses_on_a_zero_row_run(qtbot, tmp_path: Path) -> None:
    # Regression: _update_charts returns early when a run produced no audited
    # rows, which used to skip the dropdown sync too -- so a crawl that
    # returned nothing left the previous run's statuses (e.g. "404") on
    # offer, filtering an empty table by a status it can no longer contain.
    crawled = SiteCrawlResult.from_payload("https://example.com/ok", _payload("https://example.com/ok"))
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._history_store = CrawlHistoryStore(tmp_path)
    win._handle_report(SiteCrawlReport.from_results([crawled], discovered_count=1))
    assert [win.status_filter.itemText(i) for i in range(win.status_filter.count())] == ["All", "200"]

    win._handle_report(SiteCrawlReport.from_results([], discovered_count=0))

    assert [win.status_filter.itemText(i) for i in range(win.status_filter.count())] == ["All"]
    assert win.status_filter.currentText() == "All"


def test_status_filter_populates_the_same_way_for_a_stored_run(qtbot, tmp_path: Path) -> None:
    # The same sync must happen when a saved scan is reopened from history
    # (_open_stored_run), not only for a live crawl (_handle_report).
    from silentfrog.crawl_history import build_history_run

    db = tmp_path / "crawl_saved.db"
    store = CrawlStore(db)
    run_id = store.start_run("e.com", "https://e.com/", "spider")
    store.save_audit(
        run_id,
        StoredAudit(url="https://e.com/a", http_status="404", indexability="Not indexable", title="A", geo_score=0),
    )
    store.finish_run(run_id)
    store.close()
    report = SiteCrawlReport.from_run(
        CrawlRunRef(db, run_id), discovered_count=1, crawled_count=1, skipped_count=0, failed_count=0
    )
    history_run = build_history_run(report)
    win = SiteCrawlWindow()
    qtbot.addWidget(win)

    win._open_stored_run(history_run)

    items = [win.status_filter.itemText(i) for i in range(win.status_filter.count())]
    assert items == ["All", "404"]


def test_open_stored_run_binds_paged_model_and_detail_payload(qtbot, tmp_path: Path) -> None:
    # v3: opening a saved scan from history drives the SQL-paged table AND the
    # per-page detail loader from the stored run.
    from silentfrog.crawl_history import build_history_run

    # A store with a persisted payload blob so the detail-load path is exercised.
    db = tmp_path / "crawl_saved.db"
    store = CrawlStore(db)
    run_id = store.start_run("e.com", "https://e.com/", "spider")
    store.save_audit(
        run_id,
        StoredAudit(
            url="https://e.com/p",
            http_status="200",
            indexability="Indexable",
            title="P",
            geo_score=80,
            payload=_payload().to_mapping(),
        ),
    )
    store.finish_run(run_id)
    store.close()
    report = SiteCrawlReport.from_run(
        CrawlRunRef(db, run_id), discovered_count=1, crawled_count=1, skipped_count=0, failed_count=0
    )
    history_run = build_history_run(report)
    assert history_run.has_store  # linkage captured from report.run_ref

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._open_stored_run(history_run)

    assert isinstance(win._stored_model, StoredCrawlTableModel)
    assert win._stored_model.rowCount() == 1
    assert win._stored_model.index(0, 0).data() == "https://e.com/p"
    assert win._crawl_run_id == report.run_ref.run_id
    payload = win._load_payload_for_detail("https://e.com/p")
    assert payload is not None  # detail dialog path reads the stored payload


def test_open_stored_run_blocked_while_crawl_is_active(monkeypatch, qtbot, tmp_path: Path) -> None:
    # Regression: opening a saved scan from History while a crawl is still
    # running used to silently hide Stop and re-enable Start, because
    # _open_stored_run unconditionally called _set_running(False) -- the same
    # UI-only toggle _handle_report/_show_error use on completion -- even
    # though the background crawl thread was still alive and its cancel Event
    # was never set. That orphaned the live crawl's only cancel path (Stop,
    # now hidden) and let its later completion silently overwrite whatever
    # the user opened next. _crawl_active tracks "a thread is genuinely in
    # flight" independently of _set_running, and _open_stored_run must refuse
    # to touch running/report state while it is True.
    from silentfrog.crawl_history import build_history_run

    release_first = threading.Event()
    thread_started = threading.Event()

    def fake_run_site_crawl(config, timeout, on_progress, on_success, on_error, store_path=None):
        cancel_event = threading.Event()

        def _target():
            thread_started.set()
            release_first.wait(timeout=5)  # still "running" until the test releases it
            on_success(SiteCrawlReport.from_results([], discovered_count=0, base_url=config.base_url))

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        return t, cancel_event

    monkeypatch.setattr(site_crawl_gui, "run_site_crawl", fake_run_site_crawl)
    warned = {"n": 0}
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a, **k: warned.__setitem__("n", warned["n"] + 1))

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._history_store = CrawlHistoryStore(tmp_path)
    win.base_url.setText("https://live.test/")
    win._start_crawl()
    qtbot.waitUntil(lambda: thread_started.is_set(), timeout=3000)

    live_cancel = win._active_cancel
    assert win._crawl_active is True
    assert win.btn_stop.isHidden() is False
    assert win.btn_start.isEnabled() is False

    _, saved_report = _build_store(tmp_path, "crawl_saved.db", [("https://e.com/p", "200", 80)])
    history_run = build_history_run(saved_report)

    try:
        win._open_stored_run(history_run)

        assert warned["n"] == 1, "opening a saved scan during a live crawl must warn, not silently switch"
        assert win.btn_stop.isHidden() is False, "Stop control got hidden while a crawl is still running"
        assert win.btn_start.isEnabled() is False, "Start got re-enabled while a crawl is still running"
        assert win._active_cancel is live_cancel, "the live crawl's cancel token must not be displaced"
        assert live_cancel.is_set() is False
        assert win._crawl_run_id == "", "the live run's id must not be swapped for the opened history run's"
    finally:
        release_first.set()
        qtbot.waitUntil(lambda: win._crawl_active is False, timeout=3000)


def test_stored_model_owns_connection_on_building_thread(qtbot, tmp_path: Path) -> None:
    # The SQL model opens its own read connection on the thread that builds it
    # (the GUI thread), and reads succeed there without locking out a writer.
    db, report = _build_store(tmp_path, "crawl.db", [("https://e.com/p", "200", 80)])
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._history_store = CrawlHistoryStore(tmp_path)
    win._handle_report(report)

    assert isinstance(win._stored_model, StoredCrawlTableModel)
    assert win._stored_model.rowCount() == 1
    assert win._stored_model.index(0, 0).data() == "https://e.com/p"
    store2 = CrawlStore(db)  # a separate connection to the same file still works
    assert store2.count(report.run_ref.run_id) == 1
    store2.close()


def test_export_site_crawl_button_uses_bulk_export(monkeypatch, qtbot, tmp_path: Path) -> None:
    result = SiteCrawlResult.from_payload("https://example.com/page", _payload())
    report = SiteCrawlReport.from_results([result], discovered_count=1)
    target = tmp_path / "site-crawl.xlsx"
    called: dict[str, object] = {}

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(
        "silentfrog.site_crawl_gui.export_site_crawl_report",
        lambda value, path: called.update(report=value, path=path),
    )

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._latest_report = report
    win.btn_export.setEnabled(True)
    qtbot.mouseClick(win.btn_export, QtCore.Qt.MouseButton.LeftButton)

    # The bulk exporter derives its run-bound repository from the report's
    # CrawlRunRef itself (H2), so the button just hands it the report + path.
    assert called["report"] is report
    assert called["path"] == target


def test_export_tooltips_disclose_filters_are_not_applied(qtbot) -> None:
    # All four export paths (_export_excel/_export_html_report/_export_llms_txt/
    # _export_ai) always export self._latest_report / stream_report_results(...)
    # in full -- they never consult the search/status/indexability filter row
    # (self.proxy / self._stored_model). That's invisible to the user unless the
    # tooltip says so, so each export button's tooltip must disclose it.
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    for btn in (win.btn_export, win.btn_html_report, win.btn_export_ai, win.btn_llms_txt):
        tip = btn.toolTip().lower()
        assert "filter" in tip, f"{btn.text()} tooltip does not disclose filter/export mismatch"


def test_html_report_button_present_and_disabled(qtbot) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    assert win.btn_html_report.text() == "Export HTML report"
    assert win.btn_html_report.isEnabled() is False  # nothing crawled yet


def test_export_html_report_button_uses_export_site_crawl_html(monkeypatch, qtbot, tmp_path: Path) -> None:
    result = SiteCrawlResult.from_payload("https://example.com/page", _payload())
    report = SiteCrawlReport.from_results([result], discovered_count=1)
    target = tmp_path / "silentfrog_report.html"
    called: dict[str, object] = {}

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(
        "silentfrog.site_crawl_gui.export_site_crawl_html",
        lambda value, path: called.update(report=value, path=path),
    )

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._latest_report = report
    win.btn_html_report.setEnabled(True)
    qtbot.mouseClick(win.btn_html_report, QtCore.Qt.MouseButton.LeftButton)

    assert called["report"] is report
    assert called["path"] == target


def test_export_html_report_button_writes_real_self_contained_file(monkeypatch, qtbot, tmp_path: Path) -> None:
    # No ".html" suffix supplied by the save dialog — the handler must enforce
    # it (same convention as _export_excel), and the export itself is real
    # (not mocked) so this exercises the busy-cursor + suffix-enforcement path.
    result = SiteCrawlResult.from_payload("https://example.com/page", _payload())
    report = SiteCrawlReport.from_results([result], discovered_count=1, base_url="https://example.com")
    target_stub = tmp_path / "silentfrog_report"

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target_stub), ""))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path / "data"))

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._latest_report = report
    win.btn_html_report.setEnabled(True)
    qtbot.mouseClick(win.btn_html_report, QtCore.Qt.MouseButton.LeftButton)

    written = tmp_path / "silentfrog_report.html"
    assert written.exists()
    text = written.read_text(encoding="utf-8")
    assert "https://example.com" in text
    assert "Generated" in text
    assert "<script" not in text.lower()


# --- item 1/3: link-graph dialog wiring (node click + caption/banner/controls) ---


def _graph_inputs(orphan_count: int = 0) -> list[GraphInput]:
    """Homepage + linked children, plus ``orphan_count`` pages reached with no
    internal parent (discovered_from="")."""
    rows = [GraphInput("https://e.com/", "", 90), GraphInput("https://e.com/a", "https://e.com/", 80)]
    rows += [GraphInput(f"https://e.com/o{i}", "", 50) for i in range(orphan_count)]
    return rows


def test_graph_node_click_opens_page_detail(monkeypatch, qtbot) -> None:
    # item 1: LinkGraphView emits node_clicked, but the dialog never connected it,
    # so the legend's "click to open" did nothing. _build_graph_dialog now wires it
    # to the same run-bound payload loader the results-table double-click uses.
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(win, "_load_payload_for_detail", lambda url: _payload(url))
    inputs = _graph_inputs()
    graph = build_link_graph(inputs, root_url="https://e.com/")
    view = LinkGraphView()
    qtbot.addWidget(view)
    view.set_graph(graph)

    dialog = win._build_graph_dialog(graph, view, len(inputs))
    qtbot.addWidget(dialog)
    view.node_clicked.emit("https://e.com/a")  # what a node click emits

    assert win._detail_windows
    assert isinstance(win._detail_windows[-1], SiteCrawlDetailDialog)


def test_graph_inputs_from_store_reads_read_only_history_db(qtbot, tmp_path: Path) -> None:
    # Regression: _graph_inputs_from_store used to open a reopened history run's
    # store via the write-capable CrawlStore(...) (which runs apply_schema --
    # CREATE TABLE/PRAGMA/commit -- on open) just to read graph edges, wrapped
    # in a bare `except Exception: return []`. A Windows read-only file
    # attribute (a common way users "protect" old scan files) then made that
    # write-side open raise `OperationalError: attempt to write a readonly
    # database`, silently swallowed into an empty list -- so "Link graph" told
    # the user "No crawl data to graph yet" even though the run has data and is
    # perfectly readable (SqliteCrawlRunRepository succeeds against the same
    # file). read_graph_inputs opens the file READ-ONLY instead.
    import os
    import stat

    db = tmp_path / "crawl_history.db"
    store = CrawlStore(db)
    run_id = store.start_run("e.com", "https://e.com/", "spider")
    store.save_audit(run_id, StoredAudit(url="https://e.com/p", http_status="200", geo_score=80))
    store.finish_run(run_id)
    store.close()
    os.chmod(db, stat.S_IREAD)  # Windows "read-only" file attribute
    try:
        win = SiteCrawlWindow()
        qtbot.addWidget(win)
        win._crawl_store_path = str(db)
        win._crawl_run_id = run_id

        rows = win._graph_inputs_from_store()

        assert rows == [("https://e.com/p", "", 80)]
    finally:
        os.chmod(db, stat.S_IWRITE)  # restore so tmp_path cleanup can delete it


def test_graph_caption_notes_sampling_when_sampled(qtbot) -> None:
    rows = _graph_inputs() + [GraphInput(f"https://e.com/c{i}", "https://e.com/", 50) for i in range(10)]
    sampled = build_link_graph(rows, root_url="https://e.com/", max_nodes=5)
    full = build_link_graph(rows, root_url="https://e.com/")

    sampled_label = site_crawl_gui._graph_caption(sampled, total=len(rows))
    full_label = site_crawl_gui._graph_caption(full, total=len(rows))
    qtbot.addWidget(sampled_label)
    qtbot.addWidget(full_label)

    assert f"showing the top 5 of {len(rows)} by links" in sampled_label.text()
    assert "showing the top" not in full_label.text()


def test_graph_orphan_banner_threshold(qtbot) -> None:
    # >=60% of pages with no internal parent -> warning banner; below -> none.
    high = build_link_graph(_graph_inputs(orphan_count=4), root_url="https://e.com/")
    low = build_link_graph(_graph_inputs(orphan_count=0), root_url="https://e.com/")

    banner = site_crawl_gui._graph_orphan_banner(high, total=6)  # 4 orphans of 6
    assert banner is not None
    qtbot.addWidget(banner)
    assert "no parent" in banner.text()
    assert site_crawl_gui._graph_orphan_banner(low, total=2) is None  # 0 orphans of 2


def test_graph_dialog_assembles_controls_and_banner(qtbot) -> None:
    # item 3: the dialog carries Fit all / Reset zoom controls (callable) and shows
    # the orphan banner for a high-orphan crawl.
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    inputs = _graph_inputs(orphan_count=4)
    graph = build_link_graph(inputs, root_url="https://e.com/")
    view = LinkGraphView()
    qtbot.addWidget(view)
    view.set_graph(graph)

    dialog = win._build_graph_dialog(graph, view, len(inputs))
    qtbot.addWidget(dialog)

    buttons = {b.text(): b for b in dialog.findChildren(QtWidgets.QPushButton)}
    assert "Fit all" in buttons
    assert "Reset zoom" in buttons
    buttons["Fit all"].click()  # callable without crashing
    buttons["Reset zoom"].click()
    labels = " ".join(lbl.text() for lbl in dialog.findChildren(QtWidgets.QLabel))
    assert "orphan page(s)" in labels  # caption
    assert "no parent" in labels  # orphan banner (high ratio)


# --- v3 G5: Topic map (content-cluster) dialog wiring ---


def test_cluster_map_view_renders_dots_and_click_emits_url(qtbot) -> None:
    cluster_map = ClusterMap(
        points=(
            ClusterPoint(url="https://e.com/a", title="A", x=0.0, y=0.0, cluster=0),
            ClusterPoint(url="https://e.com/b", title="B", x=1.0, y=1.0, cluster=1),
            ClusterPoint(url="https://e.com/c", title="C", x=2.0, y=0.5, cluster=0),
        ),
        cluster_count=2,
        sampled=False,
        measured=True,
    )
    view = ClusterMapView()
    qtbot.addWidget(view)
    view.set_cluster_map(cluster_map)

    from silentfrog.link_graph.cluster_view import _DotItem  # type: ignore[reportMissingImports]

    dots = [i for i in view.scene().items() if isinstance(i, _DotItem)]
    assert len(dots) == 3

    captured: list[str] = []
    view.node_clicked.connect(captured.append)
    dots[0]._on_click(dots[0]._url)
    assert captured and captured[0].startswith("https://e.com/")


def test_cluster_dialog_assembles_caption_legend_controls_and_wires_click(monkeypatch, qtbot) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(win, "_load_payload_for_detail", lambda url: _payload(url))
    cluster_map = ClusterMap(
        points=(
            ClusterPoint(url="https://e.com/a", title="A", x=0.0, y=0.0, cluster=0),
            ClusterPoint(url="https://e.com/b", title="B", x=1.0, y=0.0, cluster=1),
        ),
        cluster_count=2,
        sampled=True,
        measured=True,
    )
    view = ClusterMapView()
    qtbot.addWidget(view)
    view.set_cluster_map(cluster_map)

    dialog = win._build_cluster_dialog(cluster_map, view)
    qtbot.addWidget(dialog)

    buttons = {b.text(): b for b in dialog.findChildren(QtWidgets.QPushButton)}
    assert "Fit all" in buttons
    assert "Reset zoom" in buttons
    assert "Close" in buttons
    buttons["Fit all"].click()  # callable without crashing
    buttons["Reset zoom"].click()

    labels = " ".join(lbl.text() for lbl in dialog.findChildren(QtWidgets.QLabel))
    assert "2 pages in 2 topic clusters" in labels  # caption
    assert "sampled" in labels.lower()  # sampled note
    assert "topic cluster" in labels.lower()  # legend

    # item 1 (link graph) reuse: a dot click opens the page detail dialog too.
    view.node_clicked.emit("https://e.com/a")
    assert win._detail_windows
    assert isinstance(win._detail_windows[-1], SiteCrawlDetailDialog)


def test_show_cluster_map_reports_no_vectors(monkeypatch, qtbot) -> None:
    # Stock crawls never set the opt-in topic_embeddings flag, so every payload's
    # vector is empty; the button must explain why instead of opening an empty map.
    result = SiteCrawlResult.from_payload("https://example.com/page", _payload())
    report = SiteCrawlReport.from_results([result], discovered_count=1)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda parent, title, text, *a, **k: captured.update(title=title, text=text),
    )
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._latest_report = report

    win._show_cluster_map()

    assert captured
    assert "topic" in captured["text"].lower()
    assert "embeddings" in captured["text"].lower()
    assert win._detail_windows == []


class _EndlessVectorlessRepo:
    """Streams far more vectorless results than any sane bound — the zero-vector
    scan must stop at _CLUSTER_MAX_SCANNED, not at the store's natural end."""

    def __init__(self, result: SiteCrawlResult) -> None:
        self._result = result
        self.consumed = 0

    def __enter__(self) -> _EndlessVectorlessRepo:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def stream_results(self):
        for _ in range(50_000):
            self.consumed += 1
            yield self._result


def test_stream_cluster_inputs_bounds_the_zero_vector_scan(monkeypatch, qtbot) -> None:
    # With topic embeddings off (the default) no payload carries a vector; the
    # scan must stop at _CLUSTER_MAX_SCANNED instead of decompressing an entire
    # 100k-row store on the GUI thread before the "no vectors" info box shows.
    result = SiteCrawlResult.from_payload("https://example.com/page", _payload())
    report = SiteCrawlReport.from_results([result], discovered_count=1)
    repo = _EndlessVectorlessRepo(result)
    monkeypatch.setattr(site_crawl_gui, "open_report_repository", lambda _report: repo)
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._latest_report = report

    assert win._stream_cluster_inputs() == []
    assert repo.consumed == site_crawl_gui._CLUSTER_MAX_SCANNED


# --- v3 G13: Semantic redirect mapping dialog wiring ---


def _payload_with_vector(url: str, vector: list[float]) -> CrawlPayload:
    return replace(_payload(url), topic_embeddings={"vector": vector})


def test_redirect_map_button_gated_like_diff_button(qtbot) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    result = SiteCrawlResult.from_payload("https://example.com/page", _payload())
    win._latest_report = SiteCrawlReport.from_results([result], discovered_count=1)

    win._set_running(False)
    assert win.btn_redirect_map.isEnabled() is False  # no previous report yet

    win._previous_report = win._latest_report
    win._set_running(False)
    assert win.btn_redirect_map.isEnabled() is True

    win._set_running(True)
    assert win.btn_redirect_map.isEnabled() is False  # disabled while running


def test_show_redirect_map_assembles_caption_and_suggestion_row(qtbot) -> None:
    old_vector = [1.0, 0.0, 0.0]
    new_vector = [0.99, 0.14, 0.0]  # cosine ~0.99 with old_vector
    old_result = SiteCrawlResult.from_payload(
        "https://example.com/old-page", _payload_with_vector("https://example.com/old-page", old_vector)
    )
    new_result = SiteCrawlResult.from_payload(
        "https://example.com/new-page", _payload_with_vector("https://example.com/new-page", new_vector)
    )
    previous_report = SiteCrawlReport.from_results([old_result], discovered_count=1)
    current_report = SiteCrawlReport.from_results([new_result], discovered_count=1)

    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._previous_report = previous_report
    win._latest_report = current_report

    win._show_redirect_map()

    assert win._detail_windows
    dialog = win._detail_windows[-1]
    buttons = {b.text(): b for b in dialog.findChildren(QtWidgets.QPushButton)}
    assert "Save CSV…" in buttons
    assert "Close" in buttons
    captions = " ".join(lbl.text() for lbl in dialog.findChildren(QtWidgets.QLabel))
    assert "1 suggestions" in captions
    assert "0 unmatched" in captions
    body = dialog.findChild(QtWidgets.QPlainTextEdit).toPlainText()
    assert "https://example.com/old-page" in body
    assert "https://example.com/new-page" in body
    assert "semantic" in body


def test_show_redirect_map_reports_reason_when_unmeasured(monkeypatch, qtbot) -> None:
    # Both sides empty (e.g. nothing migrated away) -> unmeasured, must explain
    # why instead of opening an empty dialog.
    result = SiteCrawlResult.from_payload("https://example.com/page", _payload())
    report = SiteCrawlReport.from_results([result], discovered_count=1)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda parent, title, text, *a, **k: captured.update(title=title, text=text),
    )
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win._previous_report = report  # same URL, same status -> "still alive", no old candidates
    win._latest_report = report

    win._show_redirect_map()

    assert captured
    assert captured["title"] == "Redirect map unavailable"
    assert win._detail_windows == []


def test_save_redirect_map_csv_writes_old_url_new_url_rows(monkeypatch, qtbot, tmp_path: Path) -> None:
    from silentfrog.redirect_mapping import RedirectMap, RedirectSuggestion

    target = tmp_path / "redirects.csv"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "CSV files (*.csv)"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    redirect_map = RedirectMap(
        suggestions=(RedirectSuggestion("https://e.com/old", "https://e.com/new", 0.91, "semantic"),),
        unmatched=(),
        measured=True,
    )

    win._save_redirect_map_csv(redirect_map)

    written = target.read_text(encoding="utf-8")
    assert "old_url,new_url" in written
    assert "https://e.com/old,https://e.com/new" in written


class _EndlessRedirectRepo:
    """Streams far more results than any sane bound — the redirect-mapping
    scan must stop at _REDIRECT_MAP_MAX_SCANNED, not at the store's natural
    end (clone of _EndlessVectorlessRepo for the new stream helper)."""

    def __init__(self, result: SiteCrawlResult) -> None:
        self._result = result
        self.consumed = 0

    def __enter__(self) -> _EndlessRedirectRepo:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def stream_results(self):
        for _ in range(50_000):
            self.consumed += 1
            yield self._result


def test_stream_redirect_page_refs_bounds_the_scan(monkeypatch, qtbot) -> None:
    result = SiteCrawlResult.from_payload("https://example.com/page", _payload())
    report = SiteCrawlReport.from_results([result], discovered_count=1)
    repo = _EndlessRedirectRepo(result)
    monkeypatch.setattr(site_crawl_gui, "open_report_repository", lambda _report: repo)
    win = SiteCrawlWindow()
    qtbot.addWidget(win)

    refs = win._stream_redirect_page_refs(report)

    assert len(refs) == site_crawl_gui._REDIRECT_MAP_MAX_SCANNED
    assert repo.consumed == site_crawl_gui._REDIRECT_MAP_MAX_SCANNED
