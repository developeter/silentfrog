from __future__ import annotations

from typing import List, Sequence

from qtpy import QtCore
from qtpy.QtCore import Qt

from ..ai_visibility import ai_visibility_check_tooltip
from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class AiVisibilityModel(GenericModel):
    def __init__(
        self,
        headers: List[str],
        rows: List[List[str]],
        check_keys: Sequence[str],
        header_tooltips: Sequence[str] | None = None,
    ) -> None:
        super().__init__(headers, rows, header_tooltips)
        self._check_keys = list(check_keys)
        self._brushes: StatusBrushPalette = status_brushes()

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role == Qt.ItemDataRole.ToolTipRole:
            row = index.row()
            if 0 <= row < len(self._check_keys):
                return ai_visibility_check_tooltip(self._check_keys[row])
            return None
        if role != Qt.ItemDataRole.BackgroundRole or index.column() != 2:
            return None
        status = str(self._rows[index.row()][2] or "").strip().lower()
        if status == "good":
            return self._brushes.good
        if status == "warning":
            return self._brushes.warn
        if status == "critical":
            return self._brushes.bad
        return None

    def sort(
        self,
        column: int,
        order: QtCore.Qt.SortOrder = QtCore.Qt.SortOrder.AscendingOrder,
    ) -> None:
        paired = list(zip(self._rows, self._check_keys))

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

        def _key(item: tuple[List[str], str]):
            row, _check_key = item
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
            paired.sort(key=_key, reverse=(order == QtCore.Qt.SortOrder.DescendingOrder))
            self._rows = [row for row, _check_key in paired]
            self._check_keys = [check_key for _row, check_key in paired]
        finally:
            self.layoutChanged.emit()


__all__ = ["AiVisibilityModel"]
