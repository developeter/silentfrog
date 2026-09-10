"""Server-log analysis window (v2.0 R4 / M6).

Pure view over the already-complete ``log_analysis`` module — this file
parses nothing and evaluates no findings itself. It mirrors
``redirect_gui.py``'s shape (file picker, worker ``QThread``, progress,
results table) over ``analyse_log_file`` / ``LogAnalysisConfig`` /
``issues_for_log_report``, the same functions ``silentfrog-cli logs`` uses.

``analyse_log_file``/``analyse_log_entries`` expose no progress callback,
pause flag, or cancel flag (log_analysis.py:66-91) — unlike
``RedirectWorker``'s cooperative ``check_redirects`` call, this is one
atomic blocking call with no internal yield points. So there is only
indeterminate progress, and closing the window mid-run detaches the
worker's signals instead of blocking on it — the same non-blocking
pattern ``robots_sim_dialog.py`` uses for its own non-cancellable
``QThread``.
"""

from __future__ import annotations

from pathlib import Path

from qtpy import QtCore, QtWidgets

from .audit_issues import AuditIssue
from .log_analysis import LogAnalysisConfig, LogAnalysisReport, analyse_log_file, issues_for_log_report
from .models import GenericModel
from .theme import window_icon

_LOG_FILE_FILTER = "Access logs (*.log *.txt *.json);;All files (*)"
_KNOWN_URLS_FILTER = "Text files (*.txt);;All files (*)"
_HEADERS = ["Severity", "Finding", "URL", "Evidence", "Recommendation"]


class LogWorker(QtCore.QThread):
    """Runs ``analyse_log_file`` off the UI thread — see module docstring
    for why this has no progress/cancel hooks."""

    failed = QtCore.Signal(str)
    # Deliberately NOT named ``finished``: QThread already defines that
    # signal and shadowing it hides the thread's own lifecycle notification.
    completed = QtCore.Signal(object)

    def __init__(self, log_path: str, config: LogAnalysisConfig) -> None:
        super().__init__()
        self.log_path = log_path
        self.config = config

    def run(self) -> None:
        try:
            report = analyse_log_file(Path(self.log_path), self.config)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
            self.failed.emit(str(exc))
            self.completed.emit(None)
            return
        self.completed.emit(report)


class LogWindow(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowIcon(window_icon())
        self.setWindowTitle("Server Log Analysis – Silentfrog")
        self.setMinimumSize(760, 520)
        self.log_path = ""
        self.known_urls_path = ""
        self.worker: LogWorker | None = None
        self._build_ui()

    # ----- interface ----------------------------------------------------- #
    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(self._build_file_row())
        layout.addLayout(self._build_known_urls_row())
        self.bar = QtWidgets.QProgressBar()
        self.bar.setVisible(False)
        layout.addWidget(self.bar)
        self.lbl_summary = QtWidgets.QLabel("Load an access log to begin.")
        layout.addWidget(self.lbl_summary)
        self.table = QtWidgets.QTableView()
        self.table.setModel(GenericModel(_HEADERS, []))
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, stretch=1)
        layout.addLayout(self._build_button_row())

    def _build_file_row(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.btn_file = QtWidgets.QPushButton("Load log file…")
        self.btn_file.setToolTip(
            "Common Log Format, Combined Log Format (+referer/user-agent), or\nJSON access logs (Apache/Nginx)."
        )
        self.btn_file.clicked.connect(self._select_log_file)
        row.addWidget(self.btn_file)
        self.lbl_file = QtWidgets.QLabel("No file selected")
        _set_muted(self.lbl_file, muted=True)
        row.addWidget(self.lbl_file, stretch=1)
        return row

    def _build_known_urls_row(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.btn_known_urls = QtWidgets.QPushButton("Load known URLs (optional)…")
        self.btn_known_urls.setToolTip(
            "One URL per line. Unlocks orphan-crawl and important-URL-not-hit\nfindings. Leave unset to skip both."
        )
        self.btn_known_urls.clicked.connect(self._select_known_urls_file)
        row.addWidget(self.btn_known_urls)
        self.lbl_known_urls = QtWidgets.QLabel("No known-URLs file selected")
        _set_muted(self.lbl_known_urls, muted=True)
        row.addWidget(self.lbl_known_urls, stretch=1)
        return row

    def _build_button_row(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Analyse")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._launch)
        row.addWidget(self.btn_start)
        row.addStretch()
        return row

    # ----- slots --------------------------------------------------------- #
    def _select_log_file(self) -> None:
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select access log", "", _LOG_FILE_FILTER)
        if not fname:
            return
        self.log_path = fname
        self.lbl_file.setText(Path(fname).name)
        _set_muted(self.lbl_file, muted=False)
        self.btn_start.setEnabled(True)

    def _select_known_urls_file(self) -> None:
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select known URLs file", "", _KNOWN_URLS_FILTER)
        if not fname:
            return
        self.known_urls_path = fname
        self.lbl_known_urls.setText(Path(fname).name)
        _set_muted(self.lbl_known_urls, muted=False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.btn_file.setEnabled(enabled)
        self.btn_known_urls.setEnabled(enabled)
        self.btn_start.setEnabled(enabled and bool(self.log_path))

    def _current_config(self) -> LogAnalysisConfig:
        return LogAnalysisConfig(important_urls=_read_known_urls(self.known_urls_path))

    def _launch(self) -> None:
        self._set_controls_enabled(False)
        self.bar.setRange(0, 0)  # indeterminate: analyse_log_file has no progress hook
        self.bar.setVisible(True)
        self.lbl_summary.setText("Analysing…")
        try:
            config = self._current_config()
        except Exception as exc:  # noqa: BLE001 - mirrors LogWorker.run()'s handling
            self._on_failure(str(exc))
            self._on_finish(None)
            return
        self.worker = LogWorker(self.log_path, config)
        self.worker.failed.connect(self._on_failure)
        self.worker.completed.connect(self._on_finish)
        self.worker.start()

    def _on_failure(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Could not analyse the log", message)

    def _on_finish(self, result: object) -> None:
        self.worker = None
        self.bar.setVisible(False)
        self._set_controls_enabled(True)
        if not isinstance(result, LogAnalysisReport):
            self.table.setModel(GenericModel(_HEADERS, []))
            self.lbl_summary.setText("Analysis failed — no results.")
            return
        issues = issues_for_log_report(result)
        self.table.setModel(GenericModel(_HEADERS, [_issue_row(issue) for issue in issues]))
        self.table.resizeColumnsToContents()
        plural = "" if len(issues) == 1 else "s"
        self.lbl_summary.setText(
            f"{result.total_requests} requests analysed, {result.googlebot_hits} from Googlebot, "
            f"{len(issues)} finding{plural}."
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        """analyse_log_file has no cancel flag, so a running worker cannot
        be stopped early. Detach its signals instead of blocking on
        ``wait()`` so a slow parse cannot freeze the window on close; the
        result then lands on a disconnected signal instead of a destroyed
        widget (mirrors robots_sim_dialog.py's ``_detach_worker``)."""
        self._detach_worker()
        super().closeEvent(event)

    def _detach_worker(self) -> None:
        worker = self.worker
        if worker is None:
            return
        worker.failed.disconnect(self._on_failure)
        worker.completed.disconnect(self._on_finish)
        worker.finished.connect(worker.deleteLater)
        _retain_until_stopped(worker)
        self.worker = None


_LIVE_WORKERS: set[LogWorker] = set()


def _retain_until_stopped(worker: LogWorker) -> None:
    """Keep an in-flight worker alive past the window that started it — a
    ``QThread`` deleted while still running aborts the process."""
    _LIVE_WORKERS.add(worker)
    worker.destroyed.connect(lambda: _LIVE_WORKERS.discard(worker))


def _read_known_urls(path: str) -> tuple[str, ...]:
    """One URL per line, matching ``cli._read_known_urls``'s own contract."""
    if not path:
        return ()
    lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    return tuple(line.strip() for line in lines if line.strip())


def _issue_row(issue: AuditIssue) -> list[str]:
    evidence = "; ".join(f"{item.label}: {item.value}" for item in issue.evidence)
    return [issue.severity.value.upper(), issue.reason, issue.url, evidence, issue.recommendation]


def _set_muted(label: QtWidgets.QLabel, *, muted: bool) -> None:
    """Toggle the shared ``#hintLabel`` styling from theme.py (P6: no inline
    colours in widgets) and re-polish, since Qt only reads objectName-based
    rules when the style is applied."""
    label.setObjectName("hintLabel" if muted else "")
    style = label.style()
    style.unpolish(label)
    style.polish(label)


__all__ = ["LogWindow", "LogWorker"]
