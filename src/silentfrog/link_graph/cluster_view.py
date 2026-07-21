"""QGraphicsView renderer for the content-cluster ("topic map") (v3 G5).

Cloned from ``graph_view.py``'s ``LinkGraphView`` chrome (dark canvas,
wheel-zoom, ScrollHandDrag pan, ``node_clicked`` signal, fit()/reset_zoom())
so the two dialogs feel like one tool. Dots are the PCA-projected topic
vector for each page, coloured by k-means cluster id from a fixed 8-colour
palette; a graph has GEO-Score bands, a topic map has no such ordinal
signal, so colour here means "same cluster", nothing more.
"""

from __future__ import annotations

from collections.abc import Sequence

from qtpy import QtCore, QtGui, QtWidgets

from ..content_clusters import ClusterMap, ClusterPoint

_CANVAS = 1600.0
_DOT_R = 6.0
# Fixed, distinct 8-colour palette (cluster id -> colour by index, wrapping).
_PALETTE: tuple[QtGui.QColor, ...] = (
    QtGui.QColor("#2ecc71"),
    QtGui.QColor("#3498db"),
    QtGui.QColor("#e74c3c"),
    QtGui.QColor("#f1c40f"),
    QtGui.QColor("#9b59b6"),
    QtGui.QColor("#1abc9c"),
    QtGui.QColor("#e67e22"),
    QtGui.QColor("#95a5a6"),
)


def _cluster_color(cluster: int) -> QtGui.QColor:
    return _PALETTE[cluster % len(_PALETTE)]


def _point_bounds(points: Sequence[ClusterPoint]) -> tuple[float, float, float, float]:
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return min(xs), max(xs), min(ys), max(ys)


def _scaled_pos(point: ClusterPoint, bounds: tuple[float, float, float, float]) -> tuple[float, float]:
    """PCA coordinates have an arbitrary scale/origin; rescale to the fixed
    canvas the way the link-graph view scales its [0,1]-normalized layout."""
    min_x, max_x, min_y, max_y = bounds
    span_x = (max_x - min_x) or 1.0
    span_y = (max_y - min_y) or 1.0
    return (point.x - min_x) / span_x * _CANVAS, (point.y - min_y) / span_y * _CANVAS


class _DotItem(QtWidgets.QGraphicsEllipseItem):
    def __init__(self, url: str, title: str, cluster: int, on_click) -> None:
        super().__init__(-_DOT_R, -_DOT_R, _DOT_R * 2, _DOT_R * 2)
        self._url = url
        self._on_click = on_click
        self.setBrush(QtGui.QBrush(_cluster_color(cluster)))
        self.setPen(QtGui.QPen(QtGui.QColor("#202124"), 0.5))
        self.setToolTip(title or url)
        self.setZValue(2)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if self._on_click is not None:
            self._on_click(self._url)
        super().mousePressEvent(event)


class ClusterMapView(QtWidgets.QGraphicsView):
    node_clicked = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._scene.setBackgroundBrush(QtGui.QBrush(QtGui.QColor("#15171a")))

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)

    def fit(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if not rect.isNull():
            self.fitInView(rect, QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def reset_zoom(self) -> None:
        self.resetTransform()
        self.fit()

    def set_cluster_map(self, cluster_map: ClusterMap) -> None:
        self._scene.clear()
        if not cluster_map.points:
            return
        bounds = _point_bounds(cluster_map.points)
        for point in cluster_map.points:
            item = _DotItem(point.url, point.title, point.cluster, self.node_clicked.emit)
            item.setPos(*_scaled_pos(point, bounds))
            self._scene.addItem(item)
        self.setSceneRect(self._scene.itemsBoundingRect())
        self.fitInView(self._scene.itemsBoundingRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)


__all__ = ["ClusterMapView"]
