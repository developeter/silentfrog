
from __future__ import annotations
import re
from typing import List

from qtpy import QtCore
from qtpy.QtCore import Qt

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
    SIZE_COL,
    normalize_image_row,
)
from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class ImagesModel(GenericModel):
    def __init__(self, rows: List[List[str]]) -> None:
        normalized: List[List[str]] = []
        for row in rows:
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
        self._background_handlers = {
            ALT_COL: self._required_background,
            SIZE_COL: self._size_background,
            DECLARED_WIDTH_COL: self._declared_dimension_background,
            DECLARED_HEIGHT_COL: self._declared_dimension_background,
            ACTUAL_WIDTH_COL: self._actual_dimension_background,
            ACTUAL_HEIGHT_COL: self._actual_dimension_background,
            CACHE_COL: self._cache_background,
            FETCH_PRIORITY_COL: self._fetch_priority_background,
            FORMAT_HINT_COL: self._format_hint_background,
            DIAGNOSTIC_COL: self._diagnostic_background,
        }

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

    def _required_background(self, row: int, column: int):
        return self._color_required(self._rows[row][column])

    def _size_background(self, row: int, column: int):
        return self._color_size(self._rows[row][column])

    def _declared_dimension_background(self, row: int, column: int):
        return None if row in self._declared_dimension_rows else self._brushes.warn

    def _actual_dimension_background(self, row: int, column: int):
        return None if row in self._actual_dimension_rows else self._brushes.warn

    def _cache_background(self, row: int, column: int):
        return None if self._filled(self._rows[row][column]) else self._brushes.warn

    def _fetch_priority_background(self, row: int, column: int):
        status = ImagesModel._priority_status(self._rows[row][column])
        return self._brushes.warn if status == "missing" else None

    def _format_hint_background(self, row: int, column: int):
        value = str(self._rows[row][column]).strip()
        if not value:
            return None
        return self._brushes.good if value == "Next-gen format" else self._brushes.warn

    def _diagnostic_background(self, row: int, column: int):
        value = str(self._rows[row][column]).strip()
        return self._brushes.good if value == "OK" else self._brushes.warn

    def _background_for(self, row: int, column: int):
        handler = self._background_handlers.get(column)
        return handler(row, column) if handler else None

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role == Qt.ItemDataRole.BackgroundRole:
            return self._background_for(index.row(), index.column())
        return None
