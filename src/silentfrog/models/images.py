from __future__ import annotations
import re
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt

from .base import GenericModel, BR_GREEN, BR_YELLOW, BR_RED


class ImagesModel(GenericModel):
    def __init__(self, rows: List[List[str]]) -> None:
        super().__init__(["Src", "Alt", "Title", "W", "H", "Peso"], rows)

    @staticmethod
    def _filled(value: object) -> bool:
        return bool(str(value).strip())

    @staticmethod
    def _bytes(human: object) -> int:
        text = str(human).strip()
        match = re.search(r"([\d.,]+)\s*([KMGT]?I?B)", text, re.I) if text else None
        if not match:
            return -1
        number = float(match.group(1).replace(",", "."))
        unit = match.group(2).upper()
        multiplier = {
            "B": 1,
            "KB": 1024,
            "MB": 1024 ** 2,
            "GB": 1024 ** 3,
            "KIB": 1024,
            "MIB": 1024 ** 2,
            "GIB": 1024 ** 3,
            "TB": 1024 ** 4,
            "TIB": 1024 ** 4,
        }.get(unit, 1)
        return int(number * multiplier)

    @staticmethod
    def _color_required(value: object):
        return BR_GREEN if ImagesModel._filled(value) else BR_YELLOW

    @staticmethod
    def _color_size(value: object):
        size = ImagesModel._bytes(value)
        if size < 0:
            return None
        if size > 500 * 1024:
            return BR_RED
        if size > 100 * 1024:
            return BR_YELLOW
        return BR_GREEN

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role != Qt.ItemDataRole.BackgroundRole:
            return None
        column = index.column()
        if column in (1, 2):
            return ImagesModel._color_required(self._rows[index.row()][column])
        if column == 5:
            return ImagesModel._color_size(self._rows[index.row()][column])
        return None
