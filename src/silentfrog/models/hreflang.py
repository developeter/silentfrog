from __future__ import annotations

import re

from qtpy import QtCore
from qtpy.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class HreflangModel(GenericModel):
    def __init__(self, headers: list[str], rows: list[list[str]]) -> None:
        super().__init__(headers, rows)
        self._brushes: StatusBrushPalette = status_brushes()

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role == Qt.ItemDataRole.BackgroundRole:
            column = index.column()
            row = self._rows[index.row()]
            if column == 2:
                try:
                    code = int(re.search(r"\d{3}", str(row[2])).group(0))
                except Exception:
                    code = 0
                if 200 <= code < 300:
                    return self._brushes.good
                if 300 <= code < 400:
                    return self._brushes.warn
                return self._brushes.bad
            if column == 3:
                return self._brushes.good if str(row[3]).strip().lower().startswith("y") else self._brushes.bad
            if column == 4:
                return self._brushes.good if str(row[4]).strip().lower().startswith("y") else self._brushes.warn
        return None
