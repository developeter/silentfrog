from __future__ import annotations

from collections import Counter
from typing import Dict, List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import _BaseModel

_PIXELS_PER_CHAR = 7.2
_TITLE_MIN, _TITLE_MAX = 200, 600
_DESCRIPTION_MIN, _DESCRIPTION_MAX = 400, 920
_WARN_MARGIN = 40


class MetaModel(_BaseModel):
    HEADERS = ["Name/Property", "Content", "Length"]

    def __init__(self, rows: List[List[str]]) -> None:
        processed = [list(row) for row in rows]
        self._brushes: StatusBrushPalette = status_brushes()

        names = [(row[0] or "").lower() for row in processed]
        counts = Counter(name for name in names if name)
        self._duplicate_rows = {idx for idx, name in enumerate(names) if name and counts[name] > 1}
        self._empty_rows = {idx for idx, row in enumerate(processed) if not str(row[1]).strip()}

        viewport_indices = [idx for idx, name in enumerate(names) if name == "viewport"]
        self._viewport_state: Dict[int, str] = {}
        if viewport_indices:
            for idx in viewport_indices:
                self._viewport_state[idx] = "good"
        else:
            processed.append(["viewport", "", "0"])
            names.append("viewport")
            self._viewport_state[len(processed) - 1] = "warn"

        charset_indices = [idx for idx, name in enumerate(names) if name == "charset"]
        self._charset_state: Dict[int, str] = {}
        if charset_indices:
            for idx in charset_indices:
                self._charset_state[idx] = "good" if idx <= 5 else "warn"
        else:
            processed.append(["charset", "", "0"])
            names.append("charset")
            self._charset_state[len(processed) - 1] = "warn"

        super().__init__(processed)

    def _to_int(self, value: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _pixel_brush(self, pixels: float, min_px: int, max_px: int):
        if pixels <= 0:
            return self._brushes.bad
        if pixels < min_px - _WARN_MARGIN or pixels > max_px + _WARN_MARGIN:
            return self._brushes.bad
        if pixels < min_px or pixels > max_px:
            return self._brushes.warn
        if pixels < min_px + _WARN_MARGIN or pixels > max_px - _WARN_MARGIN:
            return self._brushes.warn
        return self._brushes.good

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        row = index.row()
        col = index.column()
        name = (self._rows[row][0] or "").lower()
        content = self._rows[row][1] if len(self._rows[row]) > 1 else ""

        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)

        if role == Qt.ItemDataRole.BackgroundRole:
            if row in self._duplicate_rows and col == 0:
                return self._brushes.bad
            if row in self._empty_rows and col == 1:
                return self._brushes.bad

            if name == "title" and col == 2:
                length = self._to_int(self._rows[row][2])
                pixels = length * _PIXELS_PER_CHAR
                return self._pixel_brush(pixels, _TITLE_MIN, _TITLE_MAX)

            if name == "description" and col == 2:
                length = self._to_int(self._rows[row][2])
                pixels = length * _PIXELS_PER_CHAR
                return self._pixel_brush(pixels, _DESCRIPTION_MIN, _DESCRIPTION_MAX)

            if name == "robots" and col == 1:
                value = (content or "").lower()
                if "noindex" in value:
                    return self._brushes.bad
                if "nofollow" in value:
                    return self._brushes.warn
                return self._brushes.good

            if name == "viewport" and col == 0:
                state = self._viewport_state.get(row, "good")
                return self._brushes.warn if state == "warn" else self._brushes.good

            if name == "charset" and col == 0:
                state = self._charset_state.get(row, "warn")
                return self._brushes.warn if state == "warn" else self._brushes.good

        return super().data(index, role)
