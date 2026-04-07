from __future__ import annotations
from typing import List

from qtpy import QtCore
from qtpy.QtCore import Qt

from .base import GenericModel
from ..theme import StatusBrushPalette, status_brushes


class LinksModel(GenericModel):
    def __init__(self, rows: List[List[str]]) -> None:
        super().__init__(
            [
                "URL",
                "Anchor",
                "Type",
                "Rel",
                "Status",
                "Status note",
                "Section",
                "Heading",
                "TLD",
            ],
            rows,
        )
        self._brushes: StatusBrushPalette = status_brushes()

    def _status_brush(self, value: object):
        try:
            code = int(value)
        except (TypeError, ValueError):
            return self._brushes.bad
        if 200 <= code < 300:
            return self._brushes.good
        if 300 <= code < 400:
            return self._brushes.warn
        return self._brushes.bad

    def _note_brush(self, value: object):
        note = str(value).strip().lower()
        mapping = {
            "ok": self._brushes.good,
            "redirect": self._brushes.warn,
            "client error": self._brushes.bad,
            "server error": self._brushes.bad,
            "fetch error": self._brushes.bad,
        }
        return mapping.get(note)

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role != Qt.ItemDataRole.BackgroundRole:
            return None
        column = index.column()
        value = self._rows[index.row()][column]
        if column == 4:
            return self._status_brush(value)
        if column == 5:
            return self._note_brush(value)
        return None
