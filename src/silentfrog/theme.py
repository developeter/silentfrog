from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from PyQt5 import QtGui, QtWidgets


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


__all__ = ["StatusBrushPalette", "status_brushes"]
