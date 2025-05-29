import pytest
from PyQt5 import QtWidgets
from silentfrog.seo_gui import WebpageSeoWindow

def test_seo_window_tabs(qtbot):
    """La finestra si apre e contiene 6 schede."""
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    win.show()
    assert isinstance(win, QtWidgets.QWidget)
    assert win.tabs.count() == 6                # Meta, Header, Immagini, Link, Schema, Keywords
