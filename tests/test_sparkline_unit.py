"""Smoke tests for the v1.1 N5c Sparkline + AiVisibilityTab integration."""

from __future__ import annotations

from silentfrog.sparkline import Sparkline
from silentfrog.tabs import AiVisibilityTab


def test_sparkline_starts_empty(qtbot) -> None:
    sl = Sparkline()
    qtbot.addWidget(sl)
    assert sl.values() == []


def test_sparkline_set_values_roundtrips(qtbot) -> None:
    sl = Sparkline()
    qtbot.addWidget(sl)
    sl.set_values([90, 88, 85, 92])
    assert sl.values() == [90, 88, 85, 92]


def test_sparkline_coerces_floats(qtbot) -> None:
    sl = Sparkline()
    qtbot.addWidget(sl)
    sl.set_values([90.4, 88.7])  # type: ignore[list-item]
    assert sl.values() == [90, 88]


def test_sparkline_paints_without_crash_on_empty(qtbot) -> None:
    """The paintEvent must handle the empty-series branch."""
    sl = Sparkline()
    qtbot.addWidget(sl)
    sl.show()
    sl.repaint()


def test_sparkline_paints_with_single_value(qtbot) -> None:
    sl = Sparkline()
    qtbot.addWidget(sl)
    sl.set_values([75])
    sl.show()
    sl.repaint()


def test_sparkline_paints_with_full_series(qtbot) -> None:
    sl = Sparkline()
    qtbot.addWidget(sl)
    sl.set_values([90, 88, 85, 92, 91, 78, 82])
    sl.show()
    sl.repaint()


def test_ai_visibility_tab_exposes_score_history_setter(qtbot) -> None:
    tab = AiVisibilityTab()
    qtbot.addWidget(tab)
    tab.set_score_history([90, 88, 85])
    assert tab._score_history.values() == [90, 88, 85]
