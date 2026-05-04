from __future__ import annotations

from qtpy import API_NAME, QtWidgets

from silentfrog.gui import HomeWindow
from silentfrog.seo_gui import WebpageSeoWindow
from silentfrog.site_crawl_gui import SiteCrawlWindow


def test_qt_runtime_uses_pyside6_backend(qapp) -> None:
    assert API_NAME == "PySide6"
    assert isinstance(qapp, QtWidgets.QApplication)


def test_gui_entrypoints_instantiate_under_qtpy(qtbot) -> None:
    home = HomeWindow()
    seo = WebpageSeoWindow()
    site_crawl = SiteCrawlWindow()
    qtbot.addWidget(home)
    qtbot.addWidget(seo)
    qtbot.addWidget(site_crawl)

    assert home.windowTitle() == "Silentfrog"
    assert seo.windowTitle() == "Silentfrog - Single Page SEO Check"
    assert site_crawl.windowTitle() == "Silentfrog - Site Crawl"
