from __future__ import annotations

from qtpy import QtWidgets

from silentfrog.gui import HomeWindow, _SettingsDialog  # type: ignore[reportMissingImports]


def test_home_window_exposes_four_primary_actions(qtbot) -> None:
    win = HomeWindow()
    qtbot.addWidget(win)

    labels = [button.text() for button in win.findChildren(QtWidgets.QPushButton)]

    # Exact set + count: a future action added/removed must fail this named
    # test instead of silently drifting from docs/site_crawl_feature_spec.md's
    # "Home screen has four actions" UX Contract line the way the stale
    # "...three_primary_actions" name previously masked.
    assert labels.count("Massive Redirect Check") == 1
    assert labels.count("Single Page SEO Check") == 1
    assert labels.count("Site Crawl") == 1
    assert labels.count("Server Log Analysis") == 1
    assert len(labels) == 4


def test_home_window_can_open_multiple_seo_windows_without_dropping_refs(
    qtbot,
) -> None:
    """Regression: clicking 'Single Page SEO Check' twice used to drop
    the Python reference to the first window (overwritten by the
    second), which segfaults PySide6 while the first window is still
    visible. Both windows must now be retained.
    """
    win = HomeWindow()
    qtbot.addWidget(win)
    win.open_seo()
    win.open_seo()
    win.open_site_crawl()
    win.open_redirect()
    assert len(win._child_windows) == 4
    # Every retained child must still be a live QWidget instance.
    for child in win._child_windows:
        assert isinstance(child, QtWidgets.QWidget)
        assert child.isVisible() or not child.isHidden()  # show() was called


def test_home_window_logo_label_holds_pixmap_size(qtbot) -> None:
    """Regression: when the user toggled the theme via the gear dialog,
    a stylesheet repolish was shrinking the QLabel below its pixmap
    height on macOS, clipping the frog. Pinning the label's minimum
    size to the pixmap size prevents that.
    """
    win = HomeWindow()
    qtbot.addWidget(win)
    labels = [
        label
        for label in win.findChildren(QtWidgets.QLabel)
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
