"""Qt dialogs for the in-app update flow.

Two dialogs:

* :class:`AboutDialog` — static info: version, current revision,
  install mode, link to the GitHub repo.
* :class:`UpdateDialog` — kicks off a background check on open, then
  renders one of five states (up-to-date, update-available, dev-mode,
  offline, unknown) with the appropriate button set.

The actual update execution is wired up in a follow-up change. Until
then, Apply opens an informative message rather than touching the
working tree.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, cast

from qtpy import QtCore, QtWidgets
from qtpy.QtCore import Qt, QProcess
from qtpy.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
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


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Silentfrog")
        layout = QVBoxLayout(self)
        local = read_local_revision(find_repo_root())
        layout.addWidget(QLabel(f"<b>Silentfrog</b> {__version__}"))
        layout.addWidget(QLabel(f"Revision: <code>{_short_sha(local.sha)}</code>"))
        layout.addWidget(QLabel(f"Install mode: {_INSTALL_MODE_LABELS[local.mode]}"))
        link = QLabel(f'<a href="{_REPO_URL}">{_REPO_URL}</a>')
        link.setOpenExternalLinks(True)
        layout.addWidget(link)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.adjustSize()


class UpdateDialog(QDialog):
    """Modal dialog that runs an update check and shows the result.

    The dialog is created in a "checking" state and re-rendered from
    :meth:`_on_check_finished` once the background worker emits.
    Buttons are rebuilt per state via :meth:`_apply_state`.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Check for Updates")
        self.setMinimumWidth(420)
        self._status_label = QLabel("Checking for updates…")
        self._details_label = QLabel("")
        self._details_label.setWordWrap(True)
        self._buttons = QDialogButtonBox()
        layout = QVBoxLayout(self)
        layout.addWidget(self._status_label)
        layout.addWidget(self._details_label)
        layout.addWidget(self._buttons)
        self._worker: _UpdateCheckWorker | None = None
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
        self._status_label.setText(
            f"You’re on the latest version ({_short_sha(result.local.sha)})."
        )
        self._details_label.setText("")
        self._set_buttons({"OK": self._close_ok})

    def _render_update_available(self, result: UpdateCheckResult) -> None:
        remote = result.remote
        # Guard for static analysis; compare() only returns
        # UPDATE_AVAILABLE when remote is non-None.
        if remote is None:
            self._render_unknown(result)
            return
        self._status_label.setText(
            "Update available: "
            f"{_short_sha(result.local.sha)} → {_short_sha(remote.sha)}"
        )
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
        self._details_label.setText(
            "If this is a fresh install, reinstall Silentfrog to record a revision."
        )
        self._set_buttons({"OK": self._close_ok})

    def _set_buttons(self, mapping: dict[str, Callable[[], None]]) -> None:
        self._buttons.clear()
        for label, handler in mapping.items():
            button = QPushButton(label)
            button.clicked.connect(handler)
            self._buttons.addButton(button, QDialogButtonBox.ActionRole)

    # ------------------------------------------------------------ actions

    def _close_ok(self) -> None:
        self.accept()

    def _on_retry_clicked(self) -> None:
        self._start_check()

    def _on_apply_clicked(self) -> None:
        # PR-3 wires this to ``tools.update_silentfrog`` and then
        # restart_app(). Until then we show a clear placeholder so the
        # user knows the UI is wired but the executor is not.
        QMessageBox.information(
            self,
            "Update not yet wired up",
            (
                "The update mechanism is not enabled in this build. "
                f"The pending target revision is {_short_sha(self._pending_apply_sha)}."
            ),
        )


def restart_app() -> None:
    """Relaunch Silentfrog in a detached process and quit the current one.

    Used by the update flow once new sources are in place.
    """
    QProcess.startDetached(sys.executable, sys.argv)
    app = cast(QApplication | None, QApplication.instance())
    if app is not None:
        app.quit()


def _short_sha(sha: str) -> str:
    if not sha:
        return "unknown"
    return sha[:7]
