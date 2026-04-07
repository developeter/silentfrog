from __future__ import annotations
from typing import List

from qtpy import QtCore
from qtpy.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class RobotsModel(GenericModel):
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
            value = (self._rows[index.row()][1] or "").lower()
            if key.startswith("meta"):
                if "noindex" in value:
                    return self._brushes.bad
                if "nofollow" in value:
                    return self._brushes.warn
                return self._brushes.good
            if key.startswith("x-robots"):
                if "noindex" in value:
                    return self._brushes.bad
                if "nofollow" in value:
                    return self._brushes.warn
                return self._brushes.good
            if key.startswith("disallow"):
                return self._brushes.bad if value.strip() not in ("", "/") else self._brushes.warn
        return None
