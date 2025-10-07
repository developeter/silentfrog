from __future__ import annotations
from typing import Any, List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt


class _BaseModel(QtCore.QAbstractTableModel):
    HEADERS: List[str] = []

    def __init__(self, rows: List[List[str]]) -> None:
        super().__init__()
        self._rows = rows

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return len(self._rows)

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return len(self.HEADERS)

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            row = self._rows[index.row()]
            return row[index.column()] if index.column() < len(row) else ""
        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole and orientation == QtCore.Qt.Horizontal:
            return self.HEADERS[section]
        return None


class GenericModel(_BaseModel):
    def __init__(self, headers: List[str], rows: List[List[str]]) -> None:
        self.HEADERS = headers  # type: ignore[assignment]
        super().__init__(rows)

    def sort(
        self,
        column: int,
        order: QtCore.Qt.SortOrder = QtCore.Qt.SortOrder.AscendingOrder,
    ) -> None:
        def _size_to_bytes(text: str) -> float | None:
            units = {
                "b": 1,
                "kb": 1_024,
                "mb": 1_048_576,
                "gb": 1_073_741_824,
                "kib": 1_024,
                "mib": 1_048_576,
                "gib": 1_073_741_824,
            }
            parts = text.lower().split()
            if len(parts) != 2:
                return None
            try:
                num = float(parts[0].replace(",", "."))
            except ValueError:
                return None
            return num * units.get(parts[1], 1)

        def _key(row: List[str]):
            cell = row[column].strip()
            size_val = _size_to_bytes(cell)
            if size_val is not None:
                return (0, size_val)
            try:
                num_val = float(cell)
            except ValueError:
                try:
                    num_val = float(cell.replace(',', '.'))
                except ValueError:
                    num_val = None
            else:
                return (0, num_val)
            if num_val is not None:
                return (0, num_val)
            return (1, cell.lower())

        try:
            self.layoutAboutToBeChanged.emit()
            self._rows.sort(
                key=_key,
                reverse=(order == QtCore.Qt.SortOrder.DescendingOrder),
            )
        finally:
            self.layoutChanged.emit()


__all__ = ["_BaseModel", "GenericModel"]

