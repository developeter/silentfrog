from __future__ import annotations

from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from ..content_quality import content_quality_tooltip
from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class ContentQualityModel(GenericModel):
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
        if role == Qt.ItemDataRole.ToolTipRole:
            return content_quality_tooltip(str(self._rows[index.row()][0] or ""))
        if role != Qt.ItemDataRole.BackgroundRole or index.column() != 1:
            return None
        key = str(self._rows[index.row()][0] or "").lower()
        value = str(self._rows[index.row()][1] or "")
        lower_value = value.lower()
        if key == "page language":
            return self._brushes.warn if lower_value == "not declared" else None
        if key == "title present":
            return self._brushes.good if lower_value == "yes" else self._brushes.bad
        if key == "meta description present":
            return self._brushes.good if lower_value == "yes" else self._brushes.warn
        if key == "h1 count":
            if value == "1":
                return self._brushes.good
            if value == "0":
                return self._brushes.bad
            return self._brushes.warn
        if key == "h2-h6 count":
            return self._brushes.warn if value == "0" else None
        if key == "title / h1 alignment":
            if lower_value in {"aligned", "exact match"}:
                return self._brushes.good
            if lower_value == "different":
                return self._brushes.warn
            if lower_value == "missing":
                return self._brushes.bad
        if key == "intro paragraph":
            return self._brushes.good if lower_value == "present" else self._brushes.warn
        if key == "thin-content risk":
            if lower_value == "low":
                return self._brushes.good
            if lower_value == "medium":
                return self._brushes.warn
            if lower_value == "high":
                return self._brushes.bad
        if key == "heading structure":
            if lower_value == "good":
                return self._brushes.good
            if lower_value in {"multiple h1s", "no subheadings"}:
                return self._brushes.warn
            if lower_value == "missing h1":
                return self._brushes.bad
        if key == "overall verdict":
            if lower_value == "strong":
                return self._brushes.good
            if lower_value == "needs work":
                return self._brushes.warn
            if lower_value == "weak":
                return self._brushes.bad
        return None


__all__ = ["ContentQualityModel"]
