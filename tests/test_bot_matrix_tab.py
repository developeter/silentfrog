"""Smoke tests for the v1.1 N5a Bot Matrix tab.

Focused on the model + view wiring; the drill-down dialog is
exercised by spawning it directly so we don't need a click-driver.
"""

from __future__ import annotations

import pytest
from qtpy import QtCore

from silentfrog.models import BotMatrixModel
from silentfrog.tabs import BotMatrixTab

# Sample rows mirroring the parsers_meta._ai_crawl_matrix shape:
# [label, token, robots_ok, ai_directive, search_controls, verdict, notes]
_SAMPLE_ROWS = [
    ["GPTBot", "gptbot", "Yes", "-", "-", "Allowed", "No explicit AI restrictions detected"],
    [
        "Googlebot",
        "googlebot",
        "Yes",
        "-",
        "nosnippet",
        "Limited",
        "Google search controls: nosnippet",
    ],
    ["ClaudeBot", "claudebot", "No", "noai", "-", "Blocked", "Blocked by robots.txt: /private"],
]


def test_bot_matrix_model_returns_status_brush_for_verdict_column(qtbot) -> None:
    model = BotMatrixModel(
        ["Agent", "Token", "Robots.txt OK", "Nonstandard directive", "Google controls", "Verdict", "Notes"],
        _SAMPLE_ROWS,
    )
    allowed_idx = model.index(0, 5)
    limited_idx = model.index(1, 5)
    blocked_idx = model.index(2, 5)
    allowed_brush = model.data(allowed_idx, QtCore.Qt.ItemDataRole.BackgroundRole)
    limited_brush = model.data(limited_idx, QtCore.Qt.ItemDataRole.BackgroundRole)
    blocked_brush = model.data(blocked_idx, QtCore.Qt.ItemDataRole.BackgroundRole)
    # All three brushes must be distinct (different status colors).
    assert allowed_brush is not None
    assert limited_brush is not None
    assert blocked_brush is not None
    assert allowed_brush != limited_brush != blocked_brush != allowed_brush


def test_bot_matrix_model_only_colors_verdict_column(qtbot) -> None:
    model = BotMatrixModel(
        ["Agent", "Token", "Robots.txt OK", "Nonstandard directive", "Google controls", "Verdict", "Notes"],
        _SAMPLE_ROWS,
    )
    # Agent column (0) must NOT be coloured.
    assert model.data(model.index(0, 0), QtCore.Qt.ItemDataRole.BackgroundRole) is None


def test_bot_matrix_model_tooltip_returns_notes_column_text(qtbot) -> None:
    model = BotMatrixModel(
        ["Agent", "Token", "Robots.txt OK", "Nonstandard directive", "Google controls", "Verdict", "Notes"],
        _SAMPLE_ROWS,
    )
    tip = model.data(model.index(0, 0), QtCore.Qt.ItemDataRole.ToolTipRole)
    assert tip == "No explicit AI restrictions detected"


def test_bot_matrix_tab_updates_summary_with_verdict_counts(qtbot) -> None:
    tab = BotMatrixTab()
    qtbot.addWidget(tab)
    tab.update(_SAMPLE_ROWS)
    summary = tab._summary.text()
    assert "Allowed 1" in summary
    assert "Limited 1" in summary
    assert "Blocked 1" in summary


def test_bot_matrix_tab_empty_payload_is_safe(qtbot) -> None:
    tab = BotMatrixTab()
    qtbot.addWidget(tab)
    tab.update([])
    # Should not raise; summary still shows the counts as zero.
    assert "Allowed 0" in tab._summary.text()


@pytest.mark.qt_no_exception_capture
def test_bot_matrix_tab_double_click_opens_dialog_with_per_bot_data(qtbot, monkeypatch) -> None:
    captured: dict[str, str] = {}

    # Don't actually block in exec(); record that it was called.
    def _stub_exec(self) -> int:
        captured["title"] = self.windowTitle()
        return 0

    monkeypatch.setattr("qtpy.QtWidgets.QDialog.exec", _stub_exec)

    tab = BotMatrixTab()
    qtbot.addWidget(tab)
    tab.update(_SAMPLE_ROWS)
    model = tab.view.model()
    assert model is not None
    tab._on_row_activated(model.index(1, 0))
    assert "Googlebot" in captured["title"]
