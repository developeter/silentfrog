from __future__ import annotations
import re
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from .base import GenericModel, BR_GREEN, BR_YELLOW, BR_RED


class RedirectModel(GenericModel):
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
            if key == "hop count":
                try:
                    hops = int(value)
                except Exception:
                    hops = 0
                if hops == 0:
                    return BR_GREEN
                if hops <= 2:
                    return BR_YELLOW
                return BR_RED
            if key == "final status":
                match = re.search(r"\d{3}", value)
                code = int(match.group(0)) if match else 0
                if 200 <= code < 300:
                    return BR_GREEN
                if 300 <= code < 400:
                    return BR_YELLOW
                return BR_RED
            if key == "loop detected":
                return BR_RED if value.lower().startswith("y") else BR_GREEN
            if key == "redirect chain":
                return BR_YELLOW if "→" in value or "->" in value else BR_GREEN
        return None
