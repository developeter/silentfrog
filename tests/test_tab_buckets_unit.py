"""Unit tests for the V19 Stage A bucketed tab builder."""

from __future__ import annotations

import pytest
from qtpy import QtWidgets

from silentfrog.tab_buckets import (
    BUCKET_ORDER,
    OVERVIEW_LABEL,
    RECAP_SOURCE_TABS,
    TabEntry,
    build_bucketed_tabs,
)

# The 17 non-Recap leaf tabs that must each remain reachable under one bucket.
ALL_LEAVES = [
    "Meta tag",
    "Header H1-H6",
    "Images",
    "Social",
    "Link",
    "Redirect",
    "Canonical",
    "Indexability",
    "Robots",
    "Hreflang",
    "Structured data",
    "Content quality",
    "Keywords",
    "Bot Matrix",
    "AI Visibility",
    "Performance",
    "SERP",
    "Accessibility",
]


def test_bucket_order_covers_every_leaf_exactly_once() -> None:
    labels = [label for spec in BUCKET_ORDER for label in spec.tab_labels]
    assert sorted(labels) == sorted(ALL_LEAVES)
    assert len(labels) == len(set(labels))  # no leaf assigned to two buckets


def test_recap_source_map_targets_real_leaves() -> None:
    for target in set(RECAP_SOURCE_TABS.values()):
        assert target in ALL_LEAVES


def test_build_groups_into_overview_plus_five_buckets(qtbot) -> None:
    host = QtWidgets.QTabWidget()
    qtbot.addWidget(host)
    entries = tuple(TabEntry(label, QtWidgets.QWidget()) for label in [OVERVIEW_LABEL, *ALL_LEAVES])

    bucketed = build_bucketed_tabs(host, entries)

    assert host.count() == 6  # Overview + 5 buckets
    assert host.tabText(0) == "Recap"
    assert [host.tabText(i) for i in range(1, 6)] == [
        "Indexability",
        "Content",
        "Speed",
        "Trust",
        "AI/GEO",
    ]
    # every original leaf is reachable under exactly one inner bucket
    leaves = [host.widget(i).tabText(j) for i in range(1, host.count()) for j in range(host.widget(i).count())]
    assert sorted(leaves) == sorted(ALL_LEAVES)
    assert bucketed.contains("Recap")


def test_focus_selects_bucket_and_subtab(qtbot) -> None:
    host = QtWidgets.QTabWidget()
    qtbot.addWidget(host)
    entries = tuple(TabEntry(label, QtWidgets.QWidget()) for label in [OVERVIEW_LABEL, *ALL_LEAVES])
    bucketed = build_bucketed_tabs(host, entries)

    for label in ALL_LEAVES:
        assert bucketed.focus(label) is True
        inner = host.currentWidget()
        assert isinstance(inner, QtWidgets.QTabWidget)
        assert inner.tabText(inner.currentIndex()) == label

    assert bucketed.focus("Recap") is True
    assert host.currentIndex() == 0
    assert bucketed.focus("Nonexistent tab") is False


def test_build_rejects_a_label_outside_every_bucket(qtbot) -> None:
    host = QtWidgets.QTabWidget()
    qtbot.addWidget(host)
    with pytest.raises(ValueError):
        build_bucketed_tabs(host, (TabEntry("Bogus", QtWidgets.QWidget()),))
