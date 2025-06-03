from __future__ import annotations

import sys, importlib.resources, platform
import importlib.resources
import sys, platform, ctypes, importlib.resources
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget
from PyQt5 import QtCore, QtWidgets          # + QtGui for icons/fonts
from .redirect_gui import RedirectWindow

# ---------- THEMES --------------------------------------------------- #
DARK_STYLESHEET = """
QWidget      { background:#1e1e1e; color:#f0f0f0; }
QPushButton  { background:#333;    color:#f0f0f0; border:1px solid #555;
               padding:6px 12px; border-radius:6px; }
QPushButton:hover { background:#444; }
QTabWidget::pane { border:1px solid #555; }
"""
LIGHT_STYLESHEET = ""  # Qt default – leave empty

def apply_theme(app: QtWidgets.QApplication, dark: bool = True) -> None:
    app.setStyleSheet(DARK_STYLESHEET if dark else LIGHT_STYLESHEET)


icon_path = importlib.resources.files("silentfrog").joinpath("assets/icon.png")

class HomeWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Silentfrog")
        self.setMinimumSize(400, 200)

        # icona dal pacchetto
        icon_path = importlib.resources.files("silentfrog").joinpath("assets/icon.png")
        self.setWindowIcon(QIcon(str(icon_path)))

        layout = QVBoxLayout()
        

        for idx, label in enumerate(("Check Redirect Massivo", "Analisi webpage SEO", "Coming soon")):
            btn = QPushButton(label)
            if idx == 0:
                btn.clicked.connect(self.open_redirect)
            elif idx == 1:
                btn.clicked.connect(self.open_seo)
            else:
                btn.setEnabled(False)
            layout.addWidget(btn)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def open_redirect(self):
        self.redir = RedirectWindow()
        self.redir.show()

    def open_seo(self) -> None:
        from .seo_gui import WebpageSeoWindow
        self.seo_win = WebpageSeoWindow()
        self.seo_win.show()



def main():
    
    app = QApplication(sys.argv)

    assets = importlib.resources.files("silentfrog").joinpath("assets")
    if platform.system() == "Windows":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("silentfrog.app")  # :contentReference[oaicite:3]{index=3}
        app.setWindowIcon(QIcon(str(assets / "icon.ico")))
    else:
        app.setWindowIcon(QIcon(str(assets / "icon.png")))


    window = HomeWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
