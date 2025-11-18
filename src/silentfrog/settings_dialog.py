from __future__ import annotations

import sys
import ctypes
from ctypes import wintypes

from typing import Any

from PyQt5 import QtCore, QtGui, QtWidgets

from .crawl_options import CrawlOptions, parse_header_lines


class CrawlSettingsDialog(QtWidgets.QDialog):
    """Lightweight dialog that groups gentle crawl controls away from the main window."""

    def __init__(self, options: CrawlOptions, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Crawl settings")
        self.resize(420, 320)
        help_flag = getattr(QtCore.Qt, "WindowContextHelpButtonHint", QtCore.Qt.WindowType(0))
        self.setWindowFlag(help_flag, True)

        layout = QtWidgets.QVBoxLayout(self)

        general_box = QtWidgets.QGroupBox("General behaviour")
        general_layout = QtWidgets.QFormLayout(general_box)
        self.chk_gentle = QtWidgets.QCheckBox("Enable gentle crawl mode")
        self.chk_gentle.setChecked(options.gentle_mode)
        general_layout.addRow(self.chk_gentle)

        self.spin_parallel = QtWidgets.QSpinBox()
        self.spin_parallel.setRange(1, 8)
        self.spin_parallel.setValue(options.max_concurrent_per_host or 2)
        general_layout.addRow("Max parallel requests", self.spin_parallel)

        presets_widget = QtWidgets.QWidget()
        presets_layout = QtWidgets.QHBoxLayout(presets_widget)
        presets_layout.setContentsMargins(0, 0, 0, 0)
        self.preset_group = QtWidgets.QButtonGroup(self)
        self.btn_preset_standard = QtWidgets.QRadioButton("Standard")
        self.btn_preset_gentle = QtWidgets.QRadioButton("Gentle")
        self.btn_preset_custom = QtWidgets.QRadioButton("Custom")
        for btn in (self.btn_preset_standard, self.btn_preset_gentle, self.btn_preset_custom):
            self.preset_group.addButton(btn)
            presets_layout.addWidget(btn)
        general_layout.addRow("Presets", presets_widget)
        layout.addWidget(general_box)

        self.adv_group = QtWidgets.QGroupBox("Advanced headers")
        self.adv_group.setCheckable(True)
        layout.addWidget(self.adv_group)
        adv_layout = QtWidgets.QVBoxLayout(self.adv_group)
        self.headers_label = QtWidgets.QLabel("Custom headers (Key: Value per line)")
        adv_layout.addWidget(self.headers_label)

        self.txt_headers = QtWidgets.QPlainTextEdit()
        self.txt_headers.setPlaceholderText("Authorization: Bearer …")
        self.txt_headers.setFixedHeight(80)
        adv_layout.addWidget(self.txt_headers)

        adv_layout.addWidget(QtWidgets.QLabel("Cookies"))
        self.edit_cookies = QtWidgets.QLineEdit()
        self.edit_cookies.setPlaceholderText("session=abc; theme=dark")
        adv_layout.addWidget(self.edit_cookies)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.chk_gentle.toggled.connect(self._on_gentle_toggled)
        self.spin_parallel.valueChanged.connect(self._mark_custom)
        self.adv_group.toggled.connect(self._mark_custom)
        self.adv_group.toggled.connect(self._sync_state)
        self.txt_headers.textChanged.connect(self._on_header_text_changed)
        self.edit_cookies.textChanged.connect(self._mark_custom)
        self.btn_preset_standard.toggled.connect(lambda checked: checked and self._apply_preset("standard"))
        self.btn_preset_gentle.toggled.connect(lambda checked: checked and self._apply_preset("gentle"))
        self.btn_preset_custom.toggled.connect(lambda checked: checked and self._sync_state())

        self._applying_preset = False
        self._load_from_options(options)
        self._sync_state()

    def _load_from_options(self, options: CrawlOptions) -> bool:
        headers_lines = [
            f"{key}: {value}"
            for key, value in options.extra_headers.items()
            if key.lower() != "cookie"
        ]
        headers_text = "\n".join(headers_lines)
        cookie_text = options.extra_headers.get("Cookie", "")
        advanced_on = bool(headers_text or cookie_text)

        self.adv_group.setChecked(advanced_on)
        self.txt_headers.setPlainText(headers_text)
        self.edit_cookies.setText(cookie_text)
        self._select_initial_preset(options, advanced_on)
        self._validate_headers()
        return advanced_on

    def _sync_state(self) -> None:
        is_gentle = self.chk_gentle.isChecked()
        self.spin_parallel.setEnabled(is_gentle)
        self.txt_headers.setEnabled(self.adv_group.isChecked())
        self.edit_cookies.setEnabled(self.adv_group.isChecked())

    def _on_gentle_toggled(self, checked: bool) -> None:
        if self._applying_preset:
            return
        if not checked:
            self._apply_preset("standard")
        self._sync_state()

    def _mark_custom(self) -> None:
        if self._applying_preset:
            return
        self.btn_preset_custom.setChecked(True)
        self._sync_state()

    def _on_header_text_changed(self) -> None:
        self._mark_custom()
        self._validate_headers()

    def _validate_headers(self) -> None:
        styles = {"invalid": "color:#d32f2f;", "valid": "color:#2e7d32;", "empty": ""}
        if not self.adv_group.isChecked():
            self.headers_label.setStyleSheet(styles["empty"])
            return
        _, invalid = parse_header_lines(self.txt_headers.toPlainText())
        state = "invalid" if invalid else "valid" if self.txt_headers.toPlainText().strip() else "empty"
        self.headers_label.setStyleSheet(styles[state])

    def options(self) -> CrawlOptions:
        header_text = self.txt_headers.toPlainText() if self.adv_group.isChecked() else ""
        cookie_text = self.edit_cookies.text() if self.adv_group.isChecked() else ""
        return CrawlOptions.from_ui(
            gentle_mode=self.chk_gentle.isChecked(),
            max_parallel=self.spin_parallel.value(),
            header_text=header_text,
            cookie_text=cookie_text,
        )

    def _apply_preset(self, preset: str) -> None:
        if self._applying_preset:
            return
        presets = {
            "standard": {"gentle": False, "parallel": 4},
            "gentle": {"gentle": True, "parallel": 2},
            "custom": None,
        }
        config = presets.get(preset)
        self._applying_preset = True
        if config is None:
            self.btn_preset_custom.setChecked(True)
        else:
            self.chk_gentle.setChecked(config["gentle"])
            self.spin_parallel.setValue(config["parallel"])
            self.adv_group.setChecked(False)
            self.btn_preset_standard.setChecked(preset == "standard")
            self.btn_preset_gentle.setChecked(preset == "gentle")
        self._applying_preset = False
        self._sync_state()

    def _select_initial_preset(self, options: CrawlOptions, advanced_on: bool) -> None:
        self._applying_preset = True
        if not options.gentle_mode and not advanced_on and options.max_concurrent_per_host >= 4:
            self.btn_preset_standard.setChecked(True)
        elif options.gentle_mode and options.max_concurrent_per_host <= 2 and not advanced_on:
            self.btn_preset_gentle.setChecked(True)
        else:
            self.btn_preset_custom.setChecked(True)
        self._applying_preset = False

    def _show_help(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "Gentle crawl mode",
            (
                "Gentle mode keeps the request rate low, respects Crawl-delay directives, "
                "and retries politely after 403/429 responses.\n\n"
                "Use presets for quick defaults or switch to Custom to fine-tune headers and cookies."
            ),
        )

    def event(self, event: QtCore.QEvent):
        enter_help = getattr(QtCore.QEvent, "EnterWhatsThisMode", QtCore.QEvent.Type(0))
        if event.type() == enter_help:
            self._show_help()
            QtWidgets.QWhatsThis.leaveWhatsThisMode()
            QtWidgets.QApplication.restoreOverrideCursor()
            event.accept()
            return True
        return super().event(event)

    def nativeEvent(self, eventType: Any, message: Any) -> tuple[bool, int]:
        is_windows = sys.platform == "win32"
        is_help_msg = isinstance(eventType, (bytes, bytearray)) and bytes(eventType) == b"windows_generic_MSG"
        if is_windows and is_help_msg and message:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0112 and msg.wParam == 0xF180:
                self._show_help()
                return True, 0
        handled, result = super().nativeEvent(eventType, message)
        return bool(handled), int(result)
