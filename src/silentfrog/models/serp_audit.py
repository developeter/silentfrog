from __future__ import annotations
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from .base import GenericModel, BR_GREEN, BR_YELLOW, BR_RED


class SerpAuditModel(GenericModel):
    def __init__(self, headers: List[str], rows: List[List[str]]) -> None:
        super().__init__(headers, rows)

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role == Qt.ItemDataRole.BackgroundRole and index.column() == 1:
            key = (self._rows[index.row()][0] or "").lower()
            value = str(self._rows[index.row()][1] or "").strip().lower()
            if key == "missing":
                return BR_RED if value in ("yes", "true", "1") else BR_GREEN
            if key in ("> 60 chars", "< 30 chars", "> 561 px", "< 200 px", "equals h1"):
                return BR_YELLOW if value in ("yes", "true", "1") else BR_GREEN
            if key.startswith("length (chars)"):
                try:
                    length = int(value or "0")
                except Exception:
                    length = 0
                return BR_GREEN if 30 <= length <= 60 else BR_YELLOW
            if key.startswith("length (pixels)"):
                try:
                    pixels = int(value or "0")
                except Exception:
                    pixels = 0
                return BR_GREEN if 200 <= pixels <= 561 else BR_YELLOW
        return None
