from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from typing import Any

import sys

from PyQt5 import QtCore, QtGui, QtWidgets

from .crawl_types import CrawlPayload
from .crawl_options import CrawlOptions, parse_header_lines
from .exporters import export_page_analysis
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
    PerformanceTab,
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
        self.setWindowTitle("Analisi webpage SEO - Silentfrog")
        self.resize(950, 620)
        icon_path = Path(__file__).with_name("assets").joinpath("icon.png")
        self.setWindowIcon(QtGui.QIcon(str(icon_path)))
        self._latest_payload: CrawlPayload | None = None
        self._crawl_options: CrawlOptions = CrawlOptions.default()

        self._build_ui()
        self._progress_value = 0
        self._progress_limit = 100
        self._progress_timer: QtCore.QTimer | None = None

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
        self.tabs.addTab(self.schema_tab, "Structured data")

        self.keywords_tab = KeywordsTab()
        self.tabs.addTab(self.keywords_tab, "Keywords")

        self.ai_tab = AiTab()
        self.performance_tab = PerformanceTab()
        self.tabs.addTab(self.ai_tab, "AI crawl")
        self.tabs.addTab(self.performance_tab, "Performance")

        self.serp_tab = SerpTab()
        self.tabs.addTab(self.serp_tab, "SERP")

        controls = QtWidgets.QHBoxLayout()
        self.btn_export = QtWidgets.QPushButton("Esporta Excel")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export_excel)
        controls.addWidget(self.btn_export)

        self.btn_img_dl = QtWidgets.QPushButton("Analizza immagini")
        self.btn_img_dl.setEnabled(False)
        self.btn_img_dl.clicked.connect(self._start_img_analysis)
        controls.addWidget(self.btn_img_dl)

        controls.addStretch()
        layout.addLayout(controls)

        settings = QtWidgets.QHBoxLayout()
        self.chk_gentle = QtWidgets.QCheckBox("Gentle crawl mode")
        self.chk_gentle.setChecked(False)
        settings.addWidget(self.chk_gentle)
        settings.addSpacing(8)

        settings.addWidget(QtWidgets.QLabel("Max parallel requests"))
        self.spin_parallel = QtWidgets.QSpinBox()
        self.spin_parallel.setRange(1, 8)
        self.spin_parallel.setValue(2)
        self.spin_parallel.setEnabled(False)
        settings.addWidget(self.spin_parallel)
        settings.addStretch()
        layout.addLayout(settings)

        self.advanced_group = QtWidgets.QGroupBox("Advanced headers")
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)
        advanced_layout = QtWidgets.QVBoxLayout(self.advanced_group)
        self.headers_label = QtWidgets.QLabel("Custom headers (Key: Value per line)")
        advanced_layout.addWidget(self.headers_label)
        self.txt_headers = QtWidgets.QPlainTextEdit()
        self.txt_headers.setPlaceholderText("Authorization: Bearer ...")
        self.txt_headers.setEnabled(False)
        self.txt_headers.setFixedHeight(80)
        advanced_layout.addWidget(self.txt_headers)
        cookie_label = QtWidgets.QLabel("Cookies (e.g. session=abc; theme=dark)")
        advanced_layout.addWidget(cookie_label)
        self.edit_cookies = QtWidgets.QLineEdit()
        self.edit_cookies.setEnabled(False)
        advanced_layout.addWidget(self.edit_cookies)
        layout.addWidget(self.advanced_group)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFormat("%p%")
        self.bar.setVisible(False)
        layout.addWidget(self.bar)

        self.chk_gentle.toggled.connect(self._on_gentle_mode_toggled)
        self.spin_parallel.valueChanged.connect(self._on_parallel_changed)
        self.advanced_group.toggled.connect(self._on_advanced_toggled)
        self.txt_headers.textChanged.connect(self._on_header_inputs_changed)
        self.edit_cookies.textChanged.connect(self._on_header_inputs_changed)
        self._refresh_crawl_options()

    def _start_analysis(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            QtWidgets.QMessageBox.warning(self, "URL mancante", "Inserisci un URL.")
            return
        self._refresh_crawl_options()
        self._prepare_for_analysis()

        run_crawl(
            url,
            timeout=15,
            on_success=lambda data: self.dataReady.emit(data),
            on_error=lambda err: self.errorSig.emit(err),
            options=self._crawl_options,
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
        if self._handle_image_update(data):
            return

        self._stop_progress_drift()
        self._set_progress(max(self._progress_value, 65))
        self._latest_payload = self._load_payload(data)
        self._set_progress(max(self._progress_value, 70))

        meta_rows = data.get("meta", [])
        self.meta_tab.update(meta_rows)
        self.headers_tab.update(data.get("headers", []), self._title_from_meta(meta_rows))
        self._set_progress(max(self._progress_value, 75))
        self._update_content_tabs(data, span=(75, 95))
        self._finalise_population()

    def _clear_results(self) -> None:
        self.meta_tab.clear()
        self.headers_tab.update([], None)
        self.images_tab.update([])
        self.links_tab.update([])
        self.redirect_tab.update({})
        self.canonical_tab.update({})
        self.robots_tab.update("", {})
        self.hreflang_tab.update([])
        self.keywords_tab.update([])
        self.ai_tab.update([])
        self.performance_tab.update({})
        self.schema_tab.update({})
        self.serp_tab.update({}, {})
        self.btn_export.setEnabled(False)
        self.btn_img_dl.setEnabled(False)

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

    def _on_gentle_mode_toggled(self, checked: bool) -> None:
        self.spin_parallel.setEnabled(checked)
        self._refresh_crawl_options()

    def _on_parallel_changed(self, _: int) -> None:
        if self.spin_parallel.isEnabled():
            self._refresh_crawl_options()

    def _on_advanced_toggled(self, checked: bool) -> None:
        self.txt_headers.setEnabled(checked)
        self.edit_cookies.setEnabled(checked)
        self._refresh_crawl_options()

    def _on_header_inputs_changed(self) -> None:
        if self.advanced_group.isChecked():
            self._refresh_crawl_options()

    def _set_progress(self, value: int) -> None:
        clamped = max(0, min(100, value))
        if clamped == self._progress_value:
            return
        self._progress_value = clamped
        self.bar.setValue(clamped)

    def _refresh_crawl_options(self) -> None:
        header_text = self.txt_headers.toPlainText() if self.advanced_group.isChecked() else ""
        headers_map, invalid = parse_header_lines(header_text)
        self._update_header_warning(invalid)
        header_text = header_text if self.advanced_group.isChecked() else ""
        cookie_text = self.edit_cookies.text() if self.advanced_group.isChecked() else ""
        self._crawl_options = CrawlOptions.from_ui(
            gentle_mode=self.chk_gentle.isChecked(),
            max_parallel=self.spin_parallel.value(),
            header_text=header_text,
            cookie_text=cookie_text,
        )

    def _update_header_warning(self, invalid: bool) -> None:
        color = "#d32f2f" if invalid else ""
        self.headers_label.setStyleSheet(f"color:{color};" if color else "")

    def _start_progress_drift(self, limit: int = 80) -> None:
        self._progress_limit = max(0, min(100, limit))
        if self._progress_timer is None:
            timer = QtCore.QTimer(self)
            timer.setInterval(160)
            timer.timeout.connect(self._tick_progress)
            self._progress_timer = timer
        self._progress_timer.start()

    def _stop_progress_drift(self) -> None:
        self._progress_limit = 100
        if self._progress_timer:
            self._progress_timer.stop()

    def _tick_progress(self) -> None:
        next_value = min(self._progress_limit, self._progress_value + 1)
        self._set_progress(next_value)
        if next_value >= self._progress_limit and self._progress_timer:
            self._progress_timer.stop()

    def _reset_ui(self) -> None:
        self._stop_progress_drift()
        self.bar.setVisible(False)
        self.btn_go.setEnabled(True)

    def _show_error(self, msg: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Errore", msg)
        self._reset_ui()

    def _prepare_for_analysis(self) -> None:
        self._clear_results()
        self._latest_payload = None
        self.btn_go.setEnabled(False)
        self.bar.setRange(0, 100)
        self._set_progress(5)
        self._start_progress_drift(60)
        self.bar.setVisible(True)
        self.btn_export.setEnabled(False)

    def _handle_image_update(self, data: dict[str, Any]) -> bool:
        update = data.get("img_update")
        if not update:
            return False
        self.images_tab.update(update)
        if self._latest_payload:
            self._latest_payload = replace(self._latest_payload, images=self.images_tab.rows())
        return True

    def _load_payload(self, data: dict[str, Any]) -> CrawlPayload | None:
        try:
            return CrawlPayload.from_raw(data)
        except ValueError as exc:
            log.warning("Unable to parse crawl payload: %s", exc)
            return None

    @staticmethod
    def _title_from_meta(meta_rows: list[list[str]]) -> str:
        for row in meta_rows:
            name = (row[0] or "").lower() if row else ""
            if name == "title" and len(row) > 1:
                return row[1]
        return ""

    def _update_content_tabs(self, data: dict[str, Any], span: tuple[int, int]) -> None:
        list_tabs = [
            (self.images_tab.update, data.get("images", [])),
            (self.links_tab.update, data.get("links", [])),
            (self.hreflang_tab.update, data.get("hreflang", [])),
            (self.keywords_tab.update, data.get("keywords", [])),
            (self.ai_tab.update, data.get("ai_crawl", [])),
            (self.performance_tab.update, data.get("performance", {})),
            (self.schema_tab.update, data.get("schema", {})),
        ]
        start, end = span
        steps = len(list_tabs) or 1
        increment = 0 if steps == 0 else (end - start) / steps
        progress_value = float(start)
        for updater, payload in list_tabs:
            updater(payload)
            progress_value += increment
            self._set_progress(int(progress_value))
        self.redirect_tab.update(data.get("redirect", {}))
        self.canonical_tab.update(data.get("canonical", {}))
        self.robots_tab.update(data.get("meta_robots", ""), data.get("robots", {}))
        self.serp_tab.update(data.get("serp", {}), data.get("serp_audit", {}))
        self._set_progress(end)

    def _finalise_population(self) -> None:
        self._stop_progress_drift()
        self._set_progress(100)
        self.btn_export.setEnabled(self._latest_payload is not None)
        self.btn_img_dl.setEnabled(True)
        self._reset_ui()

    def _export_excel(self) -> None:
        if not self._latest_payload:
            QtWidgets.QMessageBox.information(
                self,
                "Nessun dato",
                "Esegui prima un'analisi per esportare i risultati.",
            )
            return

        suggested = Path.home() / "silentfrog_report.xlsx"
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Esporta report",
            str(suggested),
            "Excel files (*.xlsx)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".xlsx"):
            file_path = f"{file_path}.xlsx"

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            export_page_analysis(self._latest_payload, Path(file_path))
        except Exception as exc:  # noqa: BLE001
            log.exception("Failed to export Excel")
            QtWidgets.QMessageBox.critical(
                self,
                "Esportazione fallita",
                f"Impossibile esportare il report.\nDettagli: {exc}",
            )
        else:
            QtWidgets.QMessageBox.information(
                self,
                "Esportazione completata",
                "Report esportato correttamente.",
            )
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = WebpageSeoWindow()
    window.show()
    sys.exit(app.exec())

