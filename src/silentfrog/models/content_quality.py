from __future__ import annotations

from qtpy import QtCore
from qtpy.QtCore import Qt

from ..content_quality import content_quality_tooltip
from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class ContentQualityModel(GenericModel):
    def __init__(self, headers: list[str], rows: list[list[str]]) -> None:
        super().__init__(headers, rows)
        self._brushes: StatusBrushPalette = status_brushes()
        self._background_handlers = {
            "page language": self._page_language_background,
            "title present": self._title_present_background,
            "meta description present": self._meta_description_background,
            "h1 count": self._h1_count_background,
            "h2-h6 count": self._subheading_count_background,
            "title / h1 alignment": self._title_alignment_background,
            "intro paragraph": self._intro_background,
            "thin-content risk": self._thin_content_background,
            "heading structure": self._heading_structure_background,
            "overall verdict": self._overall_verdict_background,
        }

    @staticmethod
    def _lower(value: object) -> str:
        return str(value or "").strip().lower()

    def _page_language_background(self, value: object):
        return self._brushes.warn if self._lower(value) == "not declared" else None

    def _title_present_background(self, value: object):
        return self._brushes.good if self._lower(value) == "yes" else self._brushes.bad

    def _meta_description_background(self, value: object):
        return self._brushes.good if self._lower(value) == "yes" else self._brushes.warn

    def _h1_count_background(self, value: object):
        if str(value) == "1":
            return self._brushes.good
        if str(value) == "0":
            return self._brushes.bad
        return self._brushes.warn

    def _subheading_count_background(self, value: object):
        return self._brushes.warn if str(value) == "0" else None

    def _title_alignment_background(self, value: object):
        lowered = self._lower(value)
        status_map = {
            "aligned": self._brushes.good,
            "exact match": self._brushes.good,
            "different": self._brushes.warn,
            "missing": self._brushes.bad,
        }
        return status_map.get(lowered)

    def _intro_background(self, value: object):
        return self._brushes.good if self._lower(value) == "present" else self._brushes.warn

    def _thin_content_background(self, value: object):
        status_map = {
            "low": self._brushes.good,
            "medium": self._brushes.warn,
            "high": self._brushes.bad,
        }
        return status_map.get(self._lower(value))

    def _heading_structure_background(self, value: object):
        status_map = {
            "good": self._brushes.good,
            "multiple h1s": self._brushes.warn,
            "no subheadings": self._brushes.warn,
            "missing h1": self._brushes.bad,
        }
        return status_map.get(self._lower(value))

    def _overall_verdict_background(self, value: object):
        status_map = {
            "strong": self._brushes.good,
            "needs work": self._brushes.warn,
            "weak": self._brushes.bad,
        }
        return status_map.get(self._lower(value))

    def _background_for(self, row: int):
        key = str(self._rows[row][0] or "").lower()
        value = self._rows[row][1] or ""
        handler = self._background_handlers.get(key)
        return handler(value) if handler else None

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role == Qt.ItemDataRole.ToolTipRole:
            return content_quality_tooltip(str(self._rows[index.row()][0] or ""))
        if role == Qt.ItemDataRole.BackgroundRole and index.column() == 1:
            return self._background_for(index.row())
        return None


__all__ = ["ContentQualityModel"]
