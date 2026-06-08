from __future__ import annotations

from qtpy import QtCore, QtGui
from qtpy.QtCore import Qt

from ..crawl_types import KeywordEntry
from .base import _BaseModel


class KeywordModel(_BaseModel):
    HEADERS = [
        "Keyword",
        "Type",
        "Frequency",
        "Density %",
        "In Title",
        "Meta Description",
        "Headings",
        "1st Occurrence",
    ]

    def __init__(self, keywords: list[KeywordEntry]) -> None:
        self._keywords = list(keywords)
        super().__init__([self._to_row(entry) for entry in self._keywords])

    @staticmethod
    def _to_row(entry: KeywordEntry) -> list[str]:
        first = "-" if entry.first_position is None else str(entry.first_position + 1)
        density = f"{entry.density:.2f}"
        keyword_type = {1: "1-gram", 2: "2-gram", 3: "3-gram"}.get(entry.length, f"{entry.length}-gram")
        return [
            entry.term,
            keyword_type,
            str(entry.frequency),
            density,
            "Yes" if entry.in_title else "No",
            "Yes" if entry.in_description else "No",
            str(entry.heading_count),
            first,
        ]

    def sort(
        self,
        column: int,
        order: Qt.SortOrder = Qt.SortOrder.AscendingOrder,
    ) -> None:
        def _sort_key(entry: KeywordEntry):
            if column == 0:
                return entry.term.lower()
            if column == 1:
                return entry.length
            if column == 2:
                return entry.frequency
            if column == 3:
                return entry.density
            if column == 4:
                return entry.in_title
            if column == 5:
                return entry.in_description
            if column == 6:
                return entry.heading_count
            if column == 7:
                return entry.first_position if entry.first_position is not None else float("inf")
            return entry.term.lower()

        reverse = order == Qt.SortOrder.DescendingOrder
        try:
            self.layoutAboutToBeChanged.emit()
            self._keywords.sort(key=_sort_key, reverse=reverse)
            self._rows = [self._to_row(entry) for entry in self._keywords]
        finally:
            self.layoutChanged.emit()

    def data(self, index: QtCore.QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        entry = self._keywords[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role == Qt.ItemDataRole.TextAlignmentRole and column in {2, 3, 6, 7}:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            if column == 3 and entry.density_warning:
                return QtGui.QColor("#c62828")
            if column == 6 and entry.heading_count == 0:
                return QtGui.QColor("#b26a00")
        return super().data(index, role)


__all__ = ["KeywordModel"]
