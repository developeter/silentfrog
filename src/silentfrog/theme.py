from __future__ import annotations

import importlib.resources
import string
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from qtpy import QtGui, QtWidgets


def window_icon() -> QtGui.QIcon:
    """Shared title-bar / taskbar-button icon for every Silentfrog window.

    Kept separate from the program/desktop icon (``assets/icon.*``) and
    from the home-screen logo (``assets/logo.png``) so the three can be
    art-directed independently.
    """
    path = importlib.resources.files("silentfrog").joinpath("assets/window-icon.png")
    return QtGui.QIcon(str(path))


# `QTabWidget::tab-bar { left: 0px }` anchors the QTabBar to the left
# edge of the QTabWidget's top area, neutralising macOS's default of
# centring the bar within the available width. Combined with
# `QTabBar::setExpanding(False)` the tabs sit flush left on every OS.
_LEFT_ALIGN_TAB_STYLESHEET = "QTabWidget::tab-bar { left: 0px; alignment: left; }"


def left_align_tab_bar(tab_widget: QtWidgets.QTabWidget) -> None:
    """Anchor the tab bar of ``tab_widget`` to the left on every OS."""
    existing = tab_widget.styleSheet()
    if _LEFT_ALIGN_TAB_STYLESHEET in existing:
        return
    combined = f"{existing} {_LEFT_ALIGN_TAB_STYLESHEET}".strip()
    tab_widget.setStyleSheet(combined)
    tab_widget.tabBar().setExpanding(False)


# Design tokens (GUI polish, post-V19). One template + two token sets keeps
# the themes structurally identical, so a widget can't be styled in dark mode
# and forgotten in light mode. string.Template ($name) is used because QSS is
# full of literal braces that str.format would misparse.
_DARK_TOKENS = {
    "bg0": "#17181a",  # window
    "bg1": "#1e2023",  # cards / inputs / tables
    "bg2": "#26282c",  # raised / hover
    "border": "#34373c",
    "border_strong": "#4a4e55",
    "text": "#e8eaed",
    "text2": "#9aa0a6",
    "accent": "#2ecc71",
    "accent_text": "#12331f",
    "accent_hover": "#45e08a",
    "selection": "rgba(46, 204, 113, 0.22)",
}

_LIGHT_TOKENS = {
    "bg0": "#f6f7f8",
    "bg1": "#ffffff",
    "bg2": "#eef0f2",
    "border": "#d9dde3",
    "border_strong": "#c3c9d1",
    "text": "#1f2328",
    "text2": "#57606a",
    "accent": "#0f9d58",
    "accent_text": "#ffffff",
    "accent_hover": "#18b367",
    "selection": "rgba(15, 157, 88, 0.18)",
}

_QSS_TEMPLATE = string.Template("""
QWidget            { background: $bg0; color: $text; }
QToolTip           { background: $bg2; color: $text; border: 1px solid $border_strong; padding: 4px 8px; }
QPushButton        { background: $bg2; color: $text; border: 1px solid $border; padding: 6px 14px; border-radius: 6px; }
QPushButton:hover  { background: $bg1; border-color: $border_strong; }
QPushButton:pressed { background: $bg1; border-color: $accent; }
QPushButton:disabled { background: $bg0; color: $text2; border: 1px solid $border; }
QMenuBar           { background: $bg0; color: $text; padding: 2px 6px; border-bottom: 1px solid $border; }
QMenuBar::item     { background: transparent; padding: 6px 12px; border-radius: 4px; }
QMenuBar::item:selected { background: $bg2; color: $text; }
QMenuBar::item:pressed  { background: $accent; color: $accent_text; }
QMenu              { background: $bg1; color: $text; border: 1px solid $border; padding: 4px; }
QMenu::item        { padding: 6px 22px; border-radius: 4px; }
QMenu::item:selected { background: $accent; color: $accent_text; }
QMenu::separator   { height: 1px; background: $border; margin: 4px 6px; }
QToolButton#settingsGear { background: $bg1; border: 1px solid $border; border-radius: 8px; padding: 4px; }
QToolButton#settingsGear:hover { background: $bg2; border-color: $accent; }
QToolButton#settingsGear:pressed { background: $accent; }
QTabWidget::pane   { border: 1px solid $border; background: $bg0; border-radius: 2px; }
QTabBar::tab       { background: transparent; color: $text2; padding: 7px 14px; min-width: 80px;
                     border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }
QTabBar::tab:hover { color: $text; }
QTableView         { background: $bg1; alternate-background-color: $bg0; gridline-color: transparent;
                     border: 1px solid $border; selection-background-color: $selection; selection-color: $text; }
QTableView QHeaderView::section {
    background-color: $bg1; color: $text2; font-weight: 600;
    padding: 6px 8px; border: none; border-bottom: 1px solid $border_strong;
}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: $bg1; color: $text; border: 1px solid $border; border-radius: 6px; padding: 5px 8px;
    selection-background-color: $selection; selection-color: $text;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid $accent;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: $bg1; color: $text; border: 1px solid $border;
                              selection-background-color: $selection; }
QGroupBox          { border: 1px solid $border; border-radius: 8px; margin-top: 12px; padding-top: 6px; }
QGroupBox::title   { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: $text2; font-weight: 600; }
QProgressBar       { background: $bg2; border: none; border-radius: 6px; text-align: center;
                     color: $text; min-height: 12px; }
QProgressBar::chunk { background: $accent; border-radius: 6px; }
QScrollBar:vertical   { background: transparent; width: 10px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:vertical   { background: $border_strong; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:horizontal { background: $border_strong; border-radius: 5px; min-width: 24px; }
QScrollBar::handle:hover { background: $accent; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QCheckBox          { spacing: 8px; padding: 2px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $border_strong;
                       border-radius: 4px; background: $bg1; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QCheckBox::indicator:disabled { background: $bg0; border-color: $border; }
QRadioButton                       { spacing: 8px; padding: 4px; }
QRadioButton::indicator            { width: 16px; height: 16px; border-radius: 8px; }
QRadioButton::indicator:unchecked  { background: $bg1; border: 1px solid $border_strong; }
QRadioButton::indicator:checked    { background: $accent; border: 2px solid $accent; }
QRadioButton::indicator:checked:hover { background: $accent_hover; }
""")

DARK_STYLESHEET = _QSS_TEMPLATE.substitute(_DARK_TOKENS)
LIGHT_STYLESHEET = _QSS_TEMPLATE.substitute(_LIGHT_TOKENS)


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
    tokens = _DARK_TOKENS if dark else _LIGHT_TOKENS
    palette = QtGui.QPalette()
    base = QtGui.QColor(tokens["bg1"])
    window = QtGui.QColor(tokens["bg0"])
    text = QtGui.QColor(tokens["text"])
    button = QtGui.QColor(tokens["bg2"])
    highlight = QtGui.QColor(tokens["accent"])
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
    # Soft tints, not saturated floods: at table scale a page of "good" rows
    # must read as a calm surface, with glyphs/text carrying the semantics.
    key = _theme_key(dark)
    if key == "dark":
        return StatusBrushPalette(
            good=QtGui.QBrush(QtGui.QColor(76, 175, 80, 60)),
            warn=QtGui.QBrush(QtGui.QColor(255, 213, 79, 70)),
            bad=QtGui.QBrush(QtGui.QColor(239, 83, 80, 85)),
        )
    return StatusBrushPalette(
        good=QtGui.QBrush(QtGui.QColor(0, 160, 60, 45)),
        warn=QtGui.QBrush(QtGui.QColor(240, 180, 0, 60)),
        bad=QtGui.QBrush(QtGui.QColor(210, 40, 40, 60)),
    )


__all__ = [
    "StatusBrushPalette",
    "status_brushes",
    "apply_theme",
    "current_theme",
    "left_align_tab_bar",
    "DARK_STYLESHEET",
    "LIGHT_STYLESHEET",
]
