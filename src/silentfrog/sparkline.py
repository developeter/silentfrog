"""Pure-Qt sparkline widget (v1.1 N5c).

Tiny polyline chart with no QChart dependency — pure paintEvent. Used
to overlay a GEO Score history on the AI Visibility tab. Range is
auto-scaled to [min, max] of the series; an empty series renders a
centred "no history yet" string.
"""

from __future__ import annotations

from qtpy import QtCore, QtGui, QtWidgets


class Sparkline(QtWidgets.QWidget):
    """Minimal sparkline. Call ``set_values([int, int, ...])`` to update."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: list[int] = []
        self.setMinimumSize(QtCore.QSize(120, 28))
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._line_color = QtGui.QColor("#2ecc71")
        self._dim_color = QtGui.QColor("#888888")

    def set_values(self, values: list[int]) -> None:
        self._values = [int(v) for v in values]
        self.update()

    def values(self) -> list[int]:
        return list(self._values)

    def sizeHint(self) -> QtCore.QSize:  # type: ignore[override]
        return QtCore.QSize(180, 32)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:  # type: ignore[override]
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        # Frame: subtle bottom baseline.
        baseline_pen = QtGui.QPen(self._dim_color, 1)
        painter.setPen(baseline_pen)
        painter.drawLine(rect.left(), rect.bottom() - 1, rect.right(), rect.bottom() - 1)
        if not self._values:
            painter.setPen(self._dim_color)
            painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, "no history yet")
            painter.end()
            return
        if len(self._values) == 1:
            painter.setPen(self._dim_color)
            value = self._values[0]
            painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, f"score {value}")
            painter.end()
            return
        # Auto-scale to the y range of the values.
        ymin = min(self._values)
        ymax = max(self._values)
        ypad = max(1, (ymax - ymin) // 10)
        ymin_padded = ymin - ypad
        yrange = max(1, (ymax + ypad) - ymin_padded)
        usable = rect.adjusted(2, 2, -2, -4)
        step = usable.width() / (len(self._values) - 1)
        path = QtGui.QPainterPath()
        for idx, value in enumerate(self._values):
            x = usable.left() + step * idx
            normalised = (value - ymin_padded) / yrange
            y = usable.bottom() - normalised * usable.height()
            if idx == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QtGui.QPen(self._line_color, 2))
        painter.drawPath(path)
        painter.end()


__all__ = ["Sparkline"]
