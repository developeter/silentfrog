from __future__ import annotations

from typing import List

from qtpy import QtCore
from qtpy.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class IndexabilityModel(GenericModel):
    def __init__(self, headers: List[str], rows: List[List[str]]) -> None:
        super().__init__(headers, rows)
        self._brushes: StatusBrushPalette = status_brushes()
        self._background_handlers = {
            "final status": self._final_status_background,
            "redirect hops": self._redirect_hops_background,
            "crawl allowed by robots.txt": self._crawl_allowed_background,
            "meta / x-robots-tag": self._meta_robots_background,
            "index directive": self._index_directive_background,
            "follow directive": self._follow_directive_background,
            "canonical url": self._canonical_url_background,
            "canonical self-reference": self._canonical_self_background,
            "canonical status": self._canonical_status_background,
            "multiple canonicals": self._multiple_canonicals_background,
            "overall verdict": self._overall_verdict_background,
        }

    @staticmethod
    def _lower(value: object) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _int_value(value: object) -> int | None:
        text = str(value or "").strip()
        return int(text) if text.isdigit() else None

    def _final_status_background(self, value: object):
        status = self._int_value(value)
        if status is None:
            return self._brushes.bad
        if 200 <= status < 300:
            return self._brushes.good
        if 300 <= status < 400:
            return self._brushes.warn
        return self._brushes.bad

    def _redirect_hops_background(self, value: object):
        hops = self._int_value(value)
        if hops is None:
            return self._brushes.bad
        return self._brushes.good if hops == 0 else self._brushes.warn

    def _crawl_allowed_background(self, value: object):
        return self._brushes.good if self._lower(value).startswith("y") else self._brushes.bad

    def _meta_robots_background(self, value: object):
        lowered = self._lower(value)
        if lowered == "-":
            return self._brushes.warn
        if "noindex" in lowered or lowered == "none":
            return self._brushes.bad
        if "nofollow" in lowered:
            return self._brushes.warn
        return self._brushes.good

    def _index_directive_background(self, value: object):
        return self._brushes.good if self._lower(value) == "index" else self._brushes.bad

    def _follow_directive_background(self, value: object):
        return self._brushes.good if self._lower(value) == "follow" else self._brushes.warn

    def _canonical_url_background(self, value: object):
        return self._brushes.good if str(value or "").strip() not in {"", "-"} else self._brushes.warn

    def _canonical_self_background(self, value: object):
        return self._brushes.good if self._lower(value).startswith("y") else self._brushes.warn

    def _canonical_status_background(self, value: object):
        status = self._int_value(value)
        if status is not None and 200 <= status < 400:
            return self._brushes.good
        return self._brushes.warn if str(value or "").strip() == "-" else self._brushes.bad

    def _multiple_canonicals_background(self, value: object):
        return self._brushes.bad if self._lower(value).startswith("y") else self._brushes.good

    def _overall_verdict_background(self, value: object):
        status_map = {
            "indexable": self._brushes.good,
            "redirected": self._brushes.warn,
            "canonicalized elsewhere": self._brushes.warn,
            "indexable with warnings": self._brushes.warn,
        }
        return status_map.get(self._lower(value), self._brushes.bad)

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
        if role == Qt.ItemDataRole.BackgroundRole and index.column() == 1:
            return self._background_for(index.row())
        return None
