from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from typing import Any

import sys
from urllib.parse import urlparse

from PyQt5 import QtCore, QtGui, QtWidgets

from .crawl_types import CrawlPayload
from .crawl_options import CrawlOptions
from .settings_dialog import CrawlSettingsDialog
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
        self.setWindowTitle("Silentfrog - SEO webpage analysis")
        self.resize(950, 620)
        icon_path = Path(__file__).with_name("assets").joinpath("icon.png")
        self.setWindowIcon(QtGui.QIcon(str(icon_path)))
        self._latest_payload: CrawlPayload | None = None
        self._dimmed_buttons: list[QtWidgets.QPushButton] = []
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

        self.btn_go = QtWidgets.QPushButton("Analyze")
        self.btn_go.clicked.connect(self._start_analysis)
        url_bar.addWidget(self.btn_go)
        layout.addLayout(url_bar)

        self.tabs = QtWidgets.QTabWidget()
        self.body_stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.body_stack, 1)
        self._intro_panel = self._build_intro_panel()
        self.body_stack.addWidget(self._intro_panel)

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
        self.body_stack.addWidget(self.tabs)

        controls = QtWidgets.QHBoxLayout()
        self.btn_export = QtWidgets.QPushButton("Export Excel")
        self.btn_export.setEnabled(False)
        self._register_dimmed_button(self.btn_export)
        self.btn_export.clicked.connect(self._export_excel)
        controls.addWidget(self.btn_export)

        self.btn_img_dl = QtWidgets.QPushButton("Analyze images")
        self.btn_img_dl.setEnabled(False)
        self._register_dimmed_button(self.btn_img_dl)
        self.btn_img_dl.clicked.connect(self._start_img_analysis)
        controls.addWidget(self.btn_img_dl)

        self.btn_settings = QtWidgets.QPushButton("Crawl settings...")
        self.btn_settings.setToolTip("Adjust gentle crawl preferences")
        self.btn_settings.clicked.connect(self._open_crawl_settings)
        controls.addWidget(self.btn_settings)

        self.lbl_settings_state = QtWidgets.QLabel("Standard")
        font = self.lbl_settings_state.font()
        font.setPointSizeF(font.pointSizeF() - 1)
        self.lbl_settings_state.setFont(font)
        self.lbl_settings_state.setStyleSheet("color:#6b6b6b;")
        controls.addWidget(self.lbl_settings_state)

        controls.addStretch()
        layout.addLayout(controls)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFormat("%p%")
        self.bar.setAlignment(QtCore.Qt.AlignCenter)
        self.bar.setTextVisible(True)
        self.bar.setVisible(False)
        layout.addWidget(self.bar)
        self._update_settings_label()
        self._show_placeholder()
        self._set_intro_state(False)
        self._update_intro_colors()
        self._refresh_dimmed_buttons()

    def _build_intro_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        wrapper = QtWidgets.QVBoxLayout(panel)
        wrapper.setSpacing(12)
        wrapper.setAlignment(QtCore.Qt.AlignCenter)
        wrapper.addStretch()

        self._intro_default_title = "Ready to crawl a page?"
        self._intro_default_hint = (
            "Enter a URL above and press Analyze to launch the SEO scan.\n"
            "Use Crawl settings to fine-tune the scan before you start."
        )
        self._intro_crawl_hint = "Hang tight while Silentfrog crawls the page."

        self._intro_title = QtWidgets.QLabel(self._intro_default_title)
        self._intro_title.setAlignment(QtCore.Qt.AlignCenter)
        wrapper.addWidget(self._intro_title)

        self._intro_hint = QtWidgets.QLabel(self._intro_default_hint)
        self._intro_hint.setAlignment(QtCore.Qt.AlignCenter)
        self._intro_hint.setWordWrap(True)
        wrapper.addWidget(self._intro_hint)

        wrapper.addStretch()
        return panel

    def _register_dimmed_button(self, button: QtWidgets.QPushButton) -> None:
        self._dimmed_buttons.append(button)
        self._apply_disabled_appearance(button)

    def _apply_disabled_appearance(self, button: QtWidgets.QPushButton) -> None:
        colors = {
            "dark": ("#2b2b2b", "#9fa3ab", "#3a3a3a"),
            "light": ("#dcdcdc", "#6a6a6a", "#b5b5b5"),
        }
        bg, fg, border = colors.get(self._resolve_theme(), colors["light"])
        button.setStyleSheet(
            "QPushButton:disabled {"
            f" background-color: {bg};"
            f" color: {fg};"
            f" border: 1px solid {border};"
            "}"
        )

    def _refresh_dimmed_buttons(self) -> None:
        for button in self._dimmed_buttons:
            self._apply_disabled_appearance(button)

    def _show_placeholder(self) -> None:
        if self.body_stack.currentWidget() is not self._intro_panel:
            self.body_stack.setCurrentWidget(self._intro_panel)

    def _show_results_panel(self) -> None:
        if self.body_stack.currentWidget() is not self.tabs:
            self.body_stack.setCurrentWidget(self.tabs)

    def is_showing_placeholder(self) -> bool:
        return self.body_stack.currentWidget() is self._intro_panel

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        if not url:
            return False
        parsed = urlparse(url.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _set_intro_state(self, crawling: bool) -> None:
        if not hasattr(self, "_intro_title"):
            return
        if crawling:
            self._intro_title.setText("Crawling...")
            self._intro_hint.setText(self._intro_crawl_hint)
        else:
            self._intro_title.setText(self._intro_default_title)
            self._intro_hint.setText(self._intro_default_hint)

    def changeEvent(self, event: QtCore.QEvent) -> None:
        if event.type() == QtCore.QEvent.PaletteChange:
            self._update_intro_colors()
            self._refresh_dimmed_buttons()
        super().changeEvent(event)

    def _start_analysis(self) -> None:
        url = self.url_edit.text().strip()
        if not self._is_valid_url(url):
            QtWidgets.QMessageBox.warning(self, "Missing URL", "Enter a URL to analyze.")
            return
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
            QtWidgets.QMessageBox.information(self, "Nothing to do", "Image table is empty.")
            return

        run_image_analysis(
            self.url_edit.text(),
            rows,
            timeout=15,
            on_success=lambda result: self.dataReady.emit({"img_update": result}),
            on_error=lambda err: self.errorSig.emit(err),
        )

    def _open_crawl_settings(self) -> None:
        """Open the crawl settings dialog (single source of truth for crawl options)."""
        dialog = CrawlSettingsDialog(self._crawl_options, self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self._crawl_options = dialog.options()
            self._update_settings_label()


    def _open_crawl_settings(self) -> None:
        dialog = CrawlSettingsDialog(self._crawl_options, self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self._crawl_options = dialog.options()
            self._update_settings_label()

    def _update_settings_label(self) -> None:
        if self._crawl_options.gentle_mode:
            state = "Gentle crawl"
        elif self._crawl_options.extra_headers:
            state = "Custom crawl"
        else:
            state = "Standard crawl"
        self.lbl_settings_state.setText(state)

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
        self._show_placeholder()
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

    def _set_progress(self, value: int) -> None:
        clamped = max(0, min(100, value))
        if clamped == self._progress_value:
            return
        self._progress_value = clamped
        self.bar.setValue(clamped)


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

    def _show_error(self, msg: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Error", msg)
        self._reset_ui()
        self._set_intro_state(False)

    def _prepare_for_analysis(self) -> None:
        self._clear_results()
        self._latest_payload = None
        self._set_intro_state(True)
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
        self._set_intro_state(False)
        self._show_results_panel()

    def _update_intro_colors(self) -> None:
        if not hasattr(self, "_intro_title"):
            return
        scheme = {
            "dark": ("#f5f5f5", "#cfd2d8"),
            "light": ("#1c1c1c", "#4a4a4a"),
        }
        title_color, hint_color = scheme.get(self._resolve_theme(), scheme["light"])
        self._intro_title.setStyleSheet(
            f"font-size: 18px; font-weight: 600; color: {title_color};"
        )
        self._intro_hint.setStyleSheet(
            f"color: {hint_color}; max-width: 460px;"
        )

    def _resolve_theme(self) -> str:
        app = QtWidgets.QApplication.instance()
        stored = app.property("silentfrog_theme") if app else None
        if stored in ("dark", "light"):
            return stored
        window_color = self.palette().color(QtGui.QPalette.Window)
        return "dark" if window_color.lightness() < 128 else "light"

    def _export_excel(self) -> None:
        if not self._latest_payload:
            QtWidgets.QMessageBox.information(
                self,
                "No data",
                "Run an analysis before exporting results.",
            )
            return

        suggested = Path.home() / "silentfrog_report.xlsx"
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export report",
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
                "Export failed",
                f"Unable to export the report.\nDetails: {exc}",
            )
        else:
            QtWidgets.QMessageBox.information(
                self,
                "Export completed",
                "Report exported successfully.",
            )
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = WebpageSeoWindow()
    window.show()
    sys.exit(app.exec())

