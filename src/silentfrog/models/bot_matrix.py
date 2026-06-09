"""Bot Matrix model (v1.1 N5a).

Surfaces the M1 19-bot AI crawl matrix as a coloured heatmap-style
table: rows = bots, the Verdict column is painted by status
(Allowed=green, Limited=yellow, Blocked=red). The underlying data
comes from ``CrawlPayload.ai_crawl`` rows produced by
``parsers_meta._ai_crawl_matrix``.

Unlike the existing ``AiTab`` (flat table), this model gives the user
an at-a-glance view of which engines can read the page. The drill-down
dialog (``BotMatrixTab._on_row_activated``) surfaces the per-bot
reasoning sitting in the Notes column.
"""

from __future__ import annotations

from collections.abc import Sequence

from qtpy import QtCore
from qtpy.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel

_VERDICT_COLUMN = 5


class BotMatrixModel(GenericModel):
    def __init__(
        self,
        headers: list[str],
        rows: list[list[str]],
        header_tooltips: Sequence[str] | None = None,
    ) -> None:
        super().__init__(headers, rows, header_tooltips)
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
            if 0 <= row < len(self._rows):
                notes = self._rows[row][-1] if len(self._rows[row]) > 6 else ""
                if notes:
                    return notes
            return None
        if role != Qt.ItemDataRole.BackgroundRole or index.column() != _VERDICT_COLUMN:
            return None
        verdict = str(self._rows[index.row()][_VERDICT_COLUMN] or "").strip().lower()
        if verdict == "allowed":
            return self._brushes.good
        if verdict == "limited":
            return self._brushes.warn
        if verdict == "blocked":
            return self._brushes.bad
        return None
