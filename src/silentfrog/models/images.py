
from __future__ import annotations
import re
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class ImagesModel(GenericModel):
    def __init__(self, rows: List[List[str]]) -> None:
        display_rows = [row[:6] for row in rows]
        super().__init__(["Src", "Alt", "Title", "W", "H", "Peso"], display_rows)
        self._brushes: StatusBrushPalette = status_brushes()
        self._lazy_rows = {
            idx for idx, row in enumerate(rows) if len(row) > 6 and str(row[6]) == "1"
        }
        self._dimension_rows = {
            idx for idx, row in enumerate(rows) if len(row) > 7 and str(row[7]) == "1"
        }

    @staticmethod
    def _filled(value: object) -> bool:
        return bool(str(value).strip())

    @staticmethod
    def _bytes(human: object) -> int:
        text = str(human).strip()
        match = re.search(r"([\d.,]+)\s*([KMGT]?I?B)", text, re.I) if text else None
        if not match:
            return -1
        number = float(match.group(1).replace(",", "."))
        unit = match.group(2).upper()
        multiplier = {
            "B": 1,
            "KB": 1024,
            "MB": 1024 ** 2,
            "GB": 1024 ** 3,
            "KIB": 1024,
            "MIB": 1024 ** 2,
            "GIB": 1024 ** 3,
            "TB": 1024 ** 4,
            "TIB": 1024 ** 4,
        }.get(unit, 1)
        return int(number * multiplier)

    def _color_required(self, value: object):
        return self._brushes.good if ImagesModel._filled(value) else self._brushes.warn

    def _color_size(self, value: object):
        size = ImagesModel._bytes(value)
        if size < 0:
            return None
        if size > 500 * 1024:
            return self._brushes.bad
        if size > 100 * 1024:
            return self._brushes.warn
        return self._brushes.good

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role != Qt.ItemDataRole.BackgroundRole:
            return None
        row = index.row()
        column = index.column()
        if column in (1, 2):
            return self._color_required(self._rows[row][column])
        if column == 5:
            return self._color_size(self._rows[row][column])
        if column == 0 and row > 0 and row not in self._lazy_rows:
            return self._brushes.warn
        if column in (3, 4) and row not in self._dimension_rows:
            return self._brushes.warn
        return None
