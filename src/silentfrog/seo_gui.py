from __future__ import annotations
from pathlib import Path
from typing import Any

import sys

from PyQt5 import QtCore, QtGui, QtWidgets

from .tabs import (
    MetaTab,
    HeadersTab,
    ImagesTab,
    LinksTab,
    RedirectTab,
    CanonicalTab,
    RobotsTab,
    HreflangTab,
    AiTab,
    KeywordsTab,
    SchemaTab,
    SerpTab,
)
from .workers import run_crawl, run_image_analysis

import webbrowser
import logging


logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


class WebpageSeoWindow(QtWidgets.QWidget):
    """Main SEO analysis window wiring reusable tabs and async workers."""

    dataReady = QtCore.pyqtSignal(dict)  # payload dei dati
    errorSig = QtCore.pyqtSignal(str)    # messaggio d'errore

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Analisi webpage SEO – Silentfrog")
        self.resize(950, 620)
        icon_path = Path(__file__).with_name("assets").joinpath("icon.png")
        self.setWindowIcon(QtGui.QIcon(str(icon_path)))

        self._build_ui()

        self.dataReady.connect(self._populate_tables)
        self.errorSig.connect(self._show_error)

        self.images_tab.view.doubleClicked.connect(self._open_img_url)
        self.meta_tab.view.doubleClicked.connect(self._open_meta_url)

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        url_bar = QtWidgets.QHBoxLayout()
        self.url_edit = QtWidgets.QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com")
        url_bar.addWidget(self.url_edit, 1)

        self.btn_go = QtWidgets.QPushButton("Analizza")
        self.btn_go.clicked.connect(self._start_analysis)
        url_bar.addWidget(self.btn_go)
        layout.addLayout(url_bar)

        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.meta_tab = MetaTab()
        self.tabs.addTab(self.meta_tab, "Meta tag")

        self.headers_tab = HeadersTab()
        self.tabs.addTab(self.headers_tab, "Header H1-H6")

        self.images_tab = ImagesTab()
        self.tabs.addTab(self.images_tab, "Images")

        self.links_tab = LinksTab()
        self.tabs.addTab(self.links_tab, "Link")

        self.redirect_tab = RedirectTab()
        self.tabs.addTab(self.redirect_tab, "Redirect")

        self.canonical_tab = CanonicalTab()
        self.tabs.addTab(self.canonical_tab, "Canonical")

        self.robots_tab = RobotsTab()
        self.tabs.addTab(self.robots_tab, "Robots")

        self.hreflang_tab = HreflangTab()
        self.tabs.addTab(self.hreflang_tab, "Hreflang")

        self.schema_tab = SchemaTab()
        self.tabs.addTab(self.schema_tab, "Schema.org")

        self.keywords_tab = KeywordsTab()
        self.tabs.addTab(self.keywords_tab, "Keywords")

        self.ai_tab = AiTab()
        self.tabs.addTab(self.ai_tab, "AI crawl")

        self.serp_tab = SerpTab()
        self.tabs.addTab(self.serp_tab, "SERP")

        controls = QtWidgets.QHBoxLayout()
        self.btn_export = QtWidgets.QPushButton("Esporta Excel (TBD)")
        self.btn_export.setEnabled(False)
        controls.addWidget(self.btn_export)

        self.btn_img_dl = QtWidgets.QPushButton("Analizza immagini")
        self.btn_img_dl.setEnabled(False)
        self.btn_img_dl.clicked.connect(self._start_img_analysis)
        controls.addWidget(self.btn_img_dl)

        controls.addStretch()
        layout.addLayout(controls)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setVisible(False)
        layout.addWidget(self.bar)

    def _start_analysis(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            QtWidgets.QMessageBox.warning(self, "URL mancante", "Inserisci un URL.")
            return

        self.btn_go.setEnabled(False)
        self.bar.setRange(0, 0)
        self.bar.setVisible(True)

        run_crawl(
            url,
            timeout=15,
            on_success=lambda data: self.dataReady.emit(data),
            on_error=lambda err: self.errorSig.emit(err),
        )

    def _start_img_analysis(self) -> None:
        rows = self.images_tab.rows()
        if not rows:
            QtWidgets.QMessageBox.information(self, "Niente da fare", "Tabella immagini vuota.")
            return

        run_image_analysis(
            self.url_edit.text(),
            rows,
            timeout=15,
            on_success=lambda result: self.dataReady.emit({"img_update": result}),
            on_error=lambda err: self.errorSig.emit(err),
        )

    def _populate_tables(self, data: dict[str, Any]) -> None:
        if "img_update" in data:
            self.images_tab.update(data["img_update"])
            return

        self.meta_tab.update(data.get("meta", []))
        self.headers_tab.update(data.get("headers", []))
        self.images_tab.update(data.get("images", []))
        self.links_tab.update(data.get("links", []))
        self.redirect_tab.update(data.get("redirect", {}))
        self.canonical_tab.update(data.get("canonical", {}))
        self.robots_tab.update(data.get("meta_robots", ""), data.get("robots", {}))
        self.hreflang_tab.update(data.get("hreflang", []))
        self.keywords_tab.update(data.get("keywords", []))
        self.ai_tab.update(data.get("ai_crawl", []))
        self.schema_tab.update(data.get("schema", []))
        self.serp_tab.update(data.get("serp", {}), data.get("serp_audit", {}))

        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.btn_export.setEnabled(True)
        self.btn_img_dl.setEnabled(True)

    def _open_img_url(self, index: QtCore.QModelIndex) -> None:
        url = index.sibling(index.row(), 0).data()
        if url and isinstance(url, str):
            webbrowser.open(url)

    def _open_meta_url(self, index: QtCore.QModelIndex) -> None:
        name = index.sibling(index.row(), 0).data()
        if name in ("og:image", "og:image:url"):
            url = index.sibling(index.row(), 1).data()
            if url and isinstance(url, str):
                webbrowser.open(url)

    def _reset_ui(self) -> None:
        self.bar.setVisible(False)
        self.btn_go.setEnabled(True)

    def _show_error(self, msg: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Errore", msg)
        self._reset_ui()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = WebpageSeoWindow()
    window.show()
    sys.exit(app.exec())
