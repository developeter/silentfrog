from __future__ import annotations
from PyQt5 import QtCore
from PyQt5.QtCore import Qt
from .base import _BaseModel, BR_GREEN, BR_RED


class MetaModel(_BaseModel):
    HEADERS = ["Name/Property", "Content", "Length"]

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role == Qt.ItemDataRole.BackgroundRole and index.column() == 2:
            key = self._rows[index.row()][0].lower()
            try:
                length = int(self._rows[index.row()][2])
            except ValueError:
                return BR_RED
            if key == "description":
                return BR_GREEN if 120 <= length <= 160 else BR_RED
            if key == "robots":
                content = (self._rows[index.row()][1] or "").lower()
                bad = any(tok in content for tok in ("noindex", "nofollow"))
                return BR_RED if bad else BR_GREEN
        return super().data(index, role)
