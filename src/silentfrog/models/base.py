from __future__ import annotations

from collections.abc import Sequence

from qtpy import QtCore
from qtpy.QtCore import Qt


class _BaseModel(QtCore.QAbstractTableModel):
    HEADERS: list[str] = []

    def __init__(self, rows: list[list[str]]) -> None:
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

    def _after_sort(self) -> None:
        return None

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
                number = float(parts[0].replace(",", "."))
            except ValueError:
                return None
            return number * units.get(parts[1], 1)

        def _key(row: list[str]):
            cell = row[column].strip()
            size_value = _size_to_bytes(cell)
            if size_value is not None:
                return (0, size_value)
            try:
                numeric_value = float(cell)
            except ValueError:
                try:
                    numeric_value = float(cell.replace(",", "."))
                except ValueError:
                    numeric_value = None
            else:
                return (0, numeric_value)
            if numeric_value is not None:
                return (0, numeric_value)
            return (1, cell.lower())

        try:
            self.layoutAboutToBeChanged.emit()
            self._rows.sort(
                key=_key,
                reverse=(order == QtCore.Qt.SortOrder.DescendingOrder),
            )
            self._after_sort()
        finally:
            self.layoutChanged.emit()


class GenericModel(_BaseModel):
    def __init__(
        self,
        headers: list[str],
        rows: list[list[str]],
        header_tooltips: Sequence[str] | None = None,
    ) -> None:
        self.HEADERS = headers  # type: ignore[assignment]
        self._header_tooltips = list(header_tooltips or [])
        super().__init__(rows)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.ToolTipRole and orientation == QtCore.Qt.Horizontal:
            return self._header_tooltips[section] if section < len(self._header_tooltips) else None
        return super().headerData(section, orientation, role)


__all__ = ["_BaseModel", "GenericModel"]
