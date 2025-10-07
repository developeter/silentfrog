from __future__ import annotations
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class SerpAuditModel(GenericModel):
    def __init__(self, headers: List[str], rows: List[List[str]]) -> None:
        super().__init__(headers, rows)
        self._brushes: StatusBrushPalette = status_brushes()

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role == Qt.ItemDataRole.BackgroundRole and index.column() == 1:
            key = (self._rows[index.row()][0] or "").lower()
            value = str(self._rows[index.row()][1] or "").strip().lower()
            if key == "missing":
                return self._brushes.bad if value in ("yes", "true", "1") else self._brushes.good
            if key in ("> 60 chars", "< 30 chars", "> 561 px", "< 200 px", "equals h1"):
                return self._brushes.warn if value in ("yes", "true", "1") else self._brushes.good
            if key.startswith("length (chars)"):
                try:
                    length = int(value or "0")
                except Exception:
                    length = 0
                return self._brushes.good if 30 <= length <= 60 else self._brushes.warn
            if key.startswith("length (pixels)"):
                try:
                    pixels = int(value or "0")
                except Exception:
                    pixels = 0
                return self._brushes.good if 200 <= pixels <= 561 else self._brushes.warn
        return None
