from __future__ import annotations
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class CanonicalModel(GenericModel):
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
            value = str(self._rows[index.row()][1] or "")
            if key == "canonical url":
                return self._brushes.good if value and value != "-" else self._brushes.bad
            if key == "self-referencing":
                return self._brushes.good if value.lower().startswith("y") else self._brushes.bad
            if key == "multiple canonicals":
                return self._brushes.bad if value.lower().startswith("y") else self._brushes.good
            if key == "canonical status":
                if value.isdigit() and 200 <= int(value) < 400:
                    return self._brushes.good
                return self._brushes.warn if value else self._brushes.bad
        return None
