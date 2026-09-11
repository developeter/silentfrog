from __future__ import annotations

import threading

import pytest
from qtpy import QtCore, QtWidgets

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


def _close_and_destroy_mid_crawl(qtbot, hook_calls: list) -> None:
    """One race iteration: park a fake crawl worker on an Event, close the Site
    Crawl window so WA_DeleteOnClose really destroys it, then release the
    worker so its three callbacks fire at a window that no longer exists.

    This is the exact shape workers.run_site_crawl uses -- three closures over
    the per-crawl _CrawlSignalBridge -- so it exercises the real failure mode:
    before the bridge, those callbacks emitted the window's own signals and
    raised RuntimeError("Signal source has been deleted") in the worker thread
    (measured 30/30 on this build with the bridge parented to the window).
    """
    shiboken = pytest.importorskip("shiboken6")
    win = HomeWindow()
    qtbot.addWidget(win)
    win.open_site_crawl()
    crawl_window = win._child_windows[0]
    crawl_window._crawl_active = True
    crawl_window._active_cancel = threading.Event()
    bridge = crawl_window._attach_crawl_bridge()

    released = threading.Event()

    def worker_callbacks() -> None:
        released.wait(10)
        # No try/except on purpose: anything raised here escapes the thread
        # and lands in the threading.excepthook spy the caller installed.
        bridge.progress.emit({"event": "row", "completed": 1})
        bridge.report.emit(object())
        bridge.error.emit("boom")

    thread = threading.Thread(target=worker_callbacks)
    thread.start()
    try:
        crawl_window.close()
        qtbot.waitUntil(lambda: len(win._child_windows) == 0, timeout=2000)
        # Destroyed for real: Qt fired ``destroyed`` (above) AND shiboken
        # reports the C++ object gone, so the emits below are genuinely late.
        assert not shiboken.isValid(crawl_window)
        assert crawl_window._active_cancel.is_set()  # closeEvent still cancelled
    finally:
        released.set()
        thread.join(10)
    assert not thread.is_alive()
    QtWidgets.QApplication.processEvents()
    assert win._child_windows == []
    assert hook_calls == []


def test_late_crawl_callbacks_on_a_destroyed_window_never_raise(qtbot, monkeypatch) -> None:
    """Regression: a Site Crawl window is destroyed on close (WA_DeleteOnClose,
    _spawn_child) while workers.run_site_crawl's daemon thread is still alive.
    Its callbacks must reach a signal source that outlives the window -- the
    parentless _CrawlSignalBridge -- so a late emit finds no receivers instead
    of raising. This used to raise in the worker thread and was masked by a
    process-wide threading.excepthook; there is no filter now, so the hook spy
    below must stay empty.

    Looped because the outcome was timing-dependent: an emit strictly after
    destruction raised RuntimeError("Signal source has been deleted"), while
    one landing at the instant of destruction raised TypeError(" only accepts
    0 argument(s)"). Neither is reachable once the source is not the window.
    """
    hook_calls: list[threading.ExceptHookArgs] = []
    monkeypatch.setattr(threading, "excepthook", hook_calls.append)

    for _ in range(30):
        _close_and_destroy_mid_crawl(qtbot, hook_calls)


def test_redirect_and_seo_windows_are_not_destroyed_on_close(qtbot) -> None:
    """Only Site Crawl and Log Analysis detach their background worker's
    cross-thread signals before close (SiteCrawlWindow.closeEvent /
    LogWindow._detach_worker). Redirect Check only blocks close on
    worker.wait(5000) without detaching if that wait times out, and Webpage
    SEO has no closeEvent at all -- neither is proven safe to actually
    destroy on close, so _spawn_child must leave WA_DeleteOnClose off for
    both."""
    win = HomeWindow()
    qtbot.addWidget(win)
    win.open_redirect()
    win.open_seo()

    for child in win._child_windows:
        assert not child.testAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
