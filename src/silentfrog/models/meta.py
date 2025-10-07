from __future__ import annotations
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import _BaseModel


class MetaModel(_BaseModel):
    HEADERS = ["Name/Property", "Content", "Length"]

    def __init__(self, rows: List[List[str]]) -> None:
        super().__init__(rows)
        self._brushes: StatusBrushPalette = status_brushes()

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role == Qt.ItemDataRole.BackgroundRole and index.column() == 2:
            key = self._rows[index.row()][0].lower()
            try:
                length = int(self._rows[index.row()][2])
            except ValueError:
                return self._brushes.bad
            if key == "description":
                return self._brushes.good if 120 <= length <= 160 else self._brushes.bad
            if key == "robots":
                content = (self._rows[index.row()][1] or "").lower()
                bad = any(tok in content for tok in ("noindex", "nofollow"))
                return self._brushes.bad if bad else self._brushes.good
        return super().data(index, role)
