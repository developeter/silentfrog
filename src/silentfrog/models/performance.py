from __future__ import annotations

from typing import List

from qtpy import QtCore
from qtpy.QtCore import Qt

from ..perf_metrics import performance_issue_tooltip
from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class PerformanceIssueModel(GenericModel):
    def __init__(self, headers: List[str], rows: List[List[str]], issue_keys: List[str]) -> None:
        super().__init__(headers, rows)
        self._issue_keys = issue_keys
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
            if 0 <= row < len(self._issue_keys):
                return performance_issue_tooltip(self._issue_keys[row])
            return None
        if role != Qt.ItemDataRole.BackgroundRole or index.column() != 1:
            return None
        severity = str(self._rows[index.row()][1] or "").strip().lower()
        if severity == "ok":
            return self._brushes.good
        if severity == "warning":
            return self._brushes.warn
        if severity == "critical":
            return self._brushes.bad
        return None

    def sort(
        self,
        column: int,
        order: QtCore.Qt.SortOrder = QtCore.Qt.SortOrder.AscendingOrder,
    ) -> None:
        paired = list(zip(self._rows, self._issue_keys))

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

        def _key(item: tuple[List[str], str]):
            row, _issue_key = item
            cell = row[column].strip()
            size_val = _size_to_bytes(cell)
            if size_val is not None:
                return (0, size_val)
            try:
                num_val = float(cell)
            except ValueError:
                try:
                    num_val = float(cell.replace(",", "."))
                except ValueError:
                    num_val = None
            else:
                return (0, num_val)
            if num_val is not None:
                return (0, num_val)
            return (1, cell.lower())

        try:
            self.layoutAboutToBeChanged.emit()
            paired.sort(key=_key, reverse=(order == QtCore.Qt.SortOrder.DescendingOrder))
            self._rows = [row for row, _issue_key in paired]
            self._issue_keys = [issue_key for _row, issue_key in paired]
        finally:
            self.layoutChanged.emit()


__all__ = ["PerformanceIssueModel"]
