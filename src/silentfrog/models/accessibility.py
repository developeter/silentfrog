from __future__ import annotations

from qtpy import QtCore
from qtpy.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes
from .base import GenericModel

_IMPACT_COLUMN = 1

# axe-core impact tiers -> brush. Mirrors the §1.5 severity mapping in
# audit_issues._IMPACT_SEVERITY: only critical/serious get a tint;
# moderate/minor stay untinted (info-level, never penalised).
_IMPACT_BRUSH_KEYS = {
    "critical": "bad",
    "serious": "warn",
}


class AccessibilityModel(GenericModel):
    def __init__(self, headers: list[str], rows: list[list[str]]) -> None:
        super().__init__(headers, rows)
        self._brushes: StatusBrushPalette = status_brushes()

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole:
            return super().data(index, role)
        if role == Qt.ItemDataRole.BackgroundRole and index.column() == _IMPACT_COLUMN:
            impact = str(self._rows[index.row()][_IMPACT_COLUMN] or "").strip().lower()
            brush_key = _IMPACT_BRUSH_KEYS.get(impact)
            return getattr(self._brushes, brush_key) if brush_key else None
        return None


__all__ = ["AccessibilityModel"]
