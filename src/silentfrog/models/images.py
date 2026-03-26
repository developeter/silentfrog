
from __future__ import annotations
import re
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from ..image_diagnostics import (
    ACTUAL_HEIGHT_COL,
    ACTUAL_WIDTH_COL,
    ALT_COL,
    CACHE_COL,
    DECLARED_HEIGHT_COL,
    DECLARED_WIDTH_COL,
    DIAGNOSTIC_COL,
    FETCH_PRIORITY_COL,
    FORMAT_HINT_COL,
    IMAGE_HEADERS,
    LOADING_COL,
    RESPONSIVE_COL,
    SIZE_COL,
    TITLE_COL,
    normalize_image_row,
)
from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class ImagesModel(GenericModel):
    def __init__(self, rows: List[List[str]]) -> None:
        normalized: List[List[str]] = []
        for idx, row in enumerate(rows):
            padded = normalize_image_row(row)
            padded[LOADING_COL] = str(padded[LOADING_COL]).strip().title()
            padded[FETCH_PRIORITY_COL] = str(padded[FETCH_PRIORITY_COL]).strip()
            normalized.append(padded)

        super().__init__(
            IMAGE_HEADERS,
            normalized,
        )
        self._brushes: StatusBrushPalette = status_brushes()
        self._refresh_state()

    def _refresh_state(self) -> None:
        self._declared_dimension_rows = {
            idx
            for idx, row in enumerate(self._rows)
            if self._filled(row[DECLARED_WIDTH_COL]) and self._filled(row[DECLARED_HEIGHT_COL])
        }
        self._actual_dimension_rows = {
            idx
            for idx, row in enumerate(self._rows)
            if self._filled(row[ACTUAL_WIDTH_COL]) and self._filled(row[ACTUAL_HEIGHT_COL])
        }

    def _after_sort(self) -> None:
        self._refresh_state()

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

    @staticmethod
    def _priority_status(value: object) -> str:
        text = str(value).strip().lower()
        if not text:
            return "missing"
        if text in {"high", "true"}:
            return "high"
        if text in {"low", "auto", "false", "0", "no"}:
            return "low"
        return "custom"

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
        if column == ALT_COL:
            return self._color_required(self._rows[row][column])
        if column == TITLE_COL:
            return None
        if column == SIZE_COL:
            return self._color_size(self._rows[row][column])
        if column in (DECLARED_WIDTH_COL, DECLARED_HEIGHT_COL) and row not in self._declared_dimension_rows:
            return self._brushes.warn
        if column in (ACTUAL_WIDTH_COL, ACTUAL_HEIGHT_COL) and row not in self._actual_dimension_rows:
            return self._brushes.warn
        if column == CACHE_COL and not self._filled(self._rows[row][column]):
            return self._brushes.warn
        if column == LOADING_COL and not self._filled(self._rows[row][column]):
            return None
        if column == FETCH_PRIORITY_COL:
            status = ImagesModel._priority_status(self._rows[row][column])
            if status == "missing":
                return self._brushes.warn
            return None
        if column == FORMAT_HINT_COL:
            value = str(self._rows[row][column]).strip()
            if not value:
                return None
            return self._brushes.good if value == "Next-gen format" else self._brushes.warn
        if column == RESPONSIVE_COL and not self._filled(self._rows[row][column]):
            return None
        if column == DIAGNOSTIC_COL:
            value = str(self._rows[row][column]).strip()
            if value == "OK":
                return self._brushes.good
            return self._brushes.warn
        return None
