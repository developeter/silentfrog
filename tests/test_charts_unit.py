"""Unit tests for the optional charts seam (V19 Stage A).

The base install ships no pyqtgraph, so ``make_distribution_chart`` returns the
pure-Qt text fallback and these tests stay green without the ``charts`` extra.
The pyqtgraph rendering is exercised only when the extra is installed (the final
test skips otherwise), so base CI never requires the optional dependency.
"""

from __future__ import annotations

import pytest
from qtpy import QtWidgets

import silentfrog.charts as charts
from silentfrog.charts import bin_scores, charts_available, make_distribution_chart


def test_charts_available_matches_optional_import() -> None:
    assert charts_available() is (charts.pg is not None)


def test_bin_scores_buckets_into_fixed_bands() -> None:
    assert bin_scores([0, 10, 25, 60, 79, 80, 95, 100]) == {
        "0-20": 2,
        "20-40": 1,
        "40-60": 0,
        "60-80": 2,
        "80-100": 3,
    }


def test_bin_scores_empty_series_keeps_zeroed_bands() -> None:
    assert bin_scores([]) == {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}


def test_fallback_chart_shows_counts_when_pyqtgraph_absent(qtbot) -> None:
    if charts_available():
        pytest.skip("pyqtgraph installed; the text fallback path is not exercised")
    chart = make_distribution_chart("HTTP status")
    qtbot.addWidget(chart)
    chart.set_distribution({"200": 3, "404": 1})
    text = " ".join(label.text() for label in chart.findChildren(QtWidgets.QLabel))
    assert "200: 3" in text
    assert "404: 1" in text


def test_fallback_chart_empty_distribution(qtbot) -> None:
    if charts_available():
        pytest.skip("pyqtgraph installed")
    chart = make_distribution_chart("GEO score")
    qtbot.addWidget(chart)
    chart.set_distribution({})
    text = " ".join(label.text() for label in chart.findChildren(QtWidgets.QLabel))
    assert "No data yet." in text


@pytest.mark.skipif(not charts_available(), reason="requires the optional [charts] extra")
def test_pyqtgraph_chart_used_when_extra_installed(qtbot) -> None:
    import pyqtgraph as pg

    chart = make_distribution_chart("HTTP status")
    qtbot.addWidget(chart)
    chart.set_distribution({"200": 2})
    assert chart.findChild(pg.PlotWidget) is not None
