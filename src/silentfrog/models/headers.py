from __future__ import annotations

from difflib import SequenceMatcher

from qtpy import QtCore
from qtpy.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import _BaseModel


class HeaderModel(_BaseModel):
    HEADERS = ["Tag", "Text"]

    def __init__(self, rows: list[list[str]], title_text: str | None = None) -> None:
        super().__init__(rows)
        self._brushes: StatusBrushPalette = status_brushes()
        self._title_text = (title_text or "").strip().lower()
        self._refresh_state()

    def _refresh_state(self) -> None:
        self._h1_count = sum(1 for row in self._rows if row and str(row[0]).strip().lower() == "h1")
        self._empty_rows = {idx for idx, row in enumerate(self._rows) if not str(row[1]).strip()}
        self._jump_rows = set()
        prev_level = None
        for idx, row in enumerate(self._rows):
            tag = str(row[0]).strip().lower() if row else ""
            if tag.startswith("h") and len(tag) > 1 and tag[1:].isdigit():
                level = int(tag[1:])
                if prev_level is not None and abs(level - prev_level) > 1:
                    self._jump_rows.add(idx)
                prev_level = level

        self._title_warn_rows = set()
        if self._title_text:
            for idx, row in enumerate(self._rows):
                tag = str(row[0]).strip().lower() if row else ""
                if tag == "h1":
                    text = str(row[1]).strip().lower() if len(row) > 1 else ""
                    if text:
                        ratio = SequenceMatcher(None, text, self._title_text).ratio()
                        if ratio >= 0.9:
                            self._title_warn_rows.add(idx)

    def _after_sort(self) -> None:
        self._refresh_state()

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)

        if role == Qt.ItemDataRole.BackgroundRole and index.column() in (0, 1):
            row = index.row()
            tag = (self._rows[row][0] or "").strip().lower()

            if row in self._empty_rows:
                return self._brushes.bad
            if row in self._jump_rows and index.column() == 0:
                return self._brushes.warn
            if row in self._title_warn_rows and index.column() == 1:
                return self._brushes.warn
            if tag == "h1":
                return self._brushes.good if self._h1_count == 1 else self._brushes.warn
        return None
