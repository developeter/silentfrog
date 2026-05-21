from __future__ import annotations

from qtpy import QtWidgets

from silentfrog.gui import HomeWindow, _SettingsDialog  # type: ignore[reportMissingImports]


def test_home_window_exposes_three_primary_actions(qtbot) -> None:
    win = HomeWindow()
    qtbot.addWidget(win)

    labels = [button.text() for button in win.findChildren(QtWidgets.QPushButton)]

    assert "Massive Redirect Check" in labels
    assert "Single Page SEO Check" in labels
    assert "Site Crawl" in labels


def test_home_window_logo_label_holds_pixmap_size(qtbot) -> None:
    """Regression: when the user toggled the theme via the gear dialog,
    a stylesheet repolish was shrinking the QLabel below its pixmap
    height on macOS, clipping the frog. Pinning the label's minimum
    size to the pixmap size prevents that.
    """
    win = HomeWindow()
    qtbot.addWidget(win)
    labels = [
        label for label in win.findChildren(QtWidgets.QLabel)
        if label.pixmap() is not None and not label.pixmap().isNull()
    ]
    assert labels, "expected at least one QLabel holding the frog pixmap"
    logo = labels[0]
    pix = logo.pixmap()
    assert logo.minimumSize().height() >= pix.height()
    assert logo.minimumSize().width() >= pix.width()


def test_settings_dialog_radio_indicator_is_styled_for_visibility(qtbot) -> None:
    """Regression: dark-theme `QRadioButton::indicator` was using the
    Qt default, which rendered the checked state as a near-invisible
    dot on Windows. The dark stylesheet now styles the indicator
    explicitly.
    """
    from silentfrog.theme import DARK_STYLESHEET, LIGHT_STYLESHEET

    for sheet in (DARK_STYLESHEET, LIGHT_STYLESHEET):
        assert "QRadioButton::indicator" in sheet
        assert "QRadioButton::indicator:checked" in sheet
        assert "QRadioButton::indicator:unchecked" in sheet

    # Smoke: the dialog still constructs and exposes the two radios.
    win = HomeWindow()
    qtbot.addWidget(win)
    dlg = _SettingsDialog(win)
    qtbot.addWidget(dlg)
    assert dlg.dark_radio.text() == "Dark theme"
    assert dlg.light_radio.text() == "Light theme"
