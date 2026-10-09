"""Qt dialogs for the in-app update flow.

Two dialogs:

* :class:`AboutDialog` — version, current revision, install mode, link to
  the GitHub repo. The revision is resolved off the UI thread (see the class
  docstring).
* :class:`UpdateDialog` — kicks off a background check on open, then
  renders one of five states (up-to-date, update-available, dev-mode,
  offline, unknown) with the appropriate button set.

The actual update execution is wired up in a follow-up change. Until
then, Apply opens an informative message rather than touching the
working tree.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, cast

from qtpy import QtCore
from qtpy.QtCore import QProcess
from qtpy.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .updater import (
    GITHUB_OWNER,
    GITHUB_REPO,
    InstallMode,
    LocalRevision,
    RemoteRevision,
    UpdateStatus,
    compare,
    fetch_remote_revision,
    find_repo_root,
    read_local_revision,
)

_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"

_INSTALL_MODE_LABELS = {
    InstallMode.DEVELOPER: "Developer (git clone)",
    InstallMode.USER: "User install",
    InstallMode.UNKNOWN: "Unknown",
}


@dataclass(frozen=True)
class UpdateCheckResult:
    status: UpdateStatus
    local: LocalRevision
    remote: Optional[RemoteRevision]


class _UpdateCheckWorker(QtCore.QThread):
    """Background worker that produces an :class:`UpdateCheckResult`.

    Dev-mode installs short-circuit the network call so disconnected
    machines still resolve to a clear state.
    """

    finished_check = QtCore.Signal(object)

    def __init__(self, repo_root: Path, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._repo_root = repo_root

    def run(self) -> None:
        local = read_local_revision(self._repo_root)
        remote: Optional[RemoteRevision] = None
        if local.mode is not InstallMode.DEVELOPER:
            remote = asyncio.run(fetch_remote_revision())
        status = compare(local, remote)
        self.finished_check.emit(UpdateCheckResult(status=status, local=local, remote=remote))


class _JobHolder:
    """Plain (non-Qt) box the revision worker writes into — same pattern as
    ``google_connect_dialog._JobHolder`` (see that module's docstring)."""

    def __init__(self) -> None:
        self.done = False
        self.result: LocalRevision | None = None


def _start_daemon(target: Callable[..., None], *args: Any) -> None:
    """Seam over ``threading.Thread`` so tests can stub the threading
    (mirrors ``google_connect_dialog._start_daemon``)."""
    threading.Thread(target=target, args=args, daemon=True).start()


def _resolve_local_revision() -> LocalRevision:
    """Seam: the blocking part (two ``git`` spawns in developer mode)."""
    return read_local_revision(find_repo_root())


def _revision_worker(holder: _JobHolder) -> None:
    # Any failure must still complete the holder, or the dialog would poll
    # "Revision: …" forever; result None -> "unknown", and it is not cached.
    try:
        holder.result = _resolve_local_revision()
    except Exception:
        holder.result = None
    finally:
        holder.done = True


# Process-wide: the revision cannot change while the app runs, so every About
# click after the first (even one opened while the first lookup is still in
# flight, or after its dialog was closed) reuses this job instead of spawning
# git again. Only touched from the UI thread; the worker writes the holder only.
_revision_job: _JobHolder | None = None


def _shared_revision_job() -> _JobHolder:
    global _revision_job
    job = _revision_job
    # A failed lookup (result None) is not cached; the next About retries it.
    if job is None or (job.done and job.result is None):
        job = _revision_job = _JobHolder()
        _start_daemon(_revision_worker, job)
    return job


class AboutDialog(QDialog):
    """Shows version immediately; revision/branch/mode fill in once resolved.

    Resolving the revision spawns ``git`` (hundreds of ms, seconds under some
    antivirus), and ``exec()`` is application-modal, so doing it in
    ``__init__`` froze every window. A daemon thread writes only into a plain
    ``_JobHolder``; this dialog polls it with its own ``QTimer`` (no
    ``QMetaObject.invokeMethod`` on a widget, which would be a use-after-free
    if the dialog closes mid-lookup — see ``google_connect_dialog``).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Silentfrog")
        layout = QVBoxLayout(self)
        self._branch_label = QLabel("Branch: …")
        self._revision_label = QLabel("Revision: …")
        self._mode_label = QLabel("Install mode: …")
        layout.addWidget(QLabel(f"<b>Silentfrog</b> {__version__}"))
        for label in (self._branch_label, self._revision_label, self._mode_label):
            layout.addWidget(label)
        link = QLabel(f'<a href="{_REPO_URL}">{_REPO_URL}</a>')
        link.setOpenExternalLinks(True)
        layout.addWidget(link)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._on_poll_timer)
        self._job: _JobHolder | None = _shared_revision_job()
        self._on_poll_timer()
        if self._job is not None:
            self._poll_timer.start()
        self.adjustSize()

    def _on_poll_timer(self) -> None:
        job = self._job
        if job is None or not job.done:
            return
        self._poll_timer.stop()
        self._job = None
        self._apply_revision(job.result)
        self.adjustSize()

    def _apply_revision(self, local: LocalRevision | None) -> None:
        sha = local.sha if local else ""
        mode = local.mode if local else InstallMode.UNKNOWN
        branch = local.branch if local else ""
        self._revision_label.setText(f"Revision: <code>{_short_sha(sha)}</code>")
        self._mode_label.setText(f"Install mode: {_INSTALL_MODE_LABELS[mode]}")
        self._branch_label.setText(f"Branch: <code>{branch}</code>")
        self._branch_label.setVisible(bool(branch))
        if not branch:
            self._branch_label.setText("")

    def done(self, result: int) -> None:
        """Stop polling and drop the holder before teardown: a late worker
        write then lands in a holder nothing reads, never in a Qt widget."""
        self._poll_timer.stop()
        self._job = None
        super().done(result)


class UpdateDialog(QDialog):
    """Modal dialog that runs an update check and shows the result.

    The dialog is created in a "checking" state and re-rendered from
    :meth:`_on_check_finished` once the background worker emits.
    Buttons are rebuilt per state via :meth:`_apply_state`.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Check for Updates")
        self.setMinimumWidth(480)
        self._status_label = QLabel("Checking for updates…")
        self._status_label.setWordWrap(True)
        self._details_label = QLabel("")
        self._details_label.setWordWrap(True)
        self._buttons = QDialogButtonBox()
        layout = QVBoxLayout(self)
        layout.addWidget(self._status_label)
        layout.addWidget(self._details_label)
        layout.addWidget(self._buttons)
        self._worker: _UpdateCheckWorker | None = None
        self._process: QProcess | None = None
        self._pending_apply_sha: str = ""

    # ------------------------------------------------------------ lifecycle

    def showEvent(self, event: QtCore.QEvent) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        if self._worker is None:
            self._start_check()

    def _start_check(self) -> None:
        self._reset_to_checking_state()
        worker = _UpdateCheckWorker(find_repo_root(), self)
        worker.finished_check.connect(self._on_check_finished)
        self._worker = worker
        worker.start()

    def _on_check_finished(self, result: UpdateCheckResult) -> None:
        self._worker = None
        self._apply_state(result)

    # ------------------------------------------------------------ rendering

    def _reset_to_checking_state(self) -> None:
        self._status_label.setText("Checking for updates…")
        self._details_label.setText("")
        self._buttons.clear()

    def _apply_state(self, result: UpdateCheckResult) -> None:
        renderer = self._renderers().get(result.status, self._render_unknown)
        renderer(result)

    def _renderers(self) -> dict[UpdateStatus, Callable[[UpdateCheckResult], None]]:
        return {
            UpdateStatus.UP_TO_DATE: self._render_up_to_date,
            UpdateStatus.UPDATE_AVAILABLE: self._render_update_available,
            UpdateStatus.DEV_MODE_USE_GIT: self._render_dev_mode,
            UpdateStatus.OFFLINE: self._render_offline,
            UpdateStatus.UNKNOWN: self._render_unknown,
        }

    def _render_up_to_date(self, result: UpdateCheckResult) -> None:
        self._status_label.setText(f"You’re on the latest version ({_short_sha(result.local.sha)}).")
        self._details_label.setText("")
        self._set_buttons({"OK": self._close_ok})

    def _render_update_available(self, result: UpdateCheckResult) -> None:
        remote = result.remote
        # Guard for static analysis; compare() only returns
        # UPDATE_AVAILABLE when remote is non-None.
        if remote is None:
            self._render_unknown(result)
            return
        self._status_label.setText(f"Update available: {_short_sha(result.local.sha)} → {_short_sha(remote.sha)}")
        first_line = remote.message.splitlines()[0] if remote.message else ""
        self._details_label.setText(first_line)
        self._pending_apply_sha = remote.sha
        self._set_buttons(
            {
                "Apply and restart": self._on_apply_clicked,
                "Cancel": self._close_ok,
            }
        )

    def _render_dev_mode(self, _result: UpdateCheckResult) -> None:
        self._status_label.setText("You’re on a developer install (git clone).")
        self._details_label.setText(
            "Use <code>git pull</code> to update. This dialog will not modify your working tree."
        )
        self._set_buttons({"OK": self._close_ok})

    def _render_offline(self, _result: UpdateCheckResult) -> None:
        self._status_label.setText("Could not reach GitHub.")
        self._details_label.setText("Check your internet connection and try again.")
        self._set_buttons(
            {
                "Retry": self._on_retry_clicked,
                "Cancel": self._close_ok,
            }
        )

    def _render_unknown(self, _result: UpdateCheckResult) -> None:
        self._status_label.setText("Could not determine the current revision.")
        self._details_label.setText("If this is a fresh install, reinstall Silentfrog to record a revision.")
        self._set_buttons({"OK": self._close_ok})

    def _set_buttons(self, mapping: dict[str, Callable[[], None]]) -> None:
        self._buttons.clear()
        for label, handler in mapping.items():
            button = QPushButton(label)
            button.clicked.connect(handler)
            self._buttons.addButton(button, QDialogButtonBox.ActionRole)
        # The QDialog does not auto-grow when content swaps from
        # "Checking for updates…" to a multi-line status + extra
        # buttons (e.g. Apply / Cancel); without adjustSize() the
        # button row gets clipped at the bottom on macOS.
        self.adjustSize()

    # ------------------------------------------------------------ actions

    def _close_ok(self) -> None:
        self.accept()

    def _on_retry_clicked(self) -> None:
        self._start_check()

    def _on_apply_clicked(self) -> None:
        if not self._pending_apply_sha:
            return
        self._status_label.setText("Applying update…")
        self._details_label.setText(f"Fetching {_short_sha(self._pending_apply_sha)} and refreshing the venv.")
        self._buttons.clear()
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.finished.connect(self._on_apply_finished)
        process.readyReadStandardOutput.connect(lambda: self._append_log(bytes(process.readAllStandardOutput())))
        program, args = _updater_subprocess_command(self._pending_apply_sha)
        process.start(program, args)
        self._process = process

    def _on_apply_finished(self, exit_code: int, _exit_status: object) -> None:
        if exit_code == 0:
            restart_app()
            return
        self._status_label.setText("Update failed.")
        existing = self._details_label.text()
        error_line = f"`tools.update_silentfrog` exited with code {exit_code}."
        self._details_label.setText(f"{existing}\n\n{error_line}" if existing else error_line)
        self._set_buttons({"Close": self._close_ok})

    def _append_log(self, chunk: bytes) -> None:
        text = chunk.decode("utf-8", errors="replace").rstrip()
        if not text:
            return
        existing = self._details_label.text()
        self._details_label.setText(f"{existing}\n{text}" if existing else text)


def restart_app() -> None:
    """Relaunch Silentfrog in a detached process and quit the current one.

    Used by the update flow once new sources are in place. We launch the
    venv's ``silentfrog`` console-script binary directly rather than
    relying on ``sys.executable`` + ``sys.argv``: on Windows, pip's
    console-script wrappers report ``sys.argv[0]`` as ``...\\silentfrog``
    (without ``.exe``), so the naive relaunch tries
    ``python.exe <repo>\\.venv\\Scripts\\silentfrog`` and dies with
    "No such file or directory".
    """
    binary = _venv_silentfrog_binary()
    if binary is not None and binary.is_file():
        QProcess.startDetached(str(binary), [])
    else:
        # Fall back to the previous behaviour for dev clones that
        # haven't been installed into a .venv (rare; the in-app
        # updater only runs in user-mode installs, but defence first).
        QProcess.startDetached(sys.executable, sys.argv)
    app = cast(QApplication | None, QApplication.instance())
    if app is not None:
        app.quit()


def _venv_silentfrog_binary() -> Path | None:
    """Resolve the venv's ``silentfrog`` console-script for relaunch.

    Returns ``None`` when the venv layout can't be located (very early
    in setup, or non-standard install).
    """
    repo_root = find_repo_root()
    if os.name == "nt":
        candidate = repo_root / ".venv" / "Scripts" / "silentfrog.exe"
    else:
        candidate = repo_root / ".venv" / "bin" / "silentfrog"
    return candidate if candidate.exists() else None


def _updater_subprocess_command(revision: str) -> tuple[str, list[str]]:
    """Build the ``(program, args)`` pair for the update subprocess.

    Extracted so tests can assert it without running QProcess.
    """
    return sys.executable, ["-m", "tools.update_silentfrog", "--revision", revision]


def _short_sha(sha: str) -> str:
    if not sha:
        return "unknown"
    return sha[:7]
