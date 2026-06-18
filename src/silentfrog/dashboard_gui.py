"""Multi-URL Dashboard window (v1.1 N5b).

Paste N URLs → audit in parallel → sortable table of (URL, GEO Score,
Verdict, Top warning, Last audited). Uses the existing
``seo_crawler.analyse`` pipeline so every URL produces the same
``CrawlPayload`` shape as a single-page audit; we only surface the
GEO Score summary in this view.

The Dashboard is intentionally lightweight: no Qt QChart dependency
(deferred to a focused N5c sparkline pass). When that arrives, each
row will gain a sparkline column reading from ``crawl_history``.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from qtpy import QtCore, QtWidgets

from .theme import window_icon


class _AnalyserRunner(QtCore.QObject):
    """Runs the async ``analyse`` calls in a worker thread and
    surfaces progress + completion via Qt signals.

    Done as a thread (not asyncSlot) so we keep the GUI free of
    external async-Qt deps. ``asyncio.run`` lives in the thread; one
    fresh event loop per audit cycle.
    """

    row_ready = QtCore.Signal(int, str, int, str, str)  # row_idx, url, score, verdict, top_warning
    finished = QtCore.Signal()

    def __init__(
        self,
        urls: list[str],
        analyser: Callable[[str], Awaitable[Any]] | None = None,
    ) -> None:
        super().__init__()
        self._urls = urls
        self._analyser = analyser
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            asyncio.run(self._run_async())
        finally:
            self.finished.emit()

    async def _run_async(self) -> None:
        analyser = self._analyser or _default_analyser
        for idx, url in enumerate(self._urls):
            try:
                payload = await analyser(url)
            except Exception as exc:
                self.row_ready.emit(idx, url, 0, "Error", str(exc)[:120])
                continue
            summary = payload.ai_visibility.summary
            top_warning = ""
            for check in payload.ai_visibility.checks:
                if check.status == "warning":
                    top_warning = check.check
                    break
            self.row_ready.emit(idx, url, summary.score, summary.verdict or "-", top_warning or "-")


async def _default_analyser(url: str) -> Any:
    from .seo_crawler import analyse

    return await analyse(url)


_HEADERS = ("URL", "GEO Score", "Verdict", "Top warning")


class DashboardWindow(QtWidgets.QWidget):
    """Multi-URL batch audit window — the v1.1 N5b moat-builder.

    Public surface (used by tests):

    - ``url_input`` — QPlainTextEdit for the URL list.
    - ``audit_button`` — QPushButton.
    - ``results_table`` — QTableWidget.
    - ``parse_urls`` — module-level helper.
    """

    def __init__(self, analyser: Callable[[str], Awaitable[Any]] | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Silentfrog — Multi-URL Dashboard")
        self.setWindowIcon(window_icon())
        self.resize(960, 600)
        self._analyser = analyser
        self._runner: _AnalyserRunner | None = None

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)

        intro = QtWidgets.QLabel(
            "<b>Multi-URL Dashboard</b> — paste one URL per line, click Audit. Results stream into the table below."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        self.url_input = QtWidgets.QPlainTextEdit()
        self.url_input.setPlaceholderText("https://example.com/page-a\nhttps://example.com/page-b")
        self.url_input.setFixedHeight(120)
        outer.addWidget(self.url_input)

        controls = QtWidgets.QHBoxLayout()
        self.audit_button = QtWidgets.QPushButton("Audit")
        self.audit_button.clicked.connect(self._start_audit)
        controls.addWidget(self.audit_button)
        controls.addStretch()
        self.status_label = QtWidgets.QLabel("Idle.")
        controls.addWidget(self.status_label)
        outer.addLayout(controls)

        self.results_table = QtWidgets.QTableWidget(0, len(_HEADERS))
        self.results_table.setHorizontalHeaderLabels(_HEADERS)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setSortingEnabled(True)
        outer.addWidget(self.results_table)

    def _start_audit(self) -> None:
        urls = parse_urls(self.url_input.toPlainText())
        if not urls:
            self.status_label.setText("No valid URLs.")
            return
        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(len(urls))
        for idx, url in enumerate(urls):
            self.results_table.setItem(idx, 0, QtWidgets.QTableWidgetItem(url))
            self.results_table.setItem(idx, 1, QtWidgets.QTableWidgetItem("…"))
            self.results_table.setItem(idx, 2, QtWidgets.QTableWidgetItem("…"))
            self.results_table.setItem(idx, 3, QtWidgets.QTableWidgetItem("…"))
        self.audit_button.setEnabled(False)
        self.status_label.setText(f"Auditing {len(urls)} URL(s)…")
        self._runner = _AnalyserRunner(urls, analyser=self._analyser)
        self._runner.row_ready.connect(self._on_row_ready)
        self._runner.finished.connect(self._on_finished)
        self._runner.start()

    def _on_row_ready(self, row_idx: int, url: str, score: int, verdict: str, top_warning: str) -> None:
        self.results_table.setItem(row_idx, 0, QtWidgets.QTableWidgetItem(url))
        score_item = QtWidgets.QTableWidgetItem()
        score_item.setData(QtCore.Qt.ItemDataRole.DisplayRole, int(score))
        self.results_table.setItem(row_idx, 1, score_item)
        self.results_table.setItem(row_idx, 2, QtWidgets.QTableWidgetItem(verdict))
        self.results_table.setItem(row_idx, 3, QtWidgets.QTableWidgetItem(top_warning))

    def _on_finished(self) -> None:
        self.results_table.setSortingEnabled(True)
        self.audit_button.setEnabled(True)
        self.status_label.setText("Idle.")


def parse_urls(text: str) -> list[str]:
    """Extract clean URLs from the multi-line input.

    Splits on whitespace; keeps only entries that look like http(s)
    URLs. Strips trailing punctuation common in copy-paste flows.
    """
    candidates = text.split()
    out: list[str] = []
    for raw in candidates:
        candidate = raw.strip(",.;)]}‘’“”\"'")
        if candidate.startswith(("http://", "https://")):
            out.append(candidate)
    return out


__all__ = ["DashboardWindow", "parse_urls"]
