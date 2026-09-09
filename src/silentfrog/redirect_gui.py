from __future__ import annotations

import threading
from pathlib import Path

from qtpy import QtCore, QtGui, QtWidgets

from .redirect import RedirectCheckOptions, RedirectRunResult, RedirectSummary, check_redirects
from .theme import window_icon

# A migration sheet can hold tens of thousands of rows; the live log is a tail,
# not an archive. The report on disk is the record.
_MAX_LOG_LINES = 2000
_FILE_FILTER = "Redirect lists (*.xlsx *.csv);;Excel (*.xlsx);;CSV (*.csv)"


class RedirectWorker(QtCore.QThread):
    progress = QtCore.Signal(int)
    log = QtCore.Signal(str)
    failed = QtCore.Signal(str)
    # Deliberately NOT named ``finished``: QThread already defines that signal
    # and shadowing it hides the thread's own lifecycle notification.
    completed = QtCore.Signal(object)

    def __init__(self, excel_path: str, options: RedirectCheckOptions) -> None:
        super().__init__()
        self.excel_path = excel_path
        self.options = options
        self._pause = threading.Event()
        self._cancel = threading.Event()

    # ---------- API for the GUI ----------------------------------------- #
    def toggle_pause(self) -> bool:
        """Flip pause and report the new state, so the window never has to
        reach into the worker's private flag to render its own button."""
        if self._pause.is_set():
            self._pause.clear()
        else:
            self._pause.set()
        return self._pause.is_set()

    def cancel(self) -> None:
        # Clearing pause too: a paused run must still be able to stop.
        self._cancel.set()
        self._pause.clear()

    # ---------- background work ------------------------------------------ #
    def run(self) -> None:
        try:
            result = check_redirects(
                self.excel_path,
                options=self.options,
                progress_callback=self._on_row,
                pause_flag=self._pause,
                cancel_flag=self._cancel,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
            self.failed.emit(str(exc))
            self.completed.emit(None)
            return
        self.completed.emit(result)

    def _on_row(self, done: int, total: int, url: str, status: str | int) -> None:
        self.progress.emit(int(done / total * 100) if total else 100)
        self.log.emit(f"[{done}/{total}] {url} → {status}")


class RedirectWindow(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowIcon(window_icon())
        self.setWindowTitle("Massive Redirect Check – Silentfrog")
        self.setMinimumSize(700, 480)
        self.excel_path = ""
        self.worker: RedirectWorker | None = None
        self._last_output: Path | None = None
        self._build_ui()

    # ----- interface ----------------------------------------------------- #
    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(self._build_file_row())
        layout.addLayout(self._build_options_form())
        self.bar = QtWidgets.QProgressBar()
        layout.addWidget(self.bar)
        self.txt_log = QtWidgets.QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(_MAX_LOG_LINES)
        layout.addWidget(self.txt_log, stretch=1)
        layout.addLayout(self._build_button_row())

    def _build_file_row(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.btn_file = QtWidgets.QPushButton("Load list…")
        self.btn_file.setToolTip(
            "An .xlsx or .csv with two columns: the old URL and the new one.\n"
            "A header row (Old URL / New URL, old_url / new_url, From / To) is\n"
            "detected automatically; without one the first two columns are used.\n"
            "The redirect map exported by Site Crawl can be loaded as-is."
        )
        self.btn_file.clicked.connect(self._select_file)
        row.addWidget(self.btn_file)
        self.lbl_file = QtWidgets.QLabel("No file selected")
        _set_muted(self.lbl_file, muted=True)
        row.addWidget(self.lbl_file, stretch=1)
        return row

    def _build_options_form(self) -> QtWidgets.QFormLayout:
        form = QtWidgets.QFormLayout()
        self.spin_timeout = QtWidgets.QSpinBox()
        self.spin_timeout.setRange(1, 60)
        self.spin_timeout.setValue(10)
        self.spin_timeout.setToolTip("Seconds to wait for each hop of a redirect chain.")
        form.addRow("Timeout (s):", self.spin_timeout)

        self.spin_threads = QtWidgets.QSpinBox()
        self.spin_threads.setRange(1, 20)
        self.spin_threads.setValue(5)
        self.spin_threads.setToolTip("Rows checked in parallel. Lower it if the server rate-limits you.")
        form.addRow("Threads:", self.spin_threads)

        self.chk_robots = QtWidgets.QCheckBox("Respect robots.txt")
        self.chk_robots.setChecked(True)
        self.chk_robots.setToolTip("Fetched once per host, then reused for every row on it.")
        form.addRow(self.chk_robots)

        self.chk_ssl = QtWidgets.QCheckBox("Ignore TLS certificate errors (less secure)")
        self.chk_ssl.setToolTip("Only for staging hosts with a self-signed certificate.")
        form.addRow(self.chk_ssl)

        self.chk_private = QtWidgets.QCheckBox("Allow private-network targets (disables SSRF protection)")
        self.chk_private.setToolTip(
            "Off by default. Needed only to check redirects on localhost or an\n"
            "intranet host — enable it solely for hosts you control and trust."
        )
        form.addRow(self.chk_private)
        return form

    def _build_button_row(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Start")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._launch)
        row.addWidget(self.btn_start)

        self.btn_pause = QtWidgets.QPushButton("Pause")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._toggle_pause)
        row.addWidget(self.btn_pause)

        self.btn_cancel = QtWidgets.QPushButton("Stop")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setToolTip("Stop the run and write a report with the rows already checked.")
        self.btn_cancel.clicked.connect(self._cancel)
        row.addWidget(self.btn_cancel)

        self.btn_open = QtWidgets.QPushButton("Open results folder")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_results_folder)
        row.addWidget(self.btn_open)
        row.addStretch()
        return row

    # ----- slots --------------------------------------------------------- #
    def _select_file(self) -> None:
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select redirect list", "", _FILE_FILTER)
        if not fname:
            return
        self.excel_path = fname
        self.lbl_file.setText(Path(fname).name)
        _set_muted(self.lbl_file, muted=False)
        self.btn_start.setEnabled(True)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.btn_file,
            self.spin_timeout,
            self.spin_threads,
            self.chk_robots,
            self.chk_ssl,
            self.chk_private,
        ):
            widget.setEnabled(enabled)
        self.btn_start.setEnabled(enabled and bool(self.excel_path))

    def _current_options(self) -> RedirectCheckOptions:
        return RedirectCheckOptions(
            timeout=self.spin_timeout.value(),
            max_workers=self.spin_threads.value(),
            respect_robots=self.chk_robots.isChecked(),
            verify_ssl=not self.chk_ssl.isChecked(),
            allow_private_network=self.chk_private.isChecked(),
        )

    def _launch(self) -> None:
        self._set_controls_enabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self.btn_open.setEnabled(False)
        self.bar.setValue(0)
        self.txt_log.clear()

        self.worker = RedirectWorker(self.excel_path, self._current_options())
        self.worker.progress.connect(self.bar.setValue)
        self.worker.log.connect(self.txt_log.appendPlainText)
        self.worker.failed.connect(self._on_failure)
        self.worker.completed.connect(self._on_finish)
        self.worker.start()

    def _toggle_pause(self) -> None:
        if self.worker is None:
            return
        paused = self.worker.toggle_pause()
        self.btn_pause.setText("Resume" if paused else "Pause")

    def _cancel(self) -> None:
        if self.worker is None:
            return
        self.worker.cancel()
        self.btn_cancel.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.txt_log.appendPlainText("Stopping — finishing the rows already in flight…")

    def _on_failure(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Could not run the check", message)

    def _on_finish(self, result: object) -> None:
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("Pause")
        self.btn_cancel.setEnabled(False)
        self._set_controls_enabled(True)
        if not isinstance(result, RedirectRunResult):
            return
        self.bar.setValue(100)
        self._last_output = result.output_path
        self.btn_open.setEnabled(True)
        self._show_report(result)

    def _show_report(self, result: RedirectRunResult) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.setWindowTitle("Stopped" if result.cancelled else "Done")
        box.setText(_summary_text(result.summary, result.cancelled))
        box.setInformativeText(f"Report saved to:\n{result.output_path}")
        open_button = box.addButton("Open folder", QtWidgets.QMessageBox.ActionRole)
        box.addButton(QtWidgets.QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is open_button:
            self._open_results_folder()

    def _open_results_folder(self) -> None:
        if self._last_output is None:
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self._last_output.parent)))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Stop a running check before the window goes away, so the worker
        thread never outlives the widget it reports to."""
        worker = self.worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(5000)
        super().closeEvent(event)


def _set_muted(label: QtWidgets.QLabel, *, muted: bool) -> None:
    """Toggle the shared ``#hintLabel`` styling from theme.py (P6: no inline
    colours in widgets) and re-polish, since Qt only reads objectName-based
    rules when the style is applied."""
    label.setObjectName("hintLabel" if muted else "")
    style = label.style()
    style.unpolish(label)
    style.polish(label)


def _summary_text(summary: RedirectSummary, cancelled: bool) -> str:
    """The one line a user actually wants: how many redirects are wrong."""
    headline = f"{summary.correct} of {summary.total} redirects correct"
    details = [
        f"{summary.wrong} to fix" if summary.wrong else "",
        f"{summary.chains} multi-hop chains" if summary.chains else "",
        f"{summary.loops} loops" if summary.loops else "",
        f"{summary.errors} unreachable" if summary.errors else "",
    ]
    body = " · ".join(part for part in details if part)
    prefix = "Stopped early. " if cancelled else ""
    return f"{prefix}{headline}" + (f"\n{body}" if body else "")
