from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import threading
from time import monotonic
from typing import Any
from urllib.parse import urlparse

from qtpy import QtCore, QtGui, QtWidgets

from .audit_issues import AuditIssue, issues_for_payload, issues_for_site_report
from .audit_recap import AuditRecapWidget
from .crawl_options import CrawlOptions
from .crawl_history import CrawlHistoryStore, format_history_status, save_report_and_diff
from .crawl_types import CrawlPayload
from .exporters import export_site_crawl_report
from .settings_dialog import CrawlSettingsDialog
from .site_crawl_history_gui import CrawlHistoryDialog
from .site_crawl_types import (
    DEFAULT_SITE_CRAWL_LIMIT,
    SITE_CRAWL_TABLE_HEADERS,
    SITE_CRAWL_TABLE_TOOLTIPS,
    SiteCrawlConfig,
    SiteCrawlReport,
    SiteCrawlResult,
)
from .tabs import (
    AiTab,
    AiVisibilityTab,
    CanonicalTab,
    ContentQualityTab,
    HeadersTab,
    HreflangTab,
    ImagesTab,
    IndexabilityTab,
    KeywordsTab,
    LinksTab,
    MetaTab,
    PerformanceTab,
    RedirectTab,
    RobotsTab,
    SchemaTab,
    SerpTab,
    SocialTab,
)
from .theme import current_theme, status_brushes
from .workers import run_image_analysis, run_site_crawl

_SETUP_PAGE = 0
_RESULTS_PAGE = 1


class SiteCrawlTableModel(QtCore.QAbstractTableModel):
    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[SiteCrawlResult] = []
        dark = current_theme() == "dark"
        brushes = status_brushes(dark)
        self._bad = brushes.bad
        self._warn = brushes.warn
        color = "#f8f9fa" if dark else "#202124"
        self._highlight_foreground = QtGui.QBrush(QtGui.QColor(color))

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(SITE_CRAWL_TABLE_HEADERS)

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        result = self._rows[index.row()]
        value = result.table_row()[index.column()]
        if role in (QtCore.Qt.ItemDataRole.DisplayRole, QtCore.Qt.ItemDataRole.EditRole):
            return value
        if role == QtCore.Qt.ItemDataRole.UserRole:
            return result
        if role == QtCore.Qt.ItemDataRole.BackgroundRole:
            return self._background(result)
        if role == QtCore.Qt.ItemDataRole.ForegroundRole:
            return self._foreground(result)
        return None

    def headerData(self, section: int, orientation: QtCore.Qt.Orientation, role: int = QtCore.Qt.ItemDataRole.DisplayRole):
        if orientation != QtCore.Qt.Orientation.Horizontal:
            return None
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return SITE_CRAWL_TABLE_HEADERS[section]
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            return SITE_CRAWL_TABLE_TOOLTIPS[section]
        return None

    def clear(self) -> None:
        self.beginResetModel()
        self._rows = []
        self.endResetModel()

    def add_result(self, result: SiteCrawlResult) -> None:
        row = len(self._rows)
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        self._rows.append(result)
        self.endInsertRows()

    def set_results(self, results: list[SiteCrawlResult]) -> None:
        self.beginResetModel()
        self._rows = list(results)
        self.endResetModel()

    def result_at(self, row: int) -> SiteCrawlResult | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def update_payload(self, row: int, payload: CrawlPayload) -> None:
        if not 0 <= row < len(self._rows):
            return
        self._rows[row] = replace(self._rows[row], payload=payload)
        left = self.index(row, 0)
        right = self.index(row, self.columnCount() - 1)
        self.dataChanged.emit(left, right, [QtCore.Qt.ItemDataRole.UserRole])

    def results(self) -> list[SiteCrawlResult]:
        return list(self._rows)

    def _background(self, result: SiteCrawlResult):
        if _is_error_status(result.status):
            return self._bad
        if _is_warning_result(result):
            return self._warn
        return None

    def _foreground(self, result: SiteCrawlResult):
        if self._background(result) is not None:
            return self._highlight_foreground
        return None


class SiteCrawlFilterProxy(QtCore.QSortFilterProxyModel):
    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._search = ""
        self._status = "All"
        self._indexability = "All"
        self._filter_revision = 0

    def set_search(self, text: str) -> None:
        self._set_filter_value("_search", text.strip().lower())

    def set_status(self, value: str) -> None:
        self._set_filter_value("_status", value)

    def set_indexability(self, value: str) -> None:
        self._set_filter_value("_indexability", value)

    def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:
        source = self.sourceModel()
        index = source.index(source_row, 0, source_parent)
        result = index.data(QtCore.Qt.ItemDataRole.UserRole)
        if not isinstance(result, SiteCrawlResult):
            return False
        return self._matches_search(result) and self._matches_status(result) and self._matches_indexability(result)

    def _matches_search(self, result: SiteCrawlResult) -> bool:
        if not self._search:
            return True
        haystack = f"{result.url} {result.title}".lower()
        return self._search in haystack

    def _matches_status(self, result: SiteCrawlResult) -> bool:
        return self._status == "All" or result.status == self._status

    def _matches_indexability(self, result: SiteCrawlResult) -> bool:
        return self._indexability == "All" or result.indexability == self._indexability

    def _set_filter_value(self, attribute: str, value: str) -> None:
        if getattr(self, attribute) == value:
            return
        setattr(self, attribute, value)
        self._refresh_filter()

    def _refresh_filter(self) -> None:
        self._filter_revision += 1
        self.setFilterFixedString(str(self._filter_revision))


class SiteCrawlWindow(QtWidgets.QWidget):
    progressSig = QtCore.Signal(dict)
    reportSig = QtCore.Signal(object)
    errorSig = QtCore.Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Silentfrog - Site Crawl")
        self._crawl_options = CrawlOptions.from_ui(gentle_mode=True, max_parallel=2)
        self._active_cancel: threading.Event | None = None
        self._latest_report: SiteCrawlReport | None = None
        self._discovered_total = 0
        self._completed_count = 0
        self._crawl_started_at: float | None = None
        self._eta_timer = QtCore.QTimer(self)
        self._eta_timer.setInterval(1000)
        self._detail_windows: list[QtWidgets.QDialog] = []
        self._history_store = CrawlHistoryStore()
        self._build_ui()
        self._apply_tooltips()
        self._connect_signals()
        self._apply_initial_state()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        self.stack = QtWidgets.QStackedWidget()
        self.setup_page = self._build_setup_page()
        self.results_page = self._build_results_page()
        self.stack.addWidget(self.setup_page)
        self.stack.addWidget(self.results_page)
        layout.addWidget(self.stack)
        self.resize(1100, 700)

    def _build_setup_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addLayout(self._build_source_form())
        layout.addLayout(self._build_setup_actions())
        layout.addStretch()
        return page

    def _build_results_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addLayout(self._build_status_row())
        self.recap_widget = AuditRecapWidget("Site Crawl recap")
        self.recap_widget.issueActivated.connect(self._focus_recap_issue)
        layout.addWidget(self.recap_widget)
        layout.addWidget(self._build_history_label())
        layout.addLayout(self._build_filter_row())
        layout.addWidget(self._build_table(), 1)
        layout.addLayout(self._build_result_actions())
        layout.addWidget(self._build_progress())
        return page

    def _build_status_row(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.lbl_discovery = QtWidgets.QLabel("Ready")
        self.lbl_eta = QtWidgets.QLabel("ETA: -")
        self.lbl_eta.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        row.addWidget(self.lbl_discovery, 1)
        row.addWidget(self.lbl_eta)
        return row

    def _build_history_label(self) -> QtWidgets.QLabel:
        self.lbl_history = QtWidgets.QLabel("History: no completed crawl yet.")
        self.lbl_history.setWordWrap(True)
        self.lbl_history.setToolTip("Local crawl history diff against the previous run for the same host.")
        return self.lbl_history

    def _build_source_form(self) -> QtWidgets.QFormLayout:
        form = QtWidgets.QFormLayout()
        self.base_url = QtWidgets.QLineEdit()
        self.base_url.setPlaceholderText("https://www.example.com")
        self.sitemap_url = QtWidgets.QLineEdit()
        self.sitemap_url.setPlaceholderText("Optional: auto-detected from robots.txt and common sitemap paths")
        self.include_text = QtWidgets.QPlainTextEdit()
        self.exclude_text = QtWidgets.QPlainTextEdit()
        self.url_list = QtWidgets.QPlainTextEdit()
        for field in (self.include_text, self.exclude_text):
            field.setMaximumHeight(58)
        self.url_list.setMaximumHeight(90)
        self.limit_spin = QtWidgets.QSpinBox()
        self.limit_spin.setRange(1, 10000)
        self.limit_spin.setValue(DEFAULT_SITE_CRAWL_LIMIT)
        form.addRow("Base URL", self.base_url)
        form.addRow("Sitemap URL", self.sitemap_url)
        form.addRow("Include prefixes", self.include_text)
        form.addRow("Exclude patterns", self.exclude_text)
        form.addRow("URL list", self.url_list)
        form.addRow("URL limit", self.limit_spin)
        return form

    def _build_filter_row(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Filter URL or title")
        self.status_filter = QtWidgets.QComboBox()
        self.status_filter.addItems(["All", "200", "301", "302", "403", "404", "429", "error", "skipped"])
        self.indexability_filter = QtWidgets.QComboBox()
        self.indexability_filter.addItems([
            "All",
            "Indexable",
            "Indexable with warnings",
            "Not indexable",
            "Noindex",
            "Blocked by robots.txt",
            "Redirected",
            "Canonicalized elsewhere",
            "Failed",
            "Skipped",
        ])
        row.addWidget(self.search_edit, 1)
        row.addWidget(self.status_filter)
        row.addWidget(self.indexability_filter)
        return row

    def _build_table(self) -> QtWidgets.QTableView:
        self.model = SiteCrawlTableModel(self)
        self.proxy = SiteCrawlFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self._configure_table_header()
        self.table.doubleClicked.connect(self._open_result_detail)
        return self.table

    def _configure_table_header(self) -> None:
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        for column, width in _site_crawl_table_widths().items():
            self.table.setColumnWidth(column, width)

    def _build_setup_actions(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Start crawl")
        self.btn_settings = QtWidgets.QPushButton("Crawl settings...")
        self.btn_history_setup = QtWidgets.QPushButton("View past scans")
        self.lbl_speed = QtWidgets.QLabel()
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_settings)
        row.addWidget(self.btn_history_setup)
        row.addWidget(self.lbl_speed)
        row.addStretch()
        return row

    def _build_result_actions(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_export = QtWidgets.QPushButton("Export Excel")
        self.btn_history = QtWidgets.QPushButton("View past scans")
        self.btn_new_crawl = QtWidgets.QPushButton("New crawl")
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_export)
        row.addWidget(self.btn_history)
        row.addWidget(self.btn_new_crawl)
        row.addStretch()
        return row

    def _build_progress(self) -> QtWidgets.QProgressBar:
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Ready")
        self.progress.setMinimumHeight(32)
        self.progress.setStyleSheet(_progress_stylesheet())
        return self.progress

    def _connect_signals(self) -> None:
        self.btn_start.clicked.connect(self._start_crawl)
        self.btn_stop.clicked.connect(self._stop_crawl)
        self.btn_export.clicked.connect(self._export_excel)
        self.btn_new_crawl.clicked.connect(self._show_setup)
        self.btn_history.clicked.connect(self._open_history_browser)
        self.btn_history_setup.clicked.connect(self._open_history_browser)
        self.btn_settings.clicked.connect(self._open_crawl_settings)
        self.search_edit.textChanged.connect(self.proxy.set_search)
        self.status_filter.currentTextChanged.connect(self.proxy.set_status)
        self.indexability_filter.currentTextChanged.connect(self.proxy.set_indexability)
        self.progressSig.connect(self._handle_progress)
        self.reportSig.connect(self._handle_report)
        self.errorSig.connect(self._show_error)
        self._eta_timer.timeout.connect(self._update_eta_label)

    def _apply_initial_state(self) -> None:
        self.stack.setCurrentIndex(_SETUP_PAGE)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setVisible(False)
        self.btn_export.setEnabled(False)
        self.btn_new_crawl.setEnabled(False)
        self.recap_widget.reset("Start a crawl to build the site action recap.")
        self.lbl_history.setText("History: no completed crawl yet.")
        self._reset_eta_tracking()
        self._update_speed_label()

    def _apply_tooltips(self) -> None:
        self.base_url.setToolTip("Site root or branch URL used as the crawl scope.")
        self.sitemap_url.setToolTip("Optional. Leave empty to detect sitemaps from robots.txt and common sitemap paths.")
        self.include_text.setToolTip("Optional path prefixes to include, one per line. Example: /design/")
        self.exclude_text.setToolTip("Optional URL fragments or path prefixes to exclude, one per line.")
        self.url_list.setToolTip("Optional explicit URLs to crawl, one per line. This bypasses sitemap discovery.")
        self.limit_spin.setToolTip("Maximum number of URLs Silentfrog will crawl in this run.")
        self.btn_start.setToolTip("Start crawling with the current setup and switch to the results screen.")
        self.btn_settings.setToolTip("Open crawl speed, headers, cookies, and robots settings.")
        self.btn_history_setup.setToolTip("Open saved local Site Crawl runs and compare past scans.")
        self.btn_stop.setToolTip("Request cancellation. Active requests finish before the crawl fully stops.")
        self.btn_export.setToolTip("Export the current Site Crawl results to an Excel workbook.")
        self.btn_history.setToolTip("Open saved local Site Crawl runs and compare past scans.")
        self.btn_new_crawl.setToolTip("Return to setup for another Site Crawl run.")

    def _start_crawl(self) -> None:
        config = self._config_from_ui()
        if not self._valid_config(config):
            return
        self.model.clear()
        self._latest_report = None
        self.recap_widget.reset("Crawl in progress. The recap updates when results are complete.")
        self.lbl_history.setText("History: waiting for completed crawl...")
        self._reset_eta_tracking()
        self._show_results()
        self.lbl_discovery.setText("Discovering URLs from sitemap sources...")
        self.lbl_eta.setText("ETA: waiting for URL discovery")
        self.progress.setValue(0)
        self.progress.setFormat("Discovering URLs...")
        self._set_running(True)
        _, self._active_cancel = run_site_crawl(
            config,
            timeout=15,
            on_progress=lambda event: self.progressSig.emit(event),
            on_success=lambda report: self.reportSig.emit(report),
            on_error=lambda error: self.errorSig.emit(error),
        )

    def _config_from_ui(self) -> SiteCrawlConfig:
        return SiteCrawlConfig.from_text(
            base_url=self.base_url.text(),
            sitemap_url=self.sitemap_url.text(),
            include_text=self.include_text.toPlainText(),
            exclude_text=self.exclude_text.toPlainText(),
            url_list_text=self.url_list.toPlainText(),
            limit=self.limit_spin.value(),
            crawl_options=self._crawl_options,
        )

    def _valid_config(self, config: SiteCrawlConfig) -> bool:
        parsed = urlparse(config.base_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return True
        QtWidgets.QMessageBox.warning(self, "Missing URL", "Enter a valid base URL.")
        return False

    def _stop_crawl(self) -> None:
        if self._active_cancel:
            self._active_cancel.set()
        self.lbl_discovery.setText("Stopping after active requests finish...")
        self.lbl_eta.setText("ETA: stopping...")
        self.progress.setFormat("Stopping after active requests finish...")
        self.btn_stop.setEnabled(False)

    def _handle_progress(self, event: dict[str, Any]) -> None:
        if event.get("event") == "discovered":
            total = int(event.get("total", 0))
            self._discovered_total = total
            self._crawl_started_at = monotonic()
            self.lbl_discovery.setText(f"Found {total} URLs to crawl.")
            self.progress.setFormat(f"Found {total} URLs")
            self.progress.setValue(0)
            self._update_eta_label()
            return
        if event.get("event") == "row":
            self._append_progress_row(event)

    def _append_progress_row(self, event: dict[str, Any]) -> None:
        result = event.get("result")
        if isinstance(result, SiteCrawlResult):
            self.model.add_result(result)
        total = max(1, self._discovered_total or self.limit_spin.value())
        completed = min(total, int(event.get("completed", self.model.rowCount())))
        self._completed_count = completed
        if self._crawl_started_at is None:
            self._crawl_started_at = monotonic()
        self.progress.setValue(int((completed / total) * 100))
        self.progress.setFormat(f"Crawled {completed} of {total} URLs")
        self._update_eta_label()

    def _handle_report(self, report: SiteCrawlReport) -> None:
        self._latest_report = report
        self._discovered_total = report.discovered_count
        self._completed_count = report.crawled_count + report.skipped_count
        self.model.set_results(list(report.results))
        self._set_running(False)
        self.btn_export.setEnabled(bool(report.results))
        self._update_recap_from_report(report)
        self._update_history_from_report(report)
        summary = self._report_summary(report)
        self.lbl_discovery.setText(summary if not report.warning else f"{summary}. {report.warning}")
        self.lbl_eta.setText("ETA: complete")
        self.progress.setFormat("Done")
        self.progress.setValue(100)

    def _report_summary(self, report: SiteCrawlReport) -> str:
        return (
            f"Found {report.discovered_count} URLs. "
            f"Done: {report.crawled_count} crawled, "
            f"{report.failed_count} failed, {report.skipped_count} skipped"
        )

    def _set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_settings.setEnabled(not running)
        self.btn_stop.setVisible(running)
        self.btn_stop.setEnabled(running)
        self.btn_export.setEnabled(False if running else bool(self._latest_report and self._latest_report.results))
        self.btn_new_crawl.setEnabled(not running)
        if running:
            self._eta_timer.start()
        else:
            self._eta_timer.stop()

    def _show_error(self, message: str) -> None:
        self._set_running(False)
        self.lbl_discovery.setText("Site crawl failed.")
        self.lbl_eta.setText("ETA: failed")
        QtWidgets.QMessageBox.warning(self, "Site crawl failed", message)

    def _show_results(self) -> None:
        self.stack.setCurrentIndex(_RESULTS_PAGE)

    def _show_setup(self) -> None:
        self.stack.setCurrentIndex(_SETUP_PAGE)

    def _update_recap_from_report(self, report: SiteCrawlReport) -> None:
        self.recap_widget.update_issues(
            issues_for_site_report(report),
            item_count=max(1, report.discovered_count),
            item_label="crawl",
        )

    def _update_history_from_report(self, report: SiteCrawlReport) -> None:
        try:
            run, diff = save_report_and_diff(self._history_store, report)
        except Exception as exc:  # noqa: BLE001
            self.lbl_history.setText(f"History: unavailable ({exc})")
            return
        self.lbl_history.setText(format_history_status(run, diff))

    def _focus_recap_issue(self, issue: AuditIssue) -> None:
        if not issue.url:
            return
        self.search_edit.setText(issue.url)
        self._select_result_url(issue.url)

    def _select_result_url(self, url: str) -> None:
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            if index.data() == url:
                self.table.selectRow(row)
                self.table.scrollTo(index)
                return

    def _open_crawl_settings(self) -> None:
        dialog = CrawlSettingsDialog(self._crawl_options, self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self._crawl_options = dialog.options()
            self._update_speed_label()

    def _open_history_browser(self) -> None:
        dialog = CrawlHistoryDialog(self._history_store, self)
        dialog.exec()

    def _update_speed_label(self) -> None:
        mode = "Gentle" if self._crawl_options.gentle_mode else "Standard"
        self.lbl_speed.setText(f"{mode} crawl, max {self._crawl_options.max_concurrent_per_host}/host")

    def _reset_eta_tracking(self) -> None:
        self._discovered_total = 0
        self._completed_count = 0
        self._crawl_started_at = None
        if hasattr(self, "lbl_eta"):
            self.lbl_eta.setText("ETA: -")

    def _update_eta_label(self) -> None:
        if self._completed_count <= 0:
            self.lbl_eta.setText(_eta_waiting_text(self._discovered_total))
            return
        total = max(self._discovered_total, self._completed_count)
        remaining = max(0, total - self._completed_count)
        if remaining <= 0:
            self.lbl_eta.setText("ETA: finishing...")
            return
        elapsed = max(0.1, monotonic() - (self._crawl_started_at or monotonic()))
        seconds = int(round((elapsed / self._completed_count) * remaining))
        self.lbl_eta.setText(f"ETA: {_format_duration(seconds)} remaining")

    def _open_result_detail(self, index: QtCore.QModelIndex) -> None:
        source_index = self.proxy.mapToSource(index)
        result = self.model.result_at(source_index.row())
        if result is None or result.payload is None:
            return
        base_url = result.final_url or result.url
        dialog = SiteCrawlDetailDialog(
            result.payload,
            base_url,
            on_payload_updated=lambda payload, row=source_index.row(): self.model.update_payload(row, payload),
            parent=self,
        )
        self._detail_windows.append(dialog)
        dialog.show()

    def _export_excel(self) -> None:
        if not self._latest_report:
            return
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export site crawl",
            str(Path.home() / "silentfrog_site_crawl.xlsx"),
            "Excel files (*.xlsx)",
        )
        if not file_path:
            return
        target = Path(file_path if file_path.lower().endswith(".xlsx") else f"{file_path}.xlsx")
        export_site_crawl_report(self._latest_report, target)
        QtWidgets.QMessageBox.information(self, "Export completed", "Site crawl report exported successfully.")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._active_cancel:
            self._active_cancel.set()
        super().closeEvent(event)


class SiteCrawlDetailDialog(QtWidgets.QDialog):
    imageSig = QtCore.Signal(list)
    errorSig = QtCore.Signal(str)

    def __init__(
        self,
        payload: CrawlPayload,
        base_url: str,
        on_payload_updated: Any | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._payload = payload
        self._base_url = base_url
        self._on_payload_updated = on_payload_updated
        self.setWindowTitle("Site Crawl Page Detail")
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(self._build_actions())
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs)
        self._populate_tabs(payload)
        self.imageSig.connect(self._handle_image_update)
        self.errorSig.connect(self._show_image_error)
        self.resize(1000, 650)

    def _build_actions(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.btn_img_dl = QtWidgets.QPushButton("Analyze images")
        self.btn_img_dl.setToolTip("Fetch image dimensions, file size, content type, and cache headers for this cached page detail.")
        self.btn_img_dl.clicked.connect(self._start_image_analysis)
        row.addWidget(self.btn_img_dl)
        row.addStretch()
        return row

    def _populate_tabs(self, payload: CrawlPayload) -> None:
        data = payload.to_mapping()
        self._add_recap_tab(payload)
        self._add_table_tabs(data)
        self._add_special_tabs(payload, data)

    def _add_recap_tab(self, payload: CrawlPayload) -> None:
        self.recap_tab = AuditRecapWidget("Page recap")
        self.recap_tab.update_issues(
            issues_for_payload(self._base_url, payload),
            item_count=1,
            item_label="page",
        )
        self.tabs.addTab(self.recap_tab, "Recap")

    def _add_table_tabs(self, data: dict[str, Any]) -> None:
        self.images_tab = ImagesTab()
        tab_specs = [
            ("Meta tag", MetaTab(), data.get("meta", [])),
            ("Images", self.images_tab, data.get("images", [])),
            ("Social", SocialTab(), data.get("social", {})),
            ("Link", LinksTab(), data.get("links", [])),
            ("Hreflang", HreflangTab(), data.get("hreflang", [])),
            ("Content quality", ContentQualityTab(), data.get("content_quality", {})),
            ("Keywords", KeywordsTab(), data.get("keywords", [])),
            ("AI crawl", AiTab(), data.get("ai_crawl", [])),
            ("AI Visibility", AiVisibilityTab(), data.get("ai_visibility", {})),
            ("Performance", PerformanceTab(), data.get("performance", {})),
            ("Structured data", SchemaTab(), data.get("schema", {})),
        ]
        for label, tab, value in tab_specs:
            tab.update(value)
            self.tabs.addTab(tab, label)
        headers_tab = HeadersTab()
        headers_tab.update(data.get("headers", []), _title_from_meta(data.get("meta", [])))
        self.tabs.insertTab(1, headers_tab, "Header H1-H6")

    def _add_special_tabs(self, payload: CrawlPayload, data: dict[str, Any]) -> None:
        redirect_tab = RedirectTab()
        redirect_tab.update(data.get("redirect", {}))
        canonical_tab = CanonicalTab()
        canonical_tab.update(data.get("canonical", {}))
        indexability_tab = IndexabilityTab()
        indexability_tab.update(payload.redirect.to_dict(), payload.canonical.to_dict(), payload.meta_robots, payload.robots)
        robots_tab = RobotsTab()
        robots_tab.update(payload.meta_robots, payload.robots)
        serp_tab = SerpTab()
        serp_tab.update(data.get("serp", {}), data.get("serp_audit", {}))
        for label, tab in [
            ("Redirect", redirect_tab),
            ("Canonical", canonical_tab),
            ("Indexability", indexability_tab),
            ("Robots", robots_tab),
            ("SERP", serp_tab),
        ]:
            self.tabs.addTab(tab, label)

    def _start_image_analysis(self) -> None:
        rows = self.images_tab.rows()
        if not rows:
            QtWidgets.QMessageBox.information(self, "Nothing to do", "Image table is empty.")
            return
        self.btn_img_dl.setEnabled(False)
        self.btn_img_dl.setText("Analyzing images...")
        run_image_analysis(
            self._base_url,
            rows,
            timeout=15,
            on_success=lambda result: self.imageSig.emit(result),
            on_error=lambda error: self.errorSig.emit(error),
        )

    def _handle_image_update(self, rows: list[list[str]]) -> None:
        self.images_tab.update(rows)
        self._payload = replace(self._payload, images=self.images_tab.rows())
        if self._on_payload_updated:
            self._on_payload_updated(self._payload)
        self.btn_img_dl.setText("Analyze images")
        self.btn_img_dl.setEnabled(True)

    def _show_image_error(self, message: str) -> None:
        self.btn_img_dl.setText("Analyze images")
        self.btn_img_dl.setEnabled(True)
        QtWidgets.QMessageBox.warning(self, "Image analysis failed", message)


__all__ = ["SiteCrawlWindow", "SiteCrawlTableModel", "SiteCrawlFilterProxy"]


def _title_from_meta(rows: object) -> str:
    if not isinstance(rows, list):
        return ""
    for row in rows:
        if isinstance(row, list) and len(row) > 1 and str(row[0]).lower() == "title":
            return str(row[1])
    return ""


def _is_error_status(status: str) -> bool:
    if status == "error":
        return True
    return _status_code(status) >= 400


def _is_warning_result(result: SiteCrawlResult) -> bool:
    if result.status == "skipped":
        return False
    if result.indexability in {"", "-", "Indexable"}:
        return False
    return True


def _status_code(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _progress_stylesheet() -> str:
    return """
    QProgressBar {
        min-height: 32px;
        border: 1px solid #1f8f4d;
        border-radius: 8px;
        background-color: #202124;
        color: #f8f9fa;
        text-align: center;
        padding: 2px;
    }
    QProgressBar::chunk {
        background-color: #2ecc71;
        border-radius: 6px;
    }
    """


def _eta_waiting_text(total: int) -> str:
    if total > 0:
        return "ETA: calculating after first page"
    return "ETA: waiting for URL discovery"


def _format_duration(seconds: int) -> str:
    normalized = max(0, int(seconds))
    if normalized < 60:
        return f"{normalized}s"
    minutes, remaining_seconds = divmod(normalized, 60)
    if minutes < 60:
        return f"{minutes}m {remaining_seconds:02d}s"
    hours, remaining_minutes = divmod(minutes, 60)
    return f"{hours}h {remaining_minutes:02d}m"


def _site_crawl_table_widths() -> dict[int, int]:
    return {
        0: 360,
        1: 72,
        2: 150,
        3: 260,
        4: 95,
        5: 95,
        6: 90,
        7: 80,
        8: 90,
        9: 90,
        10: 80,
        11: 85,
        12: 300,
    }
