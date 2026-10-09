from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from qtpy import QtWidgets

import silentfrog.update_gui as update_gui
from silentfrog.gui import HomeWindow  # type: ignore[reportMissingImports]
from silentfrog.update_gui import (  # type: ignore[reportMissingImports]
    AboutDialog,
    UpdateCheckResult,
    UpdateDialog,
    _updater_subprocess_command,
)
from silentfrog.updater import (  # type: ignore[reportMissingImports]
    InstallMode,
    LocalRevision,
    RemoteRevision,
    UpdateStatus,
)


def _make_local(sha: str = "a" * 40, mode: InstallMode = InstallMode.USER, branch: str = "") -> LocalRevision:
    return LocalRevision(sha=sha, mode=mode, repo_root=Path("."), branch=branch)


def _make_remote(sha: str = "b" * 40, message: str = "Latest commit\n\nbody") -> RemoteRevision:
    return RemoteRevision(
        sha=sha,
        committed_at=datetime(2026, 5, 19, tzinfo=UTC),
        message=message,
    )


def _new_dialog(qtbot) -> UpdateDialog:
    dlg = UpdateDialog()
    qtbot.addWidget(dlg)
    return dlg


def _button_labels(dlg: UpdateDialog) -> list[str]:
    return [b.text().replace("&", "") for b in dlg._buttons.buttons()]


def test_update_dialog_renders_up_to_date(qtbot) -> None:
    dlg = _new_dialog(qtbot)
    result = UpdateCheckResult(
        status=UpdateStatus.UP_TO_DATE,
        local=_make_local(sha="abcdef1" + "0" * 33),
        remote=_make_remote(sha="abcdef1" + "0" * 33),
    )
    dlg._apply_state(result)
    assert "latest version" in dlg._status_label.text()
    assert "abcdef1" in dlg._status_label.text()
    assert _button_labels(dlg) == ["OK"]


def test_update_dialog_renders_update_available_with_apply_and_cancel(qtbot) -> None:
    dlg = _new_dialog(qtbot)
    local = _make_local(sha="1111111" + "0" * 33)
    remote = _make_remote(sha="2222222" + "0" * 33, message="Fix the GUI\n\ndetails")
    dlg._apply_state(UpdateCheckResult(UpdateStatus.UPDATE_AVAILABLE, local, remote))
    assert "Update available" in dlg._status_label.text()
    assert "1111111" in dlg._status_label.text()
    assert "2222222" in dlg._status_label.text()
    assert dlg._details_label.text() == "Fix the GUI"
    assert _button_labels(dlg) == ["Apply and restart", "Cancel"]
    assert dlg._pending_apply_sha == remote.sha


def test_update_dialog_renders_dev_mode_message(qtbot) -> None:
    dlg = _new_dialog(qtbot)
    local = _make_local(mode=InstallMode.DEVELOPER)
    dlg._apply_state(UpdateCheckResult(UpdateStatus.DEV_MODE_USE_GIT, local, None))
    assert "developer install" in dlg._status_label.text()
    assert "git pull" in dlg._details_label.text()
    assert _button_labels(dlg) == ["OK"]


def test_update_dialog_renders_offline_with_retry(qtbot) -> None:
    dlg = _new_dialog(qtbot)
    dlg._apply_state(UpdateCheckResult(UpdateStatus.OFFLINE, _make_local(), None))
    assert "Could not reach" in dlg._status_label.text()
    assert _button_labels(dlg) == ["Retry", "Cancel"]


def test_update_dialog_renders_unknown(qtbot) -> None:
    dlg = _new_dialog(qtbot)
    local = LocalRevision(sha="", mode=InstallMode.UNKNOWN, repo_root=Path("."))
    dlg._apply_state(UpdateCheckResult(UpdateStatus.UNKNOWN, local, None))
    assert "current revision" in dlg._status_label.text()
    assert _button_labels(dlg) == ["OK"]


def test_update_dialog_update_available_with_missing_remote_falls_back_to_unknown(
    qtbot,
) -> None:
    # Defence in depth: compare() never produces this combination, but the
    # renderer must not crash if it ever did.
    dlg = _new_dialog(qtbot)
    dlg._apply_state(UpdateCheckResult(UpdateStatus.UPDATE_AVAILABLE, _make_local(), None))
    assert "current revision" in dlg._status_label.text()


def test_update_dialog_retry_button_restarts_the_check(qtbot, monkeypatch) -> None:
    dlg = _new_dialog(qtbot)
    calls = {"count": 0}

    def fake_start_check() -> None:
        calls["count"] += 1

    monkeypatch.setattr(dlg, "_start_check", fake_start_check)
    dlg._apply_state(UpdateCheckResult(UpdateStatus.OFFLINE, _make_local(), None))
    retry_button = next(b for b in dlg._buttons.buttons() if "Retry" in b.text())
    retry_button.click()
    assert calls["count"] == 1


@pytest.fixture(autouse=True)
def _fresh_revision_cache(monkeypatch) -> None:
    # The resolved revision is cached process-wide; keep tests independent.
    monkeypatch.setattr(update_gui, "_revision_job", None)


def _about_text(dlg: AboutDialog) -> str:
    return " ".join(label.text() for label in dlg.findChildren(QtWidgets.QLabel))


def _about(qtbot, monkeypatch, local: LocalRevision) -> AboutDialog:
    """Build an AboutDialog whose revision lookup runs inline (no thread)."""
    monkeypatch.setattr(update_gui, "read_local_revision", lambda _root: local)
    monkeypatch.setattr(update_gui, "_start_daemon", lambda target, *args: target(*args))
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    return dlg


def _capture_daemons(monkeypatch) -> list:
    started: list = []
    monkeypatch.setattr(update_gui, "_start_daemon", lambda target, *args: started.append((target, args)))
    return started


def test_about_dialog_shows_version_and_repo_link(qtbot, monkeypatch) -> None:
    dlg = _about(qtbot, monkeypatch, _make_local(sha="cafebabe" + "0" * 32))
    text = _about_text(dlg)
    assert "Silentfrog" in text
    assert "cafeb" in text
    assert "developeter/silentfrog" in text


def test_about_dialog_shows_branch_when_present(qtbot, monkeypatch) -> None:
    dlg = _about(qtbot, monkeypatch, _make_local(mode=InstallMode.DEVELOPER, branch="feature/v2.0"))
    text = _about_text(dlg)
    assert "Branch" in text
    assert "feature/v2.0" in text


def test_about_dialog_omits_branch_when_empty(qtbot, monkeypatch) -> None:
    dlg = _about(qtbot, monkeypatch, _make_local(branch=""))
    assert "Branch" not in _about_text(dlg)


def test_about_dialog_never_resolves_revision_on_the_calling_thread(qtbot, monkeypatch) -> None:
    calls: list[threading.Thread] = []
    monkeypatch.setattr(
        update_gui, "read_local_revision", lambda _root: calls.append(threading.current_thread()) or _make_local()
    )
    started = _capture_daemons(monkeypatch)
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    assert calls == []  # constructing the dialog does not touch git
    assert len(started) == 1
    assert "Revision: …" in _about_text(dlg)
    target, args = started[0]
    worker = threading.Thread(target=target, args=args)
    worker.start()
    worker.join()
    assert calls == [worker]  # the lookup ran on the daemon, not the UI thread


def test_about_dialog_fills_labels_after_holder_completes_and_one_tick(qtbot, monkeypatch) -> None:
    local = _make_local(sha="1234567" + "0" * 33, mode=InstallMode.DEVELOPER, branch="feature/v2.0")
    monkeypatch.setattr(update_gui, "read_local_revision", lambda _root: local)
    started = _capture_daemons(monkeypatch)
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    assert dlg._poll_timer.isActive()
    dlg._on_poll_timer()  # worker not finished yet: nothing changes
    assert "Revision: …" in _about_text(dlg)
    target, args = started[0]
    target(*args)
    dlg._on_poll_timer()
    text = _about_text(dlg)
    assert "1234567" in text
    assert "feature/v2.0" in text
    assert "Developer" in text
    assert not dlg._poll_timer.isActive()


def test_about_dialog_second_open_uses_cache_and_starts_no_daemon(qtbot, monkeypatch) -> None:
    first = _about(qtbot, monkeypatch, _make_local(sha="abcdef0" + "0" * 33, branch="dev"))
    assert "abcdef0" in _about_text(first)
    started = _capture_daemons(monkeypatch)
    second = AboutDialog()
    qtbot.addWidget(second)
    assert started == []
    assert "abcdef0" in _about_text(second)  # shown immediately, no timer tick
    assert not second._poll_timer.isActive()


@pytest.mark.parametrize("error", [OSError("unreadable"), RuntimeError("unexpected")])
def test_about_dialog_failed_lookup_shows_unknown_and_is_retried(qtbot, monkeypatch, error) -> None:
    def boom(_root):
        raise error

    monkeypatch.setattr(update_gui, "read_local_revision", boom)
    monkeypatch.setattr(update_gui, "_start_daemon", lambda target, *args: target(*args))
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    assert "unknown" in _about_text(dlg)
    assert not dlg._poll_timer.isActive()
    started = _capture_daemons(monkeypatch)
    qtbot.addWidget(AboutDialog())
    assert len(started) == 1  # a failure is not cached


def test_about_dialog_closed_before_completion_ignores_late_result(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(update_gui, "read_local_revision", lambda _root: _make_local(sha="feedbee" + "0" * 33))
    started = _capture_daemons(monkeypatch)
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    dlg.done(0)
    assert not dlg._poll_timer.isActive()
    assert dlg._job is None
    target, args = started[0]
    target(*args)  # the orphaned daemon finishes after the dialog closed
    qtbot.wait(250)
    dlg._on_poll_timer()
    assert "Revision: …" in _about_text(dlg)
    assert "feedbee" not in _about_text(dlg)


def test_home_window_help_menu_lists_check_and_about(qtbot) -> None:
    win = HomeWindow()
    qtbot.addWidget(win)
    menu_titles = [m.title().replace("&", "") for m in win.menuBar().findChildren(__import__("qtpy").QtWidgets.QMenu)]
    assert "Help" in menu_titles
    help_menu = next(
        m
        for m in win.menuBar().findChildren(__import__("qtpy").QtWidgets.QMenu)
        if m.title().replace("&", "") == "Help"
    )
    action_texts = [a.text().replace("&", "") for a in help_menu.actions()]
    assert any("Check for Updates" in text for text in action_texts)
    assert any("About Silentfrog" in text for text in action_texts)


@pytest.mark.parametrize(
    "status, expected_buttons",
    [
        (UpdateStatus.UP_TO_DATE, ["OK"]),
        (UpdateStatus.DEV_MODE_USE_GIT, ["OK"]),
        (UpdateStatus.UNKNOWN, ["OK"]),
        (UpdateStatus.OFFLINE, ["Retry", "Cancel"]),
    ],
)
def test_button_sets_per_simple_state(qtbot, status, expected_buttons) -> None:
    dlg = _new_dialog(qtbot)
    dlg._apply_state(UpdateCheckResult(status, _make_local(), None))
    assert _button_labels(dlg) == expected_buttons


def test_updater_subprocess_command_pins_revision_argument() -> None:
    program, args = _updater_subprocess_command("abc1234")
    assert "python" in program.lower() or program.endswith("python.exe")
    assert args == ["-m", "tools.update_silentfrog", "--revision", "abc1234"]


def test_venv_silentfrog_binary_resolves_per_platform(tmp_path, monkeypatch) -> None:
    """Regression: restart_app used sys.executable + sys.argv to relaunch,
    which on Windows produced ``python.exe <path>\\silentfrog`` (no .exe)
    and bailed with "No such file or directory" right after the in-app
    updater swapped files. Pin the relaunch to the venv's console-script
    binary, resolved per OS.
    """
    import silentfrog.update_gui as ug

    monkeypatch.setattr(ug, "find_repo_root", lambda: tmp_path)
    # Empty repo root: nothing to launch.
    assert ug._venv_silentfrog_binary() is None
    # Lay out a Windows-style venv with the expected binary.
    if os.name == "nt":
        binary = tmp_path / ".venv" / "Scripts" / "silentfrog.exe"
    else:
        binary = tmp_path / ".venv" / "bin" / "silentfrog"
    binary.parent.mkdir(parents=True)
    binary.write_text("# stub")
    assert ug._venv_silentfrog_binary() == binary


def test_apply_click_transitions_to_applying_state_without_subprocess(qtbot, monkeypatch) -> None:
    started: dict[str, tuple[str, list[str]]] = {}

    class FakeProcess:
        MergedChannels = object()

        def __init__(self, _parent) -> None:
            pass

        def setProcessChannelMode(self, _mode) -> None:
            pass

        @property
        def finished(self):
            class _Sig:
                def connect(self, _fn) -> None:
                    pass

            return _Sig()

        @property
        def readyReadStandardOutput(self):
            class _Sig:
                def connect(self, _fn) -> None:
                    pass

            return _Sig()

        def start(self, program: str, args: list[str]) -> None:
            started["call"] = (program, args)

    monkeypatch.setattr("silentfrog.update_gui.QProcess", FakeProcess)
    dlg = _new_dialog(qtbot)
    dlg._apply_state(
        UpdateCheckResult(
            UpdateStatus.UPDATE_AVAILABLE,
            _make_local(),
            _make_remote(sha="cafebabe" + "0" * 32),
        )
    )
    apply_button = next(b for b in dlg._buttons.buttons() if "Apply" in b.text())
    apply_button.click()
    assert "Applying update" in dlg._status_label.text()
    assert started["call"][1] == [
        "-m",
        "tools.update_silentfrog",
        "--revision",
        "cafebabe" + "0" * 32,
    ]


def test_apply_failure_shows_failure_label(qtbot) -> None:
    dlg = _new_dialog(qtbot)
    dlg._on_apply_finished(7, None)
    assert "Update failed" in dlg._status_label.text()
    assert _button_labels(dlg) == ["Close"]
