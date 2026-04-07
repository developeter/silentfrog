from __future__ import annotations

from qtpy import API_NAME, QtWidgets

from silentfrog.gui import HomeWindow
from silentfrog.seo_gui import WebpageSeoWindow


def test_qt_runtime_uses_pyside6_backend(qapp) -> None:
    assert API_NAME == "PySide6"
    assert isinstance(qapp, QtWidgets.QApplication)


def test_gui_entrypoints_instantiate_under_qtpy(qtbot) -> None:
    home = HomeWindow()
    seo = WebpageSeoWindow()
    qtbot.addWidget(home)
    qtbot.addWidget(seo)

    assert home.windowTitle() == "Silentfrog"
    assert seo.windowTitle() == "Silentfrog - SEO webpage analysis"
