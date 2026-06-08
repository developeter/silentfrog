from __future__ import annotations

from collections import Counter

from qtpy import QtCore
from qtpy.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import _BaseModel

_PIXELS_PER_CHAR = 7.2
_TITLE_MIN, _TITLE_MAX = 200, 600
_DESCRIPTION_MIN, _DESCRIPTION_MAX = 400, 920
_WARN_MARGIN = 40


class MetaModel(_BaseModel):
    HEADERS = ["Name/Property", "Content", "Length"]

    def __init__(self, rows: list[list[str]], add_placeholders: bool = True) -> None:
        processed = [list(row) for row in rows]
        self._brushes: StatusBrushPalette = status_brushes()
        self._add_placeholders = add_placeholders

        names = [(row[0] or "").lower() for row in processed]
        viewport_indices = [idx for idx, name in enumerate(names) if name == "viewport"]
        if viewport_indices:
            pass
        elif add_placeholders:
            processed.append(["viewport", "", "0"])
            names.append("viewport")

        charset_indices = [idx for idx, name in enumerate(names) if name == "charset"]
        if charset_indices:
            pass
        elif add_placeholders:
            processed.append(["charset", "", "0"])
            names.append("charset")

        super().__init__(processed)
        self._refresh_state()

    def _refresh_state(self) -> None:
        names = [(row[0] or "").lower() for row in self._rows]
        counts = Counter(name for name in names if name)
        self._duplicate_rows = {idx for idx, name in enumerate(names) if name and counts[name] > 1}
        self._empty_rows = {idx for idx, row in enumerate(self._rows) if not str(row[1]).strip()}
        self._viewport_state = {idx: "good" for idx, name in enumerate(names) if name == "viewport"}
        self._charset_state = {
            idx: ("good" if idx <= 5 else "warn") for idx, name in enumerate(names) if name == "charset"
        }

    def _after_sort(self) -> None:
        self._refresh_state()

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
