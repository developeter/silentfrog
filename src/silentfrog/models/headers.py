from __future__ import annotations
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import _BaseModel


class HeaderModel(_BaseModel):
    HEADERS = ["Tag", "Text"]

    def __init__(self, rows: List[List[str]]) -> None:
        super().__init__(rows)
        self._h1_count = sum(1 for row in rows if row and str(row[0]).strip().lower() == "h1")
        self._brushes: StatusBrushPalette = status_brushes()

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role == Qt.ItemDataRole.BackgroundRole and index.column() in (0, 1):
            tag = (self._rows[index.row()][0] or "").strip().lower()
            if tag == "h1":
                return self._brushes.good if self._h1_count == 1 else self._brushes.warn
        return None
