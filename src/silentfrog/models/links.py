from __future__ import annotations
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from .base import GenericModel
from ..theme import StatusBrushPalette, status_brushes


class LinksModel(GenericModel):
    def __init__(self, rows: List[List[str]]) -> None:
        super().__init__(["URL", "Anchor", "Follow ?", "Status"], rows)
        self._brushes: StatusBrushPalette = status_brushes()

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role == Qt.ItemDataRole.BackgroundRole and index.column() == 3:
            try:
                code = int(self._rows[index.row()][3])
            except ValueError:
                code = 0
            if 200 <= code < 300:
                return self._brushes.good
            if 300 <= code < 400:
                return self._brushes.warn
            return self._brushes.bad
        return None
