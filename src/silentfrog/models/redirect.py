from __future__ import annotations

import re

from qtpy import QtCore
from qtpy.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class RedirectModel(GenericModel):
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
        if role == Qt.ItemDataRole.BackgroundRole and index.column() == 1:
            key = (self._rows[index.row()][0] or "").lower()
            value = str(self._rows[index.row()][1] or "")
            if key == "hop count":
                try:
                    hops = int(value)
                except Exception:
                    hops = 0
                if hops == 0:
                    return self._brushes.good
                if hops <= 2:
                    return self._brushes.warn
                return self._brushes.bad
            if key == "final status":
                match = re.search(r"\d{3}", value)
                code = int(match.group(0)) if match else 0
                if 200 <= code < 300:
                    return self._brushes.good
                if 300 <= code < 400:
                    return self._brushes.warn
                return self._brushes.bad
            if key == "loop detected":
                return self._brushes.bad if value.lower().startswith("y") else self._brushes.good
            if key == "redirect chain":
                return self._brushes.warn if "" in value or "->" in value else self._brushes.good
        return None
