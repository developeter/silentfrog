from __future__ import annotations

from qtpy import QtCore
from qtpy.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class SocialIssuesModel(GenericModel):
    def __init__(self, rows: list[list[str]]) -> None:
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
