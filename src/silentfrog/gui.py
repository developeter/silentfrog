from __future__ import annotations

import sys
import platform
import ctypes
import importlib.resources
from pathlib import Path
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QToolButton,
    QDialog,
    QRadioButton,
    QDialogButtonBox,
    QButtonGroup,
)
from .redirect_gui import RedirectWindow

# ---------- THEMES --------------------------------------------------- #
DARK_STYLESHEET = """
QWidget            { background: #1e1e1e; color: #f0f0f0; }
QPushButton        { background: #333; color: #f0f0f0; border: 1px solid #555; padding: 6px 12px; border-radius: 6px; }
QPushButton:hover  { background: #444; }
QTabWidget::pane   { border: 1px solid #555; background: #1e1e1e; }
QTabBar::tab       { background: #2e2e2e; color: #f0f0f0; padding: 6px; min-width: 80px; }
QTabBar::tab:selected { background: #3a3a3a; }
QTabBar::tab:hover { background: #444444; }

/* ─── TABLE / HEADER STYLING ───────────────────────────────────────────── */
QTableView         { background: #1e1e1e; gridline-color: #555555; }
QTableView QHeaderView::section {
    background-color: #2e2e2e;
    color: #f0f0f0;
    padding: 4px;
    border: 1px solid #555555;
}
/* ──────────────────────────────────────────────────────────────────────── */
"""
LIGHT_STYLESHEET = """
QWidget            { background: #f0f0f0; color: #1e1e1e; }
QPushButton        { background: #f0f0f0; color: #333; border: 1px solid #555; padding: 6px 12px; border-radius: 6px; }
QPushButton:hover  { background: #555555; color: #f0f0f0}
QTabWidget::pane   { border: 1px solid #555; background: #f0f0f0; }
QTabBar::tab       { background: #f0f0f0; color: #2e2e2e; padding: 6px; min-width: 80px; }
QTabBar::tab:selected { background: #666; color: #f0f0f0}
QTabBar::tab:hover { background: #888; color: #2e2e2e}

/* ─── TABLE / HEADER STYLING ───────────────────────────────────────────── */
QTableView         { background: #f0f0f0; gridline-color: #555555; }
QTableView QHeaderView::section {
    background-color: #f0f0f0;
    color: #2e2e2e;
    padding: 4px;
    border: 1px solid #555555;
}
/* ──────────────────────────────────────────────────────────────────────── */
"""

def apply_theme(app, dark: bool = True) -> None:
    """
    Apply the dark/light stylesheet to the running QApplication (if any).
    We remove the strict type-hint on `app` so that QCoreApplication.instance() can be passed in.
    """
    if app is not None:
        app.setStyleSheet(DARK_STYLESHEET if dark else LIGHT_STYLESHEET)
        app.setProperty("silentfrog_theme", "dark" if dark else "light")


icon_path = importlib.resources.files("silentfrog").joinpath("assets/icon.png")


class HomeWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Silentfrog")
        self.setMinimumSize(400, 200)

        # ---------- layout container ----------
        # Rename from `self.layout` → `self.main_layout` to avoid colliding with the QMainWindow.layout() method
        self.main_layout = QtWidgets.QVBoxLayout()
        self.main_layout.setSpacing(20)

        # ---------- window icon from the package ----------
        icon_path = importlib.resources.files("silentfrog").joinpath("assets/icon.png")
        self.setWindowIcon(QIcon(str(icon_path)))

        # ---------- centred logo ----------
        logo = QtWidgets.QLabel()
        logo.setAlignment(Qt.AlignCenter)  # type: ignore[reportAttributeAccessIssue]
        logo_pix = (
            QtGui.QPixmap(str(icon_path))
            .scaledToWidth(120, Qt.SmoothTransformation)  # type: ignore[reportAttributeAccessIssue]
        )
        logo.setPixmap(logo_pix)
        self.main_layout.addWidget(logo)

        # ---------- three main buttons ----------
        for idx, label in enumerate(("Massive Redirect Check", "SEO Webpage analysis")):
            btn = QPushButton(label)
            font = btn.font()
            font.setPointSize(font.pointSize() + 4)  # bigger text
            btn.setFont(font)
            btn.setFixedHeight(48)

            if idx == 0:
                btn.clicked.connect(self.open_redirect)
            elif idx == 1:
                btn.clicked.connect(self.open_seo)
            self.main_layout.addWidget(btn)

        # ---------- settings gear bottom-right ----------
        gear = QToolButton()
        # Load our bundled gear/Settings icon instead of fromTheme(...)
        icon_path = importlib.resources.files("silentfrog").joinpath("assets/settings.png")
        gear.setIcon(QtGui.QIcon(str(icon_path)))
        gear.setToolTip("Settings")  # tooltip remains the same
        gear.setFixedSize(32, 32)
        gear.clicked.connect(self._open_settings)

        gear_row = QtWidgets.QHBoxLayout()
        gear_row.addStretch()
        gear_row.addWidget(gear)
        self.main_layout.addLayout(gear_row)

        # Finally, put the QVBoxLayout into a central QWidget
        container = QWidget()
        container.setLayout(self.main_layout)
        self.setCentralWidget(container)

    # ---------- “Check Redirect” window ----------
    def open_redirect(self) -> None:
        self.redir = RedirectWindow()
        self.redir.show()

    # ---------- “SEO analysis” window ----------
    def open_seo(self) -> None:
        from .seo_gui import WebpageSeoWindow

        self.seo_win = WebpageSeoWindow()
        self.seo_win.show()

    # ---------------- settings popup ---------------- #
    def _open_settings(self) -> None:
        dlg = _SettingsDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            # Pass QApplication.instance() (which is actually a QCoreApplication under the hood)
            apply_theme(QtWidgets.QApplication.instance(), dlg.dark_radio.isChecked())
            apply_theme(QApplication.instance(), dlg.dark_radio.isChecked())


class _SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Appearance")
        # Remove the Windows "?" context-help button so only standard controls stay visible.
        flags = self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint
        self.setWindowFlags(flags)
        self.resize(360, 150)
        lay = QVBoxLayout(self)

        self.dark_radio = QRadioButton("Dark theme")
        self.light_radio = QRadioButton("Light theme")
        self.dark_radio.setChecked(True)

        grp = QButtonGroup(self)
        grp.addButton(self.dark_radio)
        grp.addButton(self.light_radio)

        lay.addWidget(self.dark_radio)
        lay.addWidget(self.light_radio)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)


def main():
    app = QApplication(sys.argv)
    apply_theme(app, dark=True)  # default = dark

    assets = importlib.resources.files("silentfrog").joinpath("assets")
    if platform.system() == "Windows":
        # This makes sure the icon shows up in the Windows taskbar
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("silentfrog.app")
        app.setWindowIcon(QIcon(str(assets / "icon.ico")))
    else:
        app.setWindowIcon(QIcon(str(assets / "icon.png")))

    window = HomeWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
