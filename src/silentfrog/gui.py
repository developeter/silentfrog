from __future__ import annotations

import ctypes
import importlib.resources
import platform
import sys
from pathlib import Path
from typing import cast

from qtpy import QtCore, QtGui, QtWidgets
from qtpy.QtCore import Qt
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import (
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
        # The home is a fixed-size landing card. Resize / full-screen
        # were producing layouts the maintainer rejected (buttons
        # stretching edge-to-edge, gear lost in the middle). Locking
        # the size keeps the visual contract stable regardless of OS
        # window manager whims; child windows opened from here grow
        # freely on their own.
        self.setFixedSize(640, 720)

        # Each click on a primary action opens a new top-level QWidget.
        # We must hold a Python reference to every one of them or
        # PySide6 will free the C++ side as soon as a previous click's
        # local variable goes out of scope, crashing the running window.
        self._child_windows: list[QtWidgets.QWidget] = []

        self._build_help_menu()

        self.main_layout = QtWidgets.QVBoxLayout()
        self.main_layout.setSpacing(16)
        self.main_layout.setContentsMargins(48, 32, 48, 24)

        icon_path = importlib.resources.files("silentfrog").joinpath("assets/icon.png")
        self.setWindowIcon(QIcon(str(icon_path)))

        logo = QtWidgets.QLabel()
        logo.setAlignment(Qt.AlignCenter)  # type: ignore[reportAttributeAccessIssue]
        logo_pix = (
            QtGui.QPixmap(str(icon_path))
            .scaledToWidth(120, Qt.SmoothTransformation)  # type: ignore[reportAttributeAccessIssue]
        )
        logo.setPixmap(logo_pix)
        # Pin the label to fit the pixmap so a stylesheet re-polish on
        # theme change cannot shrink it and clip the frog (the macOS
        # repro: open Settings, switch theme, OK -> logo half hidden).
        logo.setMinimumSize(logo_pix.size())
        logo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        # Top stretch + bottom stretch around the logo/buttons cluster
        # vertically centre it inside the fixed-size window. The gear
        # row sits BELOW the bottom stretch so it stays pinned to the
        # bottom-right of the window itself, not the inner column.
        self.main_layout.addStretch(1)
        self.main_layout.addWidget(logo)

        actions = (
            ("Massive Redirect Check", self.open_redirect),
            ("Single Page SEO Check", self.open_seo),
            ("Site Crawl", self.open_site_crawl),
        )
        for label, callback in actions:
            btn = QPushButton(label)
            font = btn.font()
            font.setPointSize(font.pointSize() + 4)
            btn.setFont(font)
            btn.setFixedHeight(48)
            btn.clicked.connect(callback)
            self.main_layout.addWidget(btn)

        self.main_layout.addStretch(1)

        gear = QToolButton()
        gear.setObjectName("settingsGear")
        settings_icon = importlib.resources.files("silentfrog").joinpath("assets/settings.png")
        gear.setIcon(QtGui.QIcon(str(settings_icon)))
        gear.setIconSize(QtCore.QSize(28, 28))
        gear.setToolTip("Settings")
        gear.setFixedSize(44, 44)
        gear.setCursor(Qt.PointingHandCursor)
        gear.clicked.connect(self._open_settings)

        gear_row = QtWidgets.QHBoxLayout()
        gear_row.addStretch()
        gear_row.addWidget(gear)
        self.main_layout.addLayout(gear_row)

        container = QWidget()
        container.setLayout(self.main_layout)
        self.setCentralWidget(container)

    def open_redirect(self) -> None:
        self._spawn_child(RedirectWindow())

    def open_seo(self) -> None:
        from .seo_gui import WebpageSeoWindow

        self._spawn_child(WebpageSeoWindow())

    def open_site_crawl(self) -> None:
        from .site_crawl_gui import SiteCrawlWindow

        self._spawn_child(SiteCrawlWindow())

    def _spawn_child(self, window: QtWidgets.QWidget) -> None:
        """Show ``window`` and retain a strong reference to it.

        Each click on a primary action opens an independent top-level
        window. Callers that store the window on ``self`` end up
        overwriting the previous one — losing its Python ref while it
        is still visible, which segfaults PySide6.
        """
        self._child_windows.append(window)
        window.destroyed.connect(lambda *_: self._forget_child(window))
        window.show()

    def _forget_child(self, window: QtWidgets.QWidget) -> None:
        try:
            self._child_windows.remove(window)
        except ValueError:
            pass

    def _open_settings(self) -> None:
        dlg = _SettingsDialog(self)
        dlg.exec()

    def _build_help_menu(self) -> None:
        menu_bar = self.menuBar()
        help_menu = menu_bar.addMenu("&Help")
        check_action = help_menu.addAction("Check for &Updates…")
        check_action.triggered.connect(self._open_update_dialog)
        about_action = help_menu.addAction("&About Silentfrog")
        # Force AboutRole instead of relying on Qt's TextHeuristicRole.
        # On macOS the action is auto-moved into the "Silentfrog"
        # application menu next to the Apple; on other platforms it
        # stays here under Help.
        about_action.setMenuRole(QtGui.QAction.AboutRole)
        check_action.setMenuRole(QtGui.QAction.ApplicationSpecificRole)
        about_action.triggered.connect(self._open_about_dialog)

    def _open_update_dialog(self) -> None:
        from .update_gui import UpdateDialog

        dlg = UpdateDialog(self)
        dlg.exec()

    def _open_about_dialog(self) -> None:
        from .update_gui import AboutDialog

        dlg = AboutDialog(self)
        dlg.exec()


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
    # Qt on macOS auto-migrates the QMainWindow menu bar into the
    # system menu bar at the top of the screen. Because the running
    # process is the Python interpreter (whose bundle is the framework
    # Python.app), that system menu reads "Python" — and nothing short
    # of py2app or a compiled Mach-O launcher inside our bundle fixes
    # the underlying NSApplication bundle association. AA_DontUseNativeMenuBar
    # opts out of that migration entirely so the Help menu renders inside
    # the Silentfrog window itself, the way it does on Windows.
    QApplication.setAttribute(Qt.AA_DontUseNativeMenuBar, True)
    QApplication.setApplicationName("Silentfrog")
    QApplication.setApplicationDisplayName("Silentfrog")
    QApplication.setOrganizationName("Silentfrog")
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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
