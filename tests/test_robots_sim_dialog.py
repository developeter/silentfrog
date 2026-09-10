"""v2.0 R1 (V16) — robots.txt simulator dialog.

RobotsSimDialog is a pure view over the already-tested
``robots_simulator.simulate_robots()``; this test only checks that the
dialog wires the three inputs (body, URL, user-agent) into a rendered
verdict, not the matching logic itself (covered by
tests/test_robots_simulator_unit.py).
"""

from __future__ import annotations

from qtpy import QtCore

from silentfrog import robots_sim_dialog
from silentfrog.robots_sim_dialog import RobotsSimDialog

_BLOCKED_ROBOTS_BODY = "User-agent: *\nDisallow: /private\n"


def test_robots_sim_dialog_renders_verdict_for_known_blocked_path(qtbot) -> None:
    dialog = RobotsSimDialog()
    qtbot.addWidget(dialog)

    dialog.txt_robots_body.setPlainText(_BLOCKED_ROBOTS_BODY)
    dialog.edit_target_url.setText("https://example.com/private/page")
    dialog.edit_user_agent.setText("SilentFrog/1.0 (+https://example.com)")
    qtbot.mouseClick(dialog.btn_check, QtCore.Qt.MouseButton.LeftButton)

    assert dialog.lbl_verdict.text() == "✗ Blocked"
    assert "/private" in dialog.lbl_rule.text()
    assert dialog.lbl_reason.text() != "—"


def test_closing_dialog_detaches_an_in_flight_fetch(qtbot, monkeypatch) -> None:
    """A QThread deleted while running aborts the process, so closing the
    modal mid-fetch must detach the worker instead of dropping it."""
    started: list[str] = []
    monkeypatch.setattr(robots_sim_dialog._RobotsFetchWorker, "start", lambda self: started.append(self._robots_url))
    dialog = RobotsSimDialog()
    qtbot.addWidget(dialog)
    dialog.edit_target_url.setText("https://example.com/private/page")

    qtbot.mouseClick(dialog.btn_fetch, QtCore.Qt.MouseButton.LeftButton)
    assert started == ["https://example.com/robots.txt"]
    worker = dialog._fetch_worker
    assert worker is not None
    assert worker in robots_sim_dialog._LIVE_FETCH_WORKERS
    assert worker.parent() is None

    dialog.reject()

    assert dialog._fetch_worker is None
    worker.finished_fetch.emit("User-agent: *\nDisallow: /\n")
    assert dialog.txt_robots_body.toPlainText() == ""
