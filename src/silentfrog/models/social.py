from __future__ import annotations

from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from .base import GenericModel
from ..theme import status_brushes, StatusBrushPalette


class SocialIssuesModel(GenericModel):
    def __init__(self, rows: List[List[str]]) -> None:
        super().__init__(["Source", "Issue"], rows)
        self._brushes: StatusBrushPalette = status_brushes()

    def data(  # type: ignore[override]
        self, index: QtCore.QModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role != Qt.ItemDataRole.BackgroundRole:
            return None
        issue = str(self._rows[index.row()][1]).lower()
        if any(token in issue for token in ("missing", "over", "unsupported", "error")):
            return self._brushes.warn if "over" not in issue else self._brushes.bad
        return None
