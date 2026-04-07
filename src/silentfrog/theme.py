from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from qtpy import QtGui, QtWidgets

DARK_STYLESHEET = """
QWidget            { background: #1e1e1e; color: #f0f0f0; }
QPushButton        { background: #333; color: #f0f0f0; border: 1px solid #555; padding: 6px 12px; border-radius: 6px; }
QPushButton:hover  { background: #444; }
QTabWidget::pane   { border: 1px solid #555; background: #1e1e1e; }
QTabBar::tab       { background: #2e2e2e; color: #f0f0f0; padding: 6px; min-width: 80px; }
QTabBar::tab:selected { background: #3a3a3a; }
QTabBar::tab:hover { background: #444444; }
QTableView         { background: #1e1e1e; gridline-color: #555555; }
QTableView QHeaderView::section {
    background-color: #2e2e2e;
    color: #f0f0f0;
    padding: 4px;
    border: 1px solid #555555;
}
"""

LIGHT_STYLESHEET = """
QWidget            { background: #f0f0f0; color: #1e1e1e; }
QPushButton        { background: #f0f0f0; color: #333; border: 1px solid #555; padding: 6px 12px; border-radius: 6px; }
QPushButton:hover  { background: #555555; color: #f0f0f0}
QTabWidget::pane   { border: 1px solid #555; background: #f0f0f0; }
QTabBar::tab       { background: #f0f0f0; color: #2e2e2e; padding: 6px; min-width: 80px; }
QTabBar::tab:selected { background: #666; color: #f0f0f0}
QTabBar::tab:hover { background: #888; color: #2e2e2e}
QTableView         { background: #f0f0f0; gridline-color: #555555; }
QTableView QHeaderView::section {
    background-color: #f0f0f0;
    color: #2e2e2e;
    padding: 4px;
    border: 1px solid #555555;
}
"""


@dataclass(frozen=True)
class StatusBrushPalette:
    good: QtGui.QBrush
    warn: QtGui.QBrush
    bad: QtGui.QBrush


def _theme_key(dark: bool | None) -> str:
    if dark is not None:
        return "dark" if dark else "light"
    app = QtWidgets.QApplication.instance()
    if isinstance(app, QtWidgets.QApplication):
        palette = app.palette()
        base = palette.color(QtGui.QPalette.Base)
        return "dark" if base.value() < 128 else "light"
    return "light"


def current_theme(app: QtWidgets.QApplication | None = None) -> Literal["dark", "light"]:
    app_instance: QtWidgets.QApplication | None = app
    if app_instance is None:
        inst = QtWidgets.QApplication.instance()
        app_instance = inst if isinstance(inst, QtWidgets.QApplication) else None
    if app_instance is not None:
        prop = app_instance.property("silentfrog_theme")
        if prop in ("dark", "light"):
            return prop  # type: ignore[return-value]
        base = app_instance.palette().color(QtGui.QPalette.Base)
        return "dark" if base.value() < 128 else "light"
    return "light"


def apply_theme(app: QtWidgets.QApplication | None, dark: bool = True) -> None:
    if app is None:
        return
    app.setStyleSheet(DARK_STYLESHEET if dark else LIGHT_STYLESHEET)
    app.setProperty("silentfrog_theme", "dark" if dark else "light")
    palette = QtGui.QPalette()
    base = QtGui.QColor("#1f1f1f") if dark else QtGui.QColor("#ffffff")
    window = QtGui.QColor("#121212") if dark else QtGui.QColor("#f0f0f0")
    text = QtGui.QColor("#f5f5f5") if dark else QtGui.QColor("#202124")
    button = QtGui.QColor("#1e1e1e") if dark else QtGui.QColor("#ededed")
    highlight = QtGui.QColor("#2ecc71") if dark else QtGui.QColor("#0f9d58")
    palette.setColor(QtGui.QPalette.Window, window)
    palette.setColor(QtGui.QPalette.Base, base)
    palette.setColor(QtGui.QPalette.AlternateBase, base.darker(110))
    palette.setColor(QtGui.QPalette.Text, text)
    palette.setColor(QtGui.QPalette.WindowText, text)
    palette.setColor(QtGui.QPalette.Button, button)
    palette.setColor(QtGui.QPalette.ButtonText, text)
    palette.setColor(QtGui.QPalette.Highlight, highlight)
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
    app.setPalette(palette)


@lru_cache(maxsize=4)
def status_brushes(dark: bool | None = None) -> StatusBrushPalette:
    key = _theme_key(dark)
    if key == "dark":
        return StatusBrushPalette(
            good=QtGui.QBrush(QtGui.QColor(76, 175, 80, 140)),
            warn=QtGui.QBrush(QtGui.QColor(255, 213, 79, 150)),
            bad=QtGui.QBrush(QtGui.QColor(239, 83, 80, 160)),
        )
    return StatusBrushPalette(
        good=QtGui.QBrush(QtGui.QColor(0, 180, 0, 80)),
        warn=QtGui.QBrush(QtGui.QColor(255, 200, 0, 100)),
        bad=QtGui.QBrush(QtGui.QColor(200, 0, 0, 90)),
    )


__all__ = ["StatusBrushPalette", "status_brushes", "apply_theme", "current_theme", "DARK_STYLESHEET", "LIGHT_STYLESHEET"]
