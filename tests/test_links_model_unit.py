"""Unit tests for LinksModel status colouring + display (B7).

A link with no HTTP status was never probed (the Standard audit profile bounds
per-page link probing; Lightweight skips it). That must render as a neutral
"Not probed" cell — NOT the red error colour used for a probed failure.
"""

from __future__ import annotations

from qtpy.QtCore import Qt

from silentfrog.models.links import LinksModel
from silentfrog.theme import status_brushes


def _row(status: str, note: str = "") -> list[str]:
    return ["https://e.com/x", "anchor", "internal", "", status, note, "", "", "e.com"]


def _status_background(model: LinksModel, row: int):
    index = model.index(row, LinksModel._STATUS_COLUMN)
    return model.data(index, Qt.ItemDataRole.BackgroundRole)


def _status_display(model: LinksModel, row: int):
    index = model.index(row, LinksModel._STATUS_COLUMN)
    return model.data(index, Qt.ItemDataRole.DisplayRole)


def _note_display(model: LinksModel, row: int):
    index = model.index(row, LinksModel._NOTE_COLUMN)
    return model.data(index, Qt.ItemDataRole.DisplayRole)


def test_unprobed_blank_status_is_neutral_and_labelled(qtbot) -> None:
    model = LinksModel([_row("")])  # never probed
    assert _status_background(model, 0) is None  # neutral, not the red/error brush
    assert _status_display(model, 0) == "Not probed"
    # the Status note explains WHY, for a non-technical reader, plus a fuller tooltip
    assert _note_display(model, 0) == "Not checked (profile limit)"
    tip = model.data(model.index(0, LinksModel._STATUS_COLUMN), Qt.ItemDataRole.ToolTipRole)
    assert tip and "Standard audit profile" in tip


def test_probed_failure_status_zero_stays_red(qtbot) -> None:
    brushes = status_brushes()
    model = LinksModel([_row("0", "Fetch error")])  # probed, failed
    assert _status_background(model, 0) is brushes.bad
    assert _status_display(model, 0) == "0"  # real failures are not relabelled
    assert _note_display(model, 0) == "Fetch error"  # a real note is left untouched


def test_status_brush_buckets(qtbot) -> None:
    brushes = status_brushes()
    model = LinksModel([_row("200"), _row("301"), _row("404")])
    assert _status_background(model, 0) is brushes.good
    assert _status_background(model, 1) is brushes.warn
    assert _status_background(model, 2) is brushes.bad
    assert _status_display(model, 0) == "200"
