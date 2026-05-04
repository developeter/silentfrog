from __future__ import annotations

from qtpy import QtWidgets

from silentfrog.gui import HomeWindow  # type: ignore[reportMissingImports]


def test_home_window_exposes_three_primary_actions(qtbot) -> None:
    win = HomeWindow()
    qtbot.addWidget(win)

    labels = [button.text() for button in win.findChildren(QtWidgets.QPushButton)]

    assert "Massive Redirect Check" in labels
    assert "Single Page SEO Check" in labels
    assert "Site Crawl" in labels
