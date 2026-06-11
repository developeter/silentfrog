"""QGraphicsView renderer for the link graph (v2.0 V9).

Nodes are circles coloured by GEO Score band (green >=80, yellow 60-79,
red <60, grey unknown); edges are thin lines. Positions come from the
force-directed ``layout_positions``. Clicking a node emits ``node_clicked``
so the host can drill into that URL.
"""

from __future__ import annotations

from qtpy import QtCore, QtGui, QtWidgets

from .graph_model import LinkGraph
from .layout import layout_positions

_CANVAS = 1600.0
_NODE_R = 6.0
_GOOD = QtGui.QColor("#2ecc71")
_WARN = QtGui.QColor("#f1c40f")
_BAD = QtGui.QColor("#e74c3c")
_DIM = QtGui.QColor("#9aa0a6")
_EDGE = QtGui.QColor(150, 150, 150, 90)


def _band_color(score: int) -> QtGui.QColor:
    if score >= 80:
        return _GOOD
    if score >= 60:
        return _WARN
    if score > 0:
        return _BAD
    return _DIM


class _NodeItem(QtWidgets.QGraphicsEllipseItem):
    def __init__(self, url: str, score: int, on_click) -> None:
        super().__init__(-_NODE_R, -_NODE_R, _NODE_R * 2, _NODE_R * 2)
        self._url = url
        self._on_click = on_click
        self.setBrush(QtGui.QBrush(_band_color(score)))
        self.setPen(QtGui.QPen(QtGui.QColor("#202124"), 0.5))
        self.setToolTip(f"{url}\nGEO Score: {score}")
        self.setZValue(2)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if self._on_click is not None:
            self._on_click(self._url)
        super().mousePressEvent(event)


class LinkGraphView(QtWidgets.QGraphicsView):
    node_clicked = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)

    def set_graph(self, graph: LinkGraph) -> None:
        self._scene.clear()
        positions = layout_positions(graph)
        if not positions:
            return
        self._draw_edges(graph, positions)
        self._draw_nodes(graph, positions)
        self.setSceneRect(self._scene.itemsBoundingRect())
        self.fitInView(self._scene.itemsBoundingRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def _draw_edges(self, graph: LinkGraph, positions: dict[str, tuple[float, float]]) -> None:
        pen = QtGui.QPen(_EDGE, 0.7)
        for parent, child in graph.edges:
            if parent not in positions or child not in positions:
                continue
            px, py = positions[parent]
            cx, cy = positions[child]
            line = self._scene.addLine(px * _CANVAS, py * _CANVAS, cx * _CANVAS, cy * _CANVAS, pen)
            line.setZValue(1)

    def _draw_nodes(self, graph: LinkGraph, positions: dict[str, tuple[float, float]]) -> None:
        for node in graph.nodes:
            if node.url not in positions:
                continue
            x, y = positions[node.url]
            item = _NodeItem(node.url, node.score, self.node_clicked.emit)
            item.setPos(x * _CANVAS, y * _CANVAS)
            self._scene.addItem(item)


__all__ = ["LinkGraphView"]
