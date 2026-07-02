"""Optional PyQtGraph charts with a pure-Qt text fallback (v2.0 V19 Stage A).

``pyqtgraph`` is an optional dependency (the ``charts`` extra). It is imported
once, guarded; when it is absent the factory returns a small text-summary widget
so the base install shows the same numbers without the dependency. This module is
the only place that imports pyqtgraph.
"""

from __future__ import annotations

from qtpy import QtCore, QtWidgets

try:
    import pyqtgraph as pg  # pragma: no cover - importable only with the [charts] extra
except Exception:  # the extra is absent in a base install
    pg = None


def charts_available() -> bool:
    """True when the optional pyqtgraph backend is importable."""
    return pg is not None


def bin_scores(scores: list[int], width: int = 20) -> dict[str, int]:
    """Bucket GEO scores (0-100) into fixed-width bands for a bar chart.

    Bands are lower-bound inclusive; the final band absorbs a perfect 100.
    """
    lows = list(range(0, 100, width))
    labels = [f"{low}-{min(100, low + width)}" for low in lows]
    counts = dict.fromkeys(labels, 0)
    for score in scores:
        clamped = max(0, min(100, score))
        counts[labels[min(len(lows) - 1, clamped // width)]] += 1
    return counts


class DistributionChart(QtWidgets.QWidget):
    """A labelled bar chart of ``{category: count}``.

    Concrete subclasses render with pyqtgraph or as plain text; callers depend
    only on :meth:`set_distribution`.
    """

    def set_distribution(self, distribution: dict[str, int]) -> None:
        raise NotImplementedError


class _TextDistribution(DistributionChart):
    """Fallback when pyqtgraph is absent: a titled summary card, so the numbers
    read as an intentional panel rather than stray text."""

    def __init__(self, title: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chartFallbackCard")
        # Translucent border reads on both the dark and light themes without
        # coupling charts.py to the theme palette.
        self.setStyleSheet("#chartFallbackCard { border: 1px solid rgba(127,127,127,0.45); border-radius: 6px; }")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        heading = QtWidgets.QLabel(title)
        heading.setStyleSheet("font-weight: 600;")
        self._body = QtWidgets.QLabel("No data yet.")
        self._body.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(heading)
        layout.addWidget(self._body)
        layout.addStretch(1)

    def set_distribution(self, distribution: dict[str, int]) -> None:
        if not distribution:
            self._body.setText("No data yet.")
            return
        self._body.setText("\n".join(f"{label}: {count}" for label, count in distribution.items()))


class _PgDistribution(DistributionChart):  # pragma: no cover - needs the [charts] extra
    """pyqtgraph bar chart used when the optional backend is installed."""

    def __init__(self, title: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._plot = pg.PlotWidget(title=title)
        self._plot.setMenuEnabled(False)
        self._plot.setMouseEnabled(x=False, y=False)
        layout.addWidget(self._plot)

    def set_distribution(self, distribution: dict[str, int]) -> None:
        self._plot.clear()
        labels = list(distribution)
        xs = list(range(len(labels)))
        heights = [distribution[label] for label in labels]
        self._plot.addItem(pg.BarGraphItem(x=xs, height=heights, width=0.6, brush="#2ecc71"))
        self._plot.getAxis("bottom").setTicks([list(zip(xs, labels, strict=False))])


def make_distribution_chart(title: str) -> DistributionChart:
    """A bar-chart widget — pyqtgraph when the ``charts`` extra is installed, else
    a plain-text fallback. Both honour :meth:`DistributionChart.set_distribution`."""
    if pg is None:
        return _TextDistribution(title)
    return _PgDistribution(title)  # pragma: no cover - needs the [charts] extra


__all__ = ["DistributionChart", "bin_scores", "charts_available", "make_distribution_chart"]
