from __future__ import annotations

import json
from pathlib import Path

from qtpy import QtCore, QtWidgets

from .audit_issues import IssueSeverity
from .charts import SeriesChart, make_series_chart
from .crawl_history import CrawlHistoryRun, CrawlHistoryStore, diff_runs
from .crawl_trends import CrawlTrend, IssueTrend, build_trend

_HISTORY_HEADERS = ["Site", "Created", "URLs", "Critical", "Warnings", "Info", "Health", "Run ID"]
_TRENDS_PLACEHOLDER = "Trends appear after two crawls of the same site."


class CrawlHistoryRunsModel(QtCore.QAbstractTableModel):
    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._runs: list[CrawlHistoryRun] = []

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._runs)

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_HISTORY_HEADERS)

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        run = self._runs[index.row()]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return _run_cells(run)[index.column()]
        if role == QtCore.Qt.ItemDataRole.UserRole:
            return run
        return None

    def headerData(
        self, section: int, orientation: QtCore.Qt.Orientation, role: int = QtCore.Qt.ItemDataRole.DisplayRole
    ):
        if orientation != QtCore.Qt.Orientation.Horizontal:
            return None
        return _HISTORY_HEADERS[section] if role == QtCore.Qt.ItemDataRole.DisplayRole else None

    def set_runs(self, runs: list[CrawlHistoryRun]) -> None:
        self.beginResetModel()
        self._runs = runs
        self.endResetModel()

    def run_at(self, row: int) -> CrawlHistoryRun | None:
        if 0 <= row < len(self._runs):
            return self._runs[row]
        return None


class CrawlHistoryDialog(QtWidgets.QDialog):
    # v3: emitted with the selected CrawlHistoryRun when the user asks to
    # reopen a saved scan whose SQLite store is still on disk.
    openRunRequested = QtCore.Signal(object)

    def __init__(self, store: CrawlHistoryStore, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._runs_ascending: list[CrawlHistoryRun] = []
        self.setWindowTitle("Past Site Crawls")
        self.resize(980, 620)
        self._build_ui()
        self._connect_signals()
        self.reload()

    def reload(self) -> None:
        self._runs_ascending = self._store.load_runs()
        self.model.set_runs(list(reversed(self._runs_ascending)))
        self._select_first_row()
        self._sync_actions()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._build_intro())
        layout.addWidget(self._build_table(), 1)
        layout.addWidget(self._build_details(), 1)
        layout.addWidget(self._build_trends())
        layout.addLayout(self._build_actions())

    def _build_intro(self) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(
            "Local Site Crawl history. These files stay on this computer and are not synced remotely."
        )
        label.setWordWrap(True)
        return label

    def _build_table(self) -> QtWidgets.QTableView:
        self.model = CrawlHistoryRunsModel(self)
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 180)
        self.table.setColumnWidth(1, 175)
        self.table.setColumnWidth(7, 260)
        return self.table

    def _build_details(self) -> QtWidgets.QPlainTextEdit:
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select a saved crawl to view the summary and local diff.")
        return self.details

    def _build_trends(self) -> QtWidgets.QGroupBox:
        # v3 G2: health score + per-issue counts across the selected site's
        # stored runs. build_trend is pure derivation over CrawlHistoryStore
        # data already loaded for this dialog — no extra I/O.
        box = QtWidgets.QGroupBox("Trends")
        box.setMaximumHeight(220)
        outer = QtWidgets.QVBoxLayout(box)
        self._trend_placeholder = QtWidgets.QLabel(_TRENDS_PLACEHOLDER)
        self._trend_placeholder.setWordWrap(True)
        self._trend_content = QtWidgets.QWidget()
        content_row = QtWidgets.QHBoxLayout(self._trend_content)
        content_row.setContentsMargins(0, 0, 0, 0)
        self._trend_chart = make_series_chart("Health score")
        self.trend_issues = QtWidgets.QPlainTextEdit()
        self.trend_issues.setReadOnly(True)
        content_row.addWidget(self._trend_chart, 1)
        content_row.addWidget(self.trend_issues, 1)
        outer.addWidget(self._trend_placeholder)
        outer.addWidget(self._trend_content)
        return box

    def _build_actions(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.btn_open = QtWidgets.QPushButton("Open scan")
        self.btn_open.setToolTip(
            "Reopen this scan in the Site Crawl results view with full per-page detail. "
            "Available while the scan's local crawl database is still on disk."
        )
        self.btn_export = QtWidgets.QPushButton("Export selected JSON")
        self.btn_delete = QtWidgets.QPushButton("Delete selected")
        self.btn_close = QtWidgets.QPushButton("Close")
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_export)
        row.addWidget(self.btn_delete)
        row.addStretch()
        row.addWidget(self.btn_close)
        return row

    def _connect_signals(self) -> None:
        self.table.selectionModel().currentChanged.connect(lambda *_: self._update_details())
        self.table.doubleClicked.connect(lambda *_: self._open_selected())
        self.btn_open.clicked.connect(self._open_selected)
        self.btn_export.clicked.connect(self._export_selected)
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_close.clicked.connect(self.accept)

    def _select_first_row(self) -> None:
        if self.model.rowCount() <= 0:
            self.details.setPlainText("No saved Site Crawl runs yet.")
            self._update_trends(None)
            return
        self.table.selectRow(0)
        self._update_details()

    def _sync_actions(self) -> None:
        run = self._selected_run()
        has_selection = run is not None
        self.btn_export.setEnabled(has_selection)
        self.btn_delete.setEnabled(has_selection)
        self.btn_open.setEnabled(has_selection and _run_openable(run))

    def _selected_run(self) -> CrawlHistoryRun | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.model.run_at(rows[0].row())

    def _update_details(self) -> None:
        run = self._selected_run()
        self._sync_actions()
        self.details.setPlainText(
            _details_text(run, self._previous_run(run)) if run else "No saved Site Crawl runs yet."
        )
        self._update_trends(run)

    def _previous_run(self, run: CrawlHistoryRun | None) -> CrawlHistoryRun | None:
        if run is None:
            return None
        older = [
            item
            for item in self._runs_ascending
            if item.scope_key == run.scope_key and item.created_at < run.created_at
        ]
        return older[-1] if older else None

    def _scoped_runs(self, run: CrawlHistoryRun) -> list[CrawlHistoryRun]:
        return [item for item in self._runs_ascending if item.scope_key == run.scope_key]

    def _update_trends(self, run: CrawlHistoryRun | None) -> None:
        scoped = self._scoped_runs(run) if run else []
        if len(scoped) < 2:
            self._trend_placeholder.setVisible(True)
            self._trend_content.setVisible(False)
            return
        self._trend_placeholder.setVisible(False)
        self._trend_content.setVisible(True)
        _render_trend(build_trend(scoped), self._trend_chart, self.trend_issues)

    def _export_selected(self) -> None:
        run = self._selected_run()
        if run is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export saved crawl",
            str(Path.home() / f"{_safe_export_name(run)}.json"),
            "JSON files (*.json)",
        )
        if not path:
            return
        target = Path(path if path.lower().endswith(".json") else f"{path}.json")
        target.write_text(json.dumps(run.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def _open_selected(self) -> None:
        run = self._selected_run()
        if run is None or not _run_openable(run):
            return
        self.openRunRequested.emit(run)
        self.accept()

    def _delete_selected(self) -> None:
        run = self._selected_run()
        if run is None or not _confirm_delete(self, run):
            return
        self._store.delete_run(run.run_id)
        _unlink_run_store(run)
        self.reload()


def _run_cells(run: CrawlHistoryRun) -> list[object]:
    return [
        run.scope_key,
        run.created_at,
        run.discovered_count,
        run.severity_count(IssueSeverity.CRITICAL),
        run.severity_count(IssueSeverity.WARNING),
        run.severity_count(IssueSeverity.INFO),
        run.health_score(),
        run.run_id,
    ]


def _details_text(run: CrawlHistoryRun, previous: CrawlHistoryRun | None) -> str:
    parts = [_run_summary(run), _diff_summary(run, previous), _top_issues(run)]
    return "\n\n".join(part for part in parts if part)


def _run_summary(run: CrawlHistoryRun) -> str:
    return "\n".join(
        [
            f"Site: {run.scope_key}",
            f"Run ID: {run.run_id}",
            f"Created: {run.created_at}",
            f"URLs: {run.discovered_count} discovered, {run.crawled_count} crawled, {run.failed_count} failed, {run.skipped_count} skipped",
            f"Issues: {run.severity_count(IssueSeverity.CRITICAL)} critical, {run.severity_count(IssueSeverity.WARNING)} warnings, {run.severity_count(IssueSeverity.INFO)} info",
            f"Health score: {run.health_score()} (lower is better)",
        ]
    )


def _diff_summary(run: CrawlHistoryRun, previous: CrawlHistoryRun | None) -> str:
    if previous is None:
        return "Diff: no previous local run for this site."
    diff = diff_runs(previous, run)
    return "\n".join(
        [
            f"Diff from previous run ({previous.created_at}):",
            f"- {len(diff.new_issues)} new issues",
            f"- {len(diff.fixed_issues)} fixed issues",
            f"- {len(diff.worsened_issues)} worsened issues",
            f"- {len(diff.recurring_issues)} recurring issues",
            f"- Health trend: {diff.trend} ({_signed(diff.health_delta)})",
        ]
    )


def _top_issues(run: CrawlHistoryRun) -> str:
    if not run.issues:
        return "Top issues: none recorded."
    lines = ["Top issues:"]
    lines.extend(
        f"- {issue.severity.value}: {issue.issue_id} | {issue.url or run.scope_key}" for issue in run.issues[:10]
    )
    return "\n".join(lines)


def _render_trend(trend: CrawlTrend, chart: SeriesChart, issues_panel: QtWidgets.QPlainTextEdit) -> None:
    chart.set_series(
        [_short_date(point.created_at) for point in trend.points], [point.health_score for point in trend.points]
    )
    issues_panel.setPlainText(_issue_trend_text(trend))


def _short_date(created_at: str) -> str:
    return created_at[:10] if len(created_at) >= 10 else created_at


def _issue_trend_text(trend: CrawlTrend) -> str:
    if not trend.issue_trends:
        return "No recurring issues in this window."
    return "\n".join(_issue_trend_line(item) for item in trend.issue_trends)


def _issue_trend_line(item: IssueTrend) -> str:
    # A bare signed delta, not an arrow: for issue counts more = worse, so
    # up/down glyphs would invert the reader's good/bad instinct.
    chain = " → ".join(str(count) for count in item.counts)
    suffix = f" ({item.delta:+d})" if item.delta else ""
    return f"{item.issue_id} ({item.severity.value}): {chain}{suffix}"


def _run_openable(run: CrawlHistoryRun | None) -> bool:
    return run is not None and run.has_store and Path(run.db_path).is_file()


def _unlink_run_store(run: CrawlHistoryRun) -> None:
    """Best-effort removal of the run's crawl database (+WAL/SHM siblings)."""
    if not run.db_path:
        return
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(run.db_path + suffix).unlink(missing_ok=True)
        except OSError:
            pass


def _confirm_delete(parent: QtWidgets.QWidget, run: CrawlHistoryRun) -> bool:
    detail = (
        "This removes the local history file and the stored crawl database."
        if run.has_store
        else "This only removes the local history file."
    )
    result = QtWidgets.QMessageBox.question(
        parent,
        "Delete saved crawl",
        f"Delete the saved crawl for {run.scope_key} from {run.created_at}?\n\n{detail}",
    )
    return result == QtWidgets.QMessageBox.StandardButton.Yes


def _safe_export_name(run: CrawlHistoryRun) -> str:
    return "".join(char if char.isalnum() else "-" for char in f"silentfrog-{run.scope_key}-{run.created_at}")


def _signed(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


__all__ = ["CrawlHistoryDialog", "CrawlHistoryRunsModel"]
