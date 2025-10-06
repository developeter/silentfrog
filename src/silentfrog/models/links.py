from __future__ import annotations
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor

from .base import GenericModel


class LinksModel(GenericModel):
    def __init__(self, rows: List[List[str]]) -> None:
        super().__init__(["URL", "Anchor", "Follow ?", "Status"], rows)

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role == Qt.ItemDataRole.BackgroundRole and index.column() == 3:
            green = QBrush(QColor(0, 180, 0, 60))
            yellow = QBrush(QColor(255, 200, 0, 60))
            red = QBrush(QColor(200, 0, 0, 60))
            try:
                code = int(self._rows[index.row()][3])
            except ValueError:
                code = 0
            if 200 <= code < 300:
                return green
            if 300 <= code < 400:
                return yellow
            return red
        return None
