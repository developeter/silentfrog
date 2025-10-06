from __future__ import annotations
import re
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from .base import GenericModel, BR_GREEN, BR_YELLOW, BR_RED


class HreflangModel(GenericModel):
    def __init__(self, headers: List[str], rows: List[List[str]]) -> None:
        super().__init__(headers, rows)

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role == Qt.ItemDataRole.BackgroundRole:
            column = index.column()
            row = self._rows[index.row()]
            if column == 2:
                try:
                    code = int(re.search(r"\d{3}", str(row[2])).group(0))
                except Exception:
                    code = 0
                if 200 <= code < 300:
                    return BR_GREEN
                if 300 <= code < 400:
                    return BR_YELLOW
                return BR_RED
            if column == 3:
                return BR_GREEN if str(row[3]).strip().lower().startswith("y") else BR_RED
            if column == 4:
                return BR_GREEN if str(row[4]).strip().lower().startswith("y") else BR_YELLOW
        return None
