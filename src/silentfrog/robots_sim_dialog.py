"""'Test a URL against robots.txt…' modal dialog (v2.0 V16).

Pure view over the already-tested ``robots_simulator.simulate_robots()`` —
this module parses nothing and evaluates nothing itself. The operator pastes
a robots.txt body (or fetches one from a URL), types a target URL and a
user-agent, and sees the allow/deny verdict plus the rule that decided it.

The optional "fetch from URL" leg is the only I/O here, and it runs through
the same guarded ``fetch_page`` the crawler itself uses (SSRF + TLS checks
apply) on a ``QThread`` worker so a slow/unreachable host never freezes the
modal — mirroring ``update_gui.UpdateDialog``'s worker+signal shape, not the
bare daemon-thread + ``QMetaObject.invokeMethod`` pattern used elsewhere in
``settings_dialog.py`` (that pattern can reach into a widget the dialog has
already destroyed; see the v2.0 roadmap R1/R3 notes).
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from qtpy import QtCore, QtWidgets

from .crawl_options import DEFAULT_USER_AGENT
from .http_client import fetch_page
from .robots_simulator import RobotsRule, RobotsSimResult, simulate_robots


def _robots_txt_url(target_url: str) -> str:
    """Derive ``scheme://host/robots.txt`` from a target URL, or "" if the
    URL has no scheme/host to fetch from."""
    parsed = urlparse(target_url.strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def _rule_label(rule: RobotsRule | None) -> str:
    if rule is None:
        return "No rule matched — allowed by RFC 9309's permissive default."
    return f"{rule.verb.capitalize()} '{rule.pattern}' (matched {rule.specificity} chars)"


class _RobotsFetchWorker(QtCore.QThread):
    """Fetches one robots.txt body off the UI thread via the guarded
    ``fetch_page`` helper. A non-2xx/errored response becomes an empty body,
    matching ``robots_matcher.fetch_robots_matcher``'s own contract."""

    finished_fetch = QtCore.Signal(str)

    def __init__(self, robots_url: str, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._robots_url = robots_url

    def run(self) -> None:
        resp = asyncio.run(fetch_page(self._robots_url, timeout=10))
        body = resp.body if resp.status and resp.status < 400 else ""
        self.finished_fetch.emit(body)


_LIVE_FETCH_WORKERS: set[_RobotsFetchWorker] = set()


def _retain_until_stopped(worker: _RobotsFetchWorker) -> None:
    """Keep an in-flight fetch thread alive past the dialog that started it.

    A ``QThread`` deleted while still running aborts the process, and the
    modal can be closed during the fetch's 10s window, so the worker is
    parentless and released only once Qt has really destroyed it.
    """
    _LIVE_FETCH_WORKERS.add(worker)
    worker.finished.connect(worker.deleteLater)
    worker.destroyed.connect(lambda: _LIVE_FETCH_WORKERS.discard(worker))


class RobotsSimDialog(QtWidgets.QDialog):
    """Modal robots.txt simulator launched from Settings → Advanced."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Test a URL against robots.txt")
        self.setMinimumWidth(520)
        self._fetch_worker: _RobotsFetchWorker | None = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._build_target_group())
        layout.addWidget(self._build_body_group())
        layout.addWidget(self._build_result_group())
        layout.addWidget(self._build_button_box())

    def _build_target_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Target")
        form = QtWidgets.QFormLayout(box)
        self.edit_target_url = QtWidgets.QLineEdit()
        self.edit_target_url.setPlaceholderText("https://example.com/some/path")
        form.addRow("URL", self.edit_target_url)
        self.edit_user_agent = QtWidgets.QLineEdit(DEFAULT_USER_AGENT)
        form.addRow("User-agent", self.edit_user_agent)
        return box

    def _build_body_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("robots.txt")
        body_layout = QtWidgets.QVBoxLayout(box)
        fetch_row = QtWidgets.QWidget()
        fetch_row_layout = QtWidgets.QHBoxLayout(fetch_row)
        fetch_row_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_fetch = QtWidgets.QPushButton("Fetch from URL")
        self.btn_fetch.clicked.connect(self._on_fetch_clicked)
        self.lbl_fetch_status = QtWidgets.QLabel("")
        fetch_row_layout.addWidget(self.btn_fetch)
        fetch_row_layout.addWidget(self.lbl_fetch_status)
        fetch_row_layout.addStretch(1)
        body_layout.addWidget(fetch_row)
        self.txt_robots_body = QtWidgets.QPlainTextEdit()
        self.txt_robots_body.setPlaceholderText("Paste a robots.txt body, or fetch one above…")
        self.txt_robots_body.setFixedHeight(140)
        body_layout.addWidget(self.txt_robots_body)
        return box

    def _build_result_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Result")
        form = QtWidgets.QFormLayout(box)
        self.btn_check = QtWidgets.QPushButton("Check")
        self.btn_check.clicked.connect(self._on_check_clicked)
        form.addRow(self.btn_check)
        self.lbl_verdict = QtWidgets.QLabel("—")
        form.addRow("Verdict", self.lbl_verdict)
        self.lbl_rule = QtWidgets.QLabel("—")
        self.lbl_rule.setWordWrap(True)
        form.addRow("Matching rule", self.lbl_rule)
        self.lbl_reason = QtWidgets.QLabel("—")
        self.lbl_reason.setWordWrap(True)
        form.addRow("Reason", self.lbl_reason)
        return box

    def _build_button_box(self) -> QtWidgets.QDialogButtonBox:
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        return buttons

    def _on_fetch_clicked(self) -> None:
        if self._fetch_worker is not None:
            return
        robots_url = _robots_txt_url(self.edit_target_url.text())
        if not robots_url:
            self.lbl_fetch_status.setText("Enter a valid http(s) URL first.")
            return
        self.lbl_fetch_status.setText("Fetching…")
        worker = _RobotsFetchWorker(robots_url)
        worker.finished_fetch.connect(self._on_fetch_finished)
        _retain_until_stopped(worker)
        self._fetch_worker = worker
        worker.start()

    def _on_fetch_finished(self, body: str) -> None:
        self._fetch_worker = None
        self.txt_robots_body.setPlainText(body)
        self.lbl_fetch_status.setText("Fetched." if body else "No robots.txt found (treated as empty).")

    def done(self, result: int) -> None:
        """Detach an in-flight fetch before the modal goes away, so its
        result lands on a disconnected signal instead of destroyed widgets."""
        self._detach_worker()
        super().done(result)

    def _detach_worker(self) -> None:
        if self._fetch_worker is None:
            return
        self._fetch_worker.finished_fetch.disconnect(self._on_fetch_finished)
        self._fetch_worker = None

    def _on_check_clicked(self) -> None:
        result = simulate_robots(
            self.txt_robots_body.toPlainText(),
            self.edit_user_agent.text().strip() or "*",
            self.edit_target_url.text().strip(),
        )
        self._render_result(result)

    def _render_result(self, result: RobotsSimResult) -> None:
        self.lbl_verdict.setText("✓ Allowed" if result.allowed else "✗ Blocked")
        self.lbl_rule.setText(_rule_label(result.winning_rule))
        self.lbl_reason.setText(result.reason)
