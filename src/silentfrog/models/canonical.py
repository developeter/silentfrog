from __future__ import annotations
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from .base import GenericModel, BR_GREEN, BR_YELLOW, BR_RED


class CanonicalModel(GenericModel):
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
            value = str(self._rows[index.row()][1] or "")
            if key == "canonical url":
                return BR_GREEN if value and value != "—" else BR_RED
            if key == "self-referencing":
                return BR_GREEN if value.lower().startswith("y") else BR_RED
            if key == "multiple canonicals":
                return BR_RED if value.lower().startswith("y") else BR_GREEN
            if key == "canonical status":
                if value.isdigit() and 200 <= int(value) < 400:
                    return BR_GREEN
                return BR_YELLOW if value else BR_RED
        return None
