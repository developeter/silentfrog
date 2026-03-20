from __future__ import annotations

from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class IndexabilityModel(GenericModel):
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
            lower_value = value.lower()
            if key == "final status":
                if value.isdigit() and 200 <= int(value) < 300:
                    return self._brushes.good
                if value.isdigit() and 300 <= int(value) < 400:
                    return self._brushes.warn
                return self._brushes.bad
            if key == "redirect hops":
                try:
                    return self._brushes.good if int(value) == 0 else self._brushes.warn
                except Exception:
                    return self._brushes.bad
            if key == "crawl allowed by robots.txt":
                return self._brushes.good if lower_value.startswith("y") else self._brushes.bad
            if key == "meta / x-robots-tag":
                if lower_value == "-":
                    return self._brushes.warn
                if "noindex" in lower_value or lower_value == "none":
                    return self._brushes.bad
                if "nofollow" in lower_value:
                    return self._brushes.warn
                return self._brushes.good
            if key == "index directive":
                return self._brushes.good if lower_value == "index" else self._brushes.bad
            if key == "follow directive":
                return self._brushes.good if lower_value == "follow" else self._brushes.warn
            if key == "canonical url":
                return self._brushes.good if value and value != "-" else self._brushes.warn
            if key == "canonical self-reference":
                return self._brushes.good if lower_value.startswith("y") else self._brushes.warn
            if key == "canonical status":
                if value.isdigit() and 200 <= int(value) < 400:
                    return self._brushes.good
                return self._brushes.warn if value == "-" else self._brushes.bad
            if key == "multiple canonicals":
                return self._brushes.bad if lower_value.startswith("y") else self._brushes.good
            if key == "overall verdict":
                if lower_value == "indexable":
                    return self._brushes.good
                if lower_value in {"redirected", "canonicalized elsewhere", "indexable with warnings"}:
                    return self._brushes.warn
                return self._brushes.bad
        return None
