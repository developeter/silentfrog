from __future__ import annotations

import ctypes
import importlib.resources
import platform
import sys
from pathlib import Path
from typing import cast

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .redirect_gui import RedirectWindow
from .theme import apply_theme, current_theme

icon_path = importlib.resources.files("silentfrog").joinpath("assets/icon.png")


class HomeWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Silentfrog")
        self.setMinimumSize(400, 200)

        self.main_layout = QtWidgets.QVBoxLayout()
        self.main_layout.setSpacing(20)

        icon_path = importlib.resources.files("silentfrog").joinpath("assets/icon.png")
        self.setWindowIcon(QIcon(str(icon_path)))

        logo = QtWidgets.QLabel()
        logo.setAlignment(Qt.AlignCenter)  # type: ignore[reportAttributeAccessIssue]
        logo_pix = (
            QtGui.QPixmap(str(icon_path))
            .scaledToWidth(120, Qt.SmoothTransformation)  # type: ignore[reportAttributeAccessIssue]
        )
        logo.setPixmap(logo_pix)
        self.main_layout.addWidget(logo)

        for idx, label in enumerate(("Massive Redirect Check", "SEO Webpage analysis")):
            btn = QPushButton(label)
            font = btn.font()
            font.setPointSize(font.pointSize() + 4)
            btn.setFont(font)
            btn.setFixedHeight(48)

            if idx == 0:
                btn.clicked.connect(self.open_redirect)
            elif idx == 1:
                btn.clicked.connect(self.open_seo)
            self.main_layout.addWidget(btn)

        gear = QToolButton()
        settings_icon = importlib.resources.files("silentfrog").joinpath("assets/settings.png")
        gear.setIcon(QtGui.QIcon(str(settings_icon)))
        gear.setToolTip("Settings")
        gear.setFixedSize(32, 32)
        gear.clicked.connect(self._open_settings)

        gear_row = QtWidgets.QHBoxLayout()
        gear_row.addStretch()
        gear_row.addWidget(gear)
        self.main_layout.addLayout(gear_row)

        container = QWidget()
        container.setLayout(self.main_layout)
        self.setCentralWidget(container)

    def open_redirect(self) -> None:
        self.redir = RedirectWindow()
        self.redir.show()

    def open_seo(self) -> None:
        from .seo_gui import WebpageSeoWindow

        self.seo_win = WebpageSeoWindow()
        self.seo_win.show()

    def _open_settings(self) -> None:
        dlg = _SettingsDialog(self)
        dlg.exec_()


class _SettingsDialog(QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Appearance")
        flags = cast(
            QtCore.Qt.WindowFlags,
            self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint,
        )
        self.setWindowFlags(flags)
        layout = QVBoxLayout(self)

        self.dark_radio = QRadioButton("Dark theme")
        self.light_radio = QRadioButton("Light theme")
        app = cast(QtWidgets.QApplication | None, QApplication.instance())
        theme = current_theme(app)
        self.dark_radio.setChecked(theme == "dark")
        self.light_radio.setChecked(theme == "light")

        group = QButtonGroup(self)
        group.addButton(self.dark_radio)
        group.addButton(self.light_radio)

        layout.addWidget(self.dark_radio)
        layout.addWidget(self.light_radio)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.adjustSize()

    def accept(self) -> None:
        app = cast(QtWidgets.QApplication | None, QApplication.instance())
        apply_theme(app, self.dark_radio.isChecked())
        super().accept()


def main() -> None:
    app = QApplication(sys.argv)
    apply_theme(app, dark=True)

    assets = importlib.resources.files("silentfrog").joinpath("assets")
    if platform.system() == "Windows":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("silentfrog.app")
        app.setWindowIcon(QIcon(str(assets / "icon.ico")))
    else:
        app.setWindowIcon(QIcon(str(assets / "icon.png")))

    window = HomeWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
