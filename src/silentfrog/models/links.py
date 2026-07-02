from __future__ import annotations

from qtpy import QtCore
from qtpy.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel


class LinksModel(GenericModel):
    def __init__(self, rows: list[list[str]]) -> None:
        super().__init__(
            [
                "URL",
                "Anchor",
                "Type",
                "Rel",
                "Status",
                "Status note",
                "Section",
                "Heading",
                "TLD",
            ],
            rows,
        )
        self._brushes: StatusBrushPalette = status_brushes()

    # A link with no HTTP status was never probed (e.g. the Standard audit
    # profile bounds per-page link probing; Lightweight skips it). That is
    # "not measured", NOT an error — so it stays neutral and reads "Not probed",
    # distinct from a probed failure (status "0" / note "Fetch error", red).
    _STATUS_COLUMN = 4
    _NOTE_COLUMN = 5
    _UNPROBED_LABEL = "Not probed"
    _UNPROBED_NOTE = "Not checked (profile limit)"
    _UNPROBED_TIP = (
        "This link's HTTP status was not checked. The Standard audit profile probes only the first "
        "links on each page to stay fast; run a single-page (Deep) audit to check every link."
    )

    def _status_brush(self, value: object):
        text = str(value).strip()
        if not text:
            return None  # not probed — neutral, not an error
        try:
            code = int(text)
        except (TypeError, ValueError):
            return self._brushes.bad
        if 200 <= code < 300:
            return self._brushes.good
        if 300 <= code < 400:
            return self._brushes.warn
        return self._brushes.bad

    def _note_brush(self, value: object):
        note = str(value).strip().lower()
        mapping = {
            "ok": self._brushes.good,
            "redirect": self._brushes.warn,
            "client error": self._brushes.bad,
            "server error": self._brushes.bad,
            "fetch error": self._brushes.bad,
        }
        return mapping.get(note)

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if not index.isValid():
            return super().data(index, role)
        column = index.column()
        status_blank = not str(self._rows[index.row()][self._STATUS_COLUMN]).strip()
        if role == Qt.ItemDataRole.DisplayRole:
            if status_blank and column == self._STATUS_COLUMN:
                return self._UNPROBED_LABEL
            if status_blank and column == self._NOTE_COLUMN:
                return self._UNPROBED_NOTE
            return super().data(index, role)
        if role == Qt.ItemDataRole.ToolTipRole:
            if status_blank and column in (self._STATUS_COLUMN, self._NOTE_COLUMN):
                return self._UNPROBED_TIP
            return None
        if role != Qt.ItemDataRole.BackgroundRole:
            return None
        value = self._rows[index.row()][column]
        if column == self._STATUS_COLUMN:
            return self._status_brush(value)
        if column == self._NOTE_COLUMN:
            return self._note_brush(value)
        return None
