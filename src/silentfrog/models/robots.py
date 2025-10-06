from __future__ import annotations
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from .base import GenericModel, BR_GREEN, BR_RED, BR_YELLOW


class RobotsModel(GenericModel):
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
            value = (self._rows[index.row()][1] or "").lower()
            if key.startswith("meta"):
                return BR_RED if "noindex" in value else (BR_YELLOW if "nofollow" in value else BR_GREEN)
            if key.startswith("x-robots"):
                return BR_RED if "noindex" in value else (BR_YELLOW if "nofollow" in value else BR_GREEN)
            if key.startswith("disallow"):
                return BR_RED if value.strip() not in ("", "/") else BR_YELLOW
        return None
