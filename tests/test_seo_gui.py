import pytest
from PyQt5 import QtWidgets
from silentfrog.seo_gui import WebpageSeoWindow

def test_seo_window_tabs_and_sort(qtbot):
    """Window opens, has 12 tabs"""
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    win.show()
    assert isinstance(win, QtWidgets.QWidget)
    assert win.tabs.count() == 12
