from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import urlparse

from qtpy import QtCore, QtGui, QtWidgets

from .audit_issues import AuditIssue, issues_for_payload, issues_for_site_report
from .audit_recap import AuditRecapWidget
from .crawl_diff import diff_reports, diff_to_markdown
from .crawl_history import CrawlHistoryStore, format_history_status, save_report_and_diff
from .crawl_mode import CrawlMode
from .crawl_options import AuditProfile, CrawlOptions, auto_suggest_profile
from .crawl_run_repository import (
    CrawlRowQuery,
    CrawlRunRef,
    SqliteCrawlRunRepository,
    open_report_repository,
    stream_report_results,
)
from .crawl_store import CrawlStore, new_crawl_db_path
from .crawl_types import CrawlPayload
from .exporters import export_crawl_for_llm, export_site_crawl_report, write_llm_export
from .settings_dialog import CrawlSettingsDialog
from .site_crawl_history_gui import CrawlHistoryDialog
from .site_crawl_types import (
    DEFAULT_SITE_CRAWL_LIMIT,
    SITE_CRAWL_TABLE_HEADERS,
    SITE_CRAWL_TABLE_TOOLTIPS,
    SiteCrawlConfig,
    SiteCrawlReport,
    SiteCrawlResult,
    SpiderConfig,
)
from .tabs import (
    AiVisibilityTab,
    BotMatrixTab,
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
from .theme import current_theme, left_align_tab_bar, status_brushes, window_icon
from .workers import run_image_analysis, run_site_crawl

logger = logging.getLogger(__name__)

_SETUP_PAGE = 0
_RESULTS_PAGE = 1


# v2.0 PR-10: when a crawl is store-backed the results table is driven straight
# from SQLite, one bounded page at a time, so the GUI never materialises all rows.
_PAGE_SIZE = 100
_MAX_CACHED_PAGES = 8  # ~800 rows resident at most, regardless of crawl size
# Live-streaming in-memory rows are capped to a rolling window so an in-progress
# store-backed crawl also stays flat; the full run is shown SQL-paged on finish.
_LIVE_ROW_WINDOW = 5000
# Display column -> sortable SQL (lightweight) column. Columns absent here derive
# from the payload and keep crawl order (sorting them would load every payload).
_SORT_COLUMN_BY_INDEX = {0: "url", 1: "http_status", 2: "indexability", 3: "title", 12: "issue_summary"}


def _sql_filter_value(value: str) -> str:
    """The status/indexability combos use 'All' as the no-filter sentinel."""
    return "" if value == "All" else value


class _CrawlTableBase(QtCore.QAbstractTableModel):
    """Shared columns + status colouring for the two results models (PR-10): an
    in-memory model for store-less/live crawls and a SQL-paged model for
    store-backed runs. Subclasses provide ``rowCount`` and ``_result_for_row``."""

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        dark = current_theme() == "dark"
        brushes = status_brushes(dark)
        self._bad = brushes.bad
        self._warn = brushes.warn
        color = "#f8f9fa" if dark else "#202124"
        self._highlight_foreground = QtGui.QBrush(QtGui.QColor(color))

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(SITE_CRAWL_TABLE_HEADERS)

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        result = self._result_for_row(index.row())
        if result is None:
            return None
        if role in (QtCore.Qt.ItemDataRole.DisplayRole, QtCore.Qt.ItemDataRole.EditRole):
            return result.table_row()[index.column()]
        if role == QtCore.Qt.ItemDataRole.UserRole:
            return result
        if role == QtCore.Qt.ItemDataRole.BackgroundRole:
            return self._background(result)
        if role == QtCore.Qt.ItemDataRole.ForegroundRole:
            return self._foreground(result)
        return None

    def headerData(
        self, section: int, orientation: QtCore.Qt.Orientation, role: int = QtCore.Qt.ItemDataRole.DisplayRole
    ):
        if orientation != QtCore.Qt.Orientation.Horizontal:
            return None
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return SITE_CRAWL_TABLE_HEADERS[section]
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            return SITE_CRAWL_TABLE_TOOLTIPS[section]
        return None

    def _result_for_row(self, row: int) -> SiteCrawlResult | None:
        raise NotImplementedError

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


class SiteCrawlTableModel(_CrawlTableBase):
    """In-memory model for store-less crawls (tests + bounded small programmatic
    runs) and for the live row stream. ``max_rows`` caps the live stream to a
    rolling window so an in-progress crawl never materialises all rows."""

    def __init__(self, parent: QtCore.QObject | None = None, max_rows: int = 0) -> None:
        super().__init__(parent)
        self._rows: list[SiteCrawlResult] = []
        self._max_rows = max_rows

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def _result_for_row(self, row: int) -> SiteCrawlResult | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def clear(self) -> None:
        self.beginResetModel()
        self._rows = []
        self.endResetModel()

    def add_result(self, result: SiteCrawlResult) -> None:
        if self._max_rows and len(self._rows) >= self._max_rows:
            self.beginRemoveRows(QtCore.QModelIndex(), 0, 0)
            self._rows.pop(0)  # drop the oldest row so the window stays bounded
            self.endRemoveRows()
        row = len(self._rows)
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        self._rows.append(result)
        self.endInsertRows()

    def set_results(self, results: list[SiteCrawlResult]) -> None:
        self.beginResetModel()
        self._rows = list(results)
        self.endResetModel()

    def result_at(self, row: int) -> SiteCrawlResult | None:
        return self._result_for_row(row)

    def update_payload(self, row: int, payload: CrawlPayload) -> None:
        if not 0 <= row < len(self._rows):
            return
        self._rows[row] = replace(self._rows[row], payload=payload)
        left = self.index(row, 0)
        right = self.index(row, self.columnCount() - 1)
        self.dataChanged.emit(left, right, [QtCore.Qt.ItemDataRole.UserRole])

    def results(self) -> list[SiteCrawlResult]:
        return list(self._rows)


class StoredCrawlTableModel(_CrawlTableBase):
    """SQL-paged model for store-backed runs (PR-10, H2). Rows are read from the
    run's SQLite store one bounded page at a time and sorted/filtered in SQL, so
    the GUI holds at most a few pages no matter how large the crawl is. Its own
    read connection is owned by the thread that builds it (the GUI thread)."""

    def __init__(self, run_ref: CrawlRunRef, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._repo = SqliteCrawlRunRepository(run_ref.db_path, run_ref.run_id)
        self._query = CrawlRowQuery()
        self._pages: OrderedDict[int, list[SiteCrawlResult]] = OrderedDict()
        self._row_count = self._repo.filtered_count(self._query)

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else self._row_count

    def _result_for_row(self, row: int) -> SiteCrawlResult | None:
        if not 0 <= row < self._row_count:
            return None
        page_index = row // _PAGE_SIZE
        page = self._pages.get(page_index) or self._load_page(page_index)
        offset = row - page_index * _PAGE_SIZE
        return page[offset] if offset < len(page) else None

    def _load_page(self, page_index: int) -> list[SiteCrawlResult]:
        page = self._repo.page_results(self._query, page_index * _PAGE_SIZE, _PAGE_SIZE)
        self._pages[page_index] = page
        self._pages.move_to_end(page_index)
        while len(self._pages) > _MAX_CACHED_PAGES:
            self._pages.popitem(last=False)  # evict the least-recently-used page
        return page

    def result_at(self, row: int) -> SiteCrawlResult | None:
        return self._result_for_row(row)

    def update_payload(self, row: int, payload: CrawlPayload) -> None:
        result = self._result_for_row(row)
        if result is None:
            return
        page = self._pages.get(row // _PAGE_SIZE)
        if page is None:
            return
        page[row - (row // _PAGE_SIZE) * _PAGE_SIZE] = replace(result, payload=payload)
        left = self.index(row, 0)
        right = self.index(row, self.columnCount() - 1)
        self.dataChanged.emit(left, right, [QtCore.Qt.ItemDataRole.UserRole])

    def set_search(self, text: str) -> None:
        self._apply_query(replace(self._query, search=text.strip()))

    def set_status(self, value: str) -> None:
        self._apply_query(replace(self._query, status=_sql_filter_value(value)))

    def set_indexability(self, value: str) -> None:
        self._apply_query(replace(self._query, indexability=_sql_filter_value(value)))

    def sort(self, column: int, order: QtCore.Qt.SortOrder = QtCore.Qt.SortOrder.AscendingOrder) -> None:
        descending = order == QtCore.Qt.SortOrder.DescendingOrder
        self._apply_query(replace(self._query, sort=_SORT_COLUMN_BY_INDEX.get(column, ""), descending=descending))

    def refresh(self) -> None:
        """Re-read the count and drop the page cache — used after the crawl's
        final flush so newly persisted rows become visible."""
        self._apply_query(self._query)

    def _apply_query(self, query: CrawlRowQuery) -> None:
        self.beginResetModel()
        self._query = query
        self._pages.clear()
        self._row_count = self._repo.filtered_count(query)
        self.endResetModel()

    def close(self) -> None:
        self._repo.close()


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
        self.setWindowIcon(window_icon())
        # H4: site crawls default to STANDARD (gated). Single-page audits stay DEEP.
        self._crawl_options = CrawlOptions.from_ui(gentle_mode=True, max_parallel=2, profile=AuditProfile.STANDARD)
        self._active_cancel: threading.Event | None = None
        self._latest_report: SiteCrawlReport | None = None
        # v2.0 V8: previous crawl kept so "Compare with previous" can diff the
        # current run against it. PR-10: the previous run's on-disk store is
        # retained (only the run before it is discarded) so the diff can stream
        # both runs' rows through their CrawlRunRefs.
        self._previous_report: SiteCrawlReport | None = None
        # v2.0 V3.2: streaming store for the live crawl (payloads on disk,
        # loaded on demand for the detail dialog so RAM stays flat at ~1M).
        self._crawl_store_path: str = ""
        self._previous_store_path: str = ""
        self._crawl_run_id: str = ""
        # v2.0 PR-10: when the displayed run is store-backed, the table is driven
        # by this SQL-paged model instead of the in-memory model + proxy.
        self._stored_model: StoredCrawlTableModel | None = None
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
        self.lbl_eta.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
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
        # macOS Qt 6.11 defaults a QFormLayout's FieldGrowthPolicy to
        # `FieldsStayAtSizeHint`, which renders our QLineEdit / QPlainTextEdit
        # rows at their preferred (small) width centred in the window. Force
        # the fields to fill the available row width across all platforms.
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.DontWrapRows)
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
        # v2.0 V3: store-backed, so the cap is far higher than the old 10k.
        self.limit_spin.setRange(1, 1_000_000)
        self.limit_spin.setValue(DEFAULT_SITE_CRAWL_LIMIT)
        self._build_spider_controls()
        form.addRow("Base URL", self.base_url)
        form.addRow("Sitemap URL", self.sitemap_url)
        form.addRow("Include prefixes", self.include_text)
        form.addRow("Exclude patterns", self.exclude_text)
        form.addRow("URL list", self.url_list)
        form.addRow("Crawl mode", self.crawl_mode_combo)
        form.addRow("Max depth", self.depth_spin)
        form.addRow("Max URLs", self.limit_spin)
        form.addRow("Politeness (ms/host)", self.politeness_spin)
        form.addRow("", self.respect_robots_check)
        form.addRow("", self.follow_subdomains_check)
        return form

    def _build_spider_controls(self) -> None:
        # v2.0 V3 — drive the hybrid spider from the GUI.
        self.crawl_mode_combo = QtWidgets.QComboBox()
        # Store the mode's string value (or None for Auto) — Qt coerces a
        # str-subclass enum on retrieval, so we round-trip via CrawlMode.
        modes: list[tuple[str, str | None]] = [
            ("Auto (recommended)", None),
            ("Hybrid: sitemap + spider", CrawlMode.HYBRID.value),
            ("Spider: follow links", CrawlMode.SPIDER.value),
            ("Sitemap only", CrawlMode.SITEMAP.value),
            ("URL list only", CrawlMode.LIST.value),
        ]
        for label, mode in modes:
            self.crawl_mode_combo.addItem(label, mode)
        self.crawl_mode_combo.setToolTip(
            "Auto picks Hybrid when you give only a base URL (crawl the whole site by "
            "following links), LIST for an explicit URL list, SITEMAP for a sitemap."
        )
        self.depth_spin = QtWidgets.QSpinBox()
        self.depth_spin.setRange(0, 50)
        self.depth_spin.setValue(10)
        self.politeness_spin = QtWidgets.QSpinBox()
        self.politeness_spin.setRange(0, 5000)
        self.politeness_spin.setSingleStep(50)
        self.politeness_spin.setValue(200)
        self.respect_robots_check = QtWidgets.QCheckBox("Respect robots.txt disallow rules")
        self.respect_robots_check.setChecked(True)
        self.follow_subdomains_check = QtWidgets.QCheckBox("Follow subdomains")
        self.follow_subdomains_check.setChecked(False)

    def _build_filter_row(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Filter URL or title")
        self.status_filter = QtWidgets.QComboBox()
        self.status_filter.addItems(["All", "200", "301", "302", "403", "404", "429", "error", "skipped"])
        self.indexability_filter = QtWidgets.QComboBox()
        self.indexability_filter.addItems(
            [
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
            ]
        )
        row.addWidget(self.search_edit, 1)
        row.addWidget(self.status_filter)
        row.addWidget(self.indexability_filter)
        return row

    def _build_table(self) -> QtWidgets.QTableView:
        self.model = SiteCrawlTableModel(self, max_rows=_LIVE_ROW_WINDOW)
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
        self.btn_export_ai = QtWidgets.QPushButton("Export for AI analysis")
        self.btn_export_ai.setToolTip(
            "Write a Markdown + JSON bundle you can paste into a Claude chat for a "
            "prioritised fix list. Compact by default (worst pages + recurring issues)."
        )
        self.btn_diff = QtWidgets.QPushButton("Compare with previous")
        self.btn_diff.setToolTip(
            "Diff this crawl against the previous one in this session: new / removed URLs, "
            "status changes, and GEO Score regressions / improvements."
        )
        self.btn_graph = QtWidgets.QPushButton("Link graph")
        self.btn_graph.setToolTip(
            "Visualise the crawl tree: nodes coloured by GEO Score, edges from the page that "
            "first linked to each URL. Orphan pages (reached via sitemap, not internal links) "
            "are listed."
        )
        self.btn_history = QtWidgets.QPushButton("View past scans")
        self.btn_new_crawl = QtWidgets.QPushButton("New crawl")
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_export)
        row.addWidget(self.btn_export_ai)
        row.addWidget(self.btn_diff)
        row.addWidget(self.btn_graph)
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
        self.btn_export_ai.clicked.connect(self._export_ai)
        self.btn_diff.clicked.connect(self._show_diff)
        self.btn_graph.clicked.connect(self._show_graph)
        self.btn_new_crawl.clicked.connect(self._show_setup)
        self.btn_history.clicked.connect(self._open_history_browser)
        self.btn_history_setup.clicked.connect(self._open_history_browser)
        self.btn_settings.clicked.connect(self._open_crawl_settings)
        self.limit_spin.valueChanged.connect(self._update_speed_label)  # reflect H4 auto-suggest live
        self.search_edit.textChanged.connect(self._on_search_changed)
        self.status_filter.currentTextChanged.connect(self._on_status_changed)
        self.indexability_filter.currentTextChanged.connect(self._on_indexability_changed)
        self.progressSig.connect(self._handle_progress)
        self.reportSig.connect(self._handle_report)
        self.errorSig.connect(self._show_error)
        self._eta_timer.timeout.connect(self._update_eta_label)

    def _apply_initial_state(self) -> None:
        self.stack.setCurrentIndex(_SETUP_PAGE)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setVisible(False)
        self.btn_export.setEnabled(False)
        self.btn_export_ai.setEnabled(False)
        self.btn_diff.setEnabled(False)
        self.btn_graph.setEnabled(False)
        self.btn_new_crawl.setEnabled(False)
        self.recap_widget.reset("Start a crawl to build the site action recap.")
        self.lbl_history.setText("History: no completed crawl yet.")
        self._reset_eta_tracking()
        self._update_speed_label()

    def _apply_tooltips(self) -> None:
        self.base_url.setToolTip("Site root or branch URL used as the crawl scope.")
        self.sitemap_url.setToolTip(
            "Optional. Leave empty to detect sitemaps from robots.txt and common sitemap paths."
        )
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

    def _active_filter_target(self):
        """Filtering/search drives the SQL model when store-backed, else the
        in-memory proxy. Both expose ``set_search``/``set_status``/
        ``set_indexability``."""
        return self._stored_model if self._stored_model is not None else self.proxy

    def _on_search_changed(self, text: str) -> None:
        self._active_filter_target().set_search(text)

    def _on_status_changed(self, value: str) -> None:
        self._active_filter_target().set_status(value)

    def _on_indexability_changed(self, value: str) -> None:
        self._active_filter_target().set_indexability(value)

    def _bind_stored_model(self, run_ref: CrawlRunRef) -> None:
        """Swap the table to a SQL-paged model bound to ``run_ref`` and free the
        live in-memory rows (PR-10). Current filter selections carry over."""
        self._teardown_stored_model()
        self.model.clear()
        self._stored_model = StoredCrawlTableModel(run_ref, self)
        self.table.setModel(self._stored_model)
        self._stored_model.set_status(self.status_filter.currentText())
        self._stored_model.set_indexability(self.indexability_filter.currentText())
        self._stored_model.set_search(self.search_edit.text())

    def _teardown_stored_model(self) -> None:
        if self._stored_model is None:
            return
        self.table.setModel(self.proxy)  # back to the in-memory live model
        self._stored_model.close()
        self._stored_model = None

    def _roll_store_generation(self) -> None:
        """Retain the immediately-previous run's store for the diff; discard the
        run before it (at most two crawl stores live on disk at once)."""
        self._discard_store(self._previous_store_path)
        self._previous_store_path = self._crawl_store_path
        self._crawl_store_path = str(new_crawl_db_path())

    def _discard_store(self, path: str) -> None:
        """Best-effort unlink of a crawl store and its WAL/SHM siblings."""
        if not path:
            return
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(path + suffix).unlink(missing_ok=True)
            except OSError:
                pass

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
        self._teardown_stored_model()
        self._roll_store_generation()
        self._crawl_run_id = ""
        _, self._active_cancel = run_site_crawl(
            config,
            timeout=15,
            on_progress=lambda event: self.progressSig.emit(event),
            on_success=lambda report: self.reportSig.emit(report),
            on_error=lambda error: self.errorSig.emit(error),
            store_path=self._crawl_store_path,
        )

    def _config_from_ui(self) -> SiteCrawlConfig:
        return SiteCrawlConfig.from_text(
            base_url=self.base_url.text(),
            sitemap_url=self.sitemap_url.text(),
            include_text=self.include_text.toPlainText(),
            exclude_text=self.exclude_text.toPlainText(),
            url_list_text=self.url_list.toPlainText(),
            limit=self.limit_spin.value(),
            crawl_options=self._effective_options(),
            spider=self._spider_from_ui(),
        )

    def _effective_options(self) -> CrawlOptions:
        """Apply the H4 auto-suggestion: a large crawl left on the STANDARD
        default downgrades to LIGHTWEIGHT; an explicit choice is honoured."""
        profile = auto_suggest_profile(self.limit_spin.value(), self._crawl_options.profile)
        if profile is self._crawl_options.profile:
            return self._crawl_options
        return replace(self._crawl_options, profile=profile)

    def _spider_from_ui(self) -> SpiderConfig:
        raw = self.crawl_mode_combo.currentData()
        mode = self._auto_mode_from_ui() if raw is None else CrawlMode.from_value(raw)
        return SpiderConfig(
            mode=mode,
            max_depth=self.depth_spin.value(),
            max_urls=self.limit_spin.value(),
            respect_robots=self.respect_robots_check.isChecked(),
            politeness_delay_ms=self.politeness_spin.value(),
            follow_subdomains=self.follow_subdomains_check.isChecked(),
        )

    def _auto_mode_from_ui(self) -> CrawlMode:
        if self.url_list.toPlainText().strip():
            return CrawlMode.LIST
        if self.sitemap_url.text().strip():
            return CrawlMode.SITEMAP
        return CrawlMode.HYBRID

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
        self._previous_report = self._latest_report
        self._latest_report = report
        self._crawl_run_id = report.run_ref.run_id if report.run_ref is not None else ""
        self._discovered_total = report.discovered_count
        self._completed_count = report.crawled_count + report.skipped_count
        # PR-10: a store-backed run drives the table from SQLite, one bounded page
        # at a time (the live in-memory rows are dropped). A store-less report
        # (small crawls + tests set the report directly) syncs its inline results
        # into the in-memory model.
        if report.run_ref is not None:
            self._bind_stored_model(report.run_ref)
        elif report.results:
            self.model.set_results(list(report.results))
        self._set_running(False)
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
        # "Are there results" comes from the report's summary counts (H2), so it
        # holds whether the report is store-backed or carries inline results.
        has_results = bool(self._latest_report and self._latest_report.has_rows)
        self.btn_export.setEnabled(False if running else has_results)
        self.btn_export_ai.setEnabled(False if running else has_results)
        self.btn_diff.setEnabled(False if running else (has_results and self._previous_report is not None))
        self.btn_graph.setEnabled(False if running else (has_results and bool(self._crawl_store_path)))
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
        try:
            issues = issues_for_site_report(report)
        except Exception as exc:  # recap must never abort crawl completion (_handle_report)
            logger.warning("recap build failed for run %s: %s", self._crawl_run_id, exc)
            issues = []
        self.recap_widget.update_issues(
            issues,
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
        view_model = self.table.model()
        for row in range(view_model.rowCount()):
            index = view_model.index(row, 0)
            if index.data() == url:
                self.table.selectRow(row)
                self.table.scrollTo(index)
                return

    def _open_crawl_settings(self) -> None:
        dialog = CrawlSettingsDialog(self._crawl_options, self, show_profile=True)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self._crawl_options = dialog.options()
            self._update_speed_label()

    def _open_history_browser(self) -> None:
        dialog = CrawlHistoryDialog(self._history_store, self)
        dialog.exec()

    def _update_speed_label(self) -> None:
        mode = "Gentle" if self._crawl_options.gentle_mode else "Standard"
        profile = self._effective_options().profile.value.capitalize()
        self.lbl_speed.setText(
            f"{mode} crawl, max {self._crawl_options.max_concurrent_per_host}/host · {profile} profile"
        )

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
        # The store-backed model is shown directly (its index is the source row);
        # the in-memory model is shown behind a filter proxy that must be mapped.
        model = self._stored_model if self._stored_model is not None else self.model
        source_row = index.row() if self._stored_model is not None else self.proxy.mapToSource(index).row()
        result = model.result_at(source_row)
        if result is None:
            return
        payload = result.payload or self._load_payload_for_detail(result.url)
        if payload is None:
            return
        base_url = result.final_url or result.url
        dialog = SiteCrawlDetailDialog(
            payload,
            base_url,
            on_payload_updated=lambda updated, row=source_row: model.update_payload(row, updated),
            parent=self,
        )
        self._detail_windows.append(dialog)
        dialog.show()

    def _show_graph(self) -> None:
        from .link_graph import GraphInput, build_link_graph
        from .link_graph.graph_view import LinkGraphView

        rows = self._graph_inputs_from_store()
        if not rows:
            QtWidgets.QMessageBox.information(self, "No graph data", "No crawl data to graph yet.")
            return
        root = self._latest_report.base_url if self._latest_report else ""
        graph = build_link_graph([GraphInput(*r) for r in rows], root_url=root)
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Link graph — crawl tree")
        dialog.resize(900, 680)
        layout = QtWidgets.QVBoxLayout(dialog)
        caption = QtWidgets.QLabel(
            f"{graph.node_count} nodes"
            + (" (sampled to top centrality)" if graph.sampled else "")
            + f" · {len(graph.orphans)} orphan page(s)"
        )
        layout.addWidget(caption)
        view = LinkGraphView()
        view.set_graph(graph)
        layout.addWidget(view)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        self._detail_windows.append(dialog)
        dialog.show()

    def _graph_inputs_from_store(self) -> list[tuple[str, str, int]]:
        if not self._crawl_store_path or not self._crawl_run_id:
            return []
        try:
            store = CrawlStore(self._crawl_store_path)
            try:
                return store.iter_graph_inputs(self._crawl_run_id)
            finally:
                store.close()
        except Exception:
            return []

    def _show_diff(self) -> None:
        if self._latest_report is None or self._previous_report is None:
            return
        diff = diff_reports(self._previous_report, self._latest_report)
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Crawl comparison — previous vs current")
        dialog.resize(720, 560)
        layout = QtWidgets.QVBoxLayout(dialog)
        view = QtWidgets.QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(diff_to_markdown(diff))
        layout.addWidget(view)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        self._detail_windows.append(dialog)
        dialog.show()

    def _load_payload_for_detail(self, url: str) -> CrawlPayload | None:
        """Reload a stripped payload on demand for the detail dialog, via the
        displayed report's run-bound repository (its own read connection on the
        GUI thread). Returns None when no run is bound or the read fails (H1)."""
        report = self._latest_report
        if report is None:
            return None
        try:
            with open_report_repository(report) as repo:
                return repo.load_payload(url)
        except Exception as exc:  # on-demand GUI load must not crash the app
            logger.warning("payload reload failed for %s: %s", url, exc)
            return None

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

    def _export_ai(self) -> None:
        if not self._latest_report or not self._latest_report.has_rows:
            return
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export for AI analysis",
            str(Path.home() / "silentfrog_audit_for_ai.md"),
            "Markdown (*.md)",
        )
        if not file_path:
            return
        export = export_crawl_for_llm(list(stream_report_results(self._latest_report)))
        written = write_llm_export(export, Path(file_path).with_suffix(""), fmt="both")
        names = ", ".join(p.name for p in written)
        QtWidgets.QMessageBox.information(
            self,
            "Export completed",
            f"Wrote {names}. Paste the .md into a Claude chat for a prioritised fix list.",
        )

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._active_cancel:
            self._active_cancel.set()
        self._teardown_stored_model()
        self._discard_store(self._crawl_store_path)
        self._discard_store(self._previous_store_path)
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
        left_align_tab_bar(self.tabs)
        layout.addWidget(self.tabs)
        self._populate_tabs(payload)
        self.imageSig.connect(self._handle_image_update)
        self.errorSig.connect(self._show_image_error)
        self.resize(1000, 650)

    def _build_actions(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.btn_img_dl = QtWidgets.QPushButton("Analyze images")
        self.btn_img_dl.setToolTip(
            "Fetch image dimensions, file size, content type, and cache headers for this cached page detail."
        )
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
            ("Bot Matrix", BotMatrixTab(), data),
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
        indexability_tab.update(
            payload.redirect.to_dict(), payload.canonical.to_dict(), payload.meta_robots, payload.robots
        )
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
