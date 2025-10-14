
from __future__ import annotations
import re
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class ImagesModel(GenericModel):
    def __init__(self, rows: List[List[str]]) -> None:
        normalized: List[List[str]] = []
        self._lazy_rows: set[int] = set()
        self._dimension_rows: set[int] = set()
        for idx, row in enumerate(rows):
            padded = (row + [""] * 8)[:8]
            src, alt, title, mime, width, height, size, lazy = padded
            lazy_text = str(lazy).strip().lower()
            lazy_value = "Yes" if lazy_text in {"yes", "1", "true"} else "No"
            normalized.append(
                [src, alt, title, mime, width, height, size, lazy_value]
            )
            if lazy_value == "Yes":
                self._lazy_rows.add(idx)
            if str(width).strip() and str(height).strip():
                self._dimension_rows.add(idx)

        super().__init__(["Src", "Alt", "Title", "Type", "W", "H", "Size", "Lazy"], normalized)
        self._brushes: StatusBrushPalette = status_brushes()

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
        if column == 3:
            return None
        if column == 6:
            return self._color_size(self._rows[row][column])
        if column == 0 and row not in self._lazy_rows:
            return self._brushes.warn
        if column in (4, 5) and row not in self._dimension_rows:
            return self._brushes.warn
        if column == 7 and row not in self._lazy_rows:
            return self._brushes.warn
        return None
