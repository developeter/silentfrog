"""Group the per-page audit tabs into 5 user-goal buckets (v2.0 V19 Stage A).

The Single Page SEO window and the Site Crawl per-page detail dialog both build
the same ~18 tab widgets. This module regroups those widgets into nested
``QTabWidget``s — a top-level Overview (Recap) plus one inner tab widget per
bucket — without changing the widgets themselves.

The builder is **layout only**: callers construct the tab instances exactly as
before (keeping their references, ``.update(...)`` calls, and signal wiring) and
hand ``(label, widget)`` pairs here. Membership is keyed by label, so the two
surfaces' different construction orders still yield identical bucket grouping.
"""

from __future__ import annotations

from dataclasses import dataclass

from qtpy import QtCore, QtWidgets

from .theme import left_align_tab_bar

OVERVIEW_LABEL = "Recap"


@dataclass(frozen=True)
class BucketSpec:
    key: str
    title: str
    tab_labels: tuple[str, ...]


# The single source of truth for tab → bucket assignment (data, not control
# flow). Order here defines the on-screen order of buckets and of their
# sub-tabs. Every non-Recap leaf label must appear in exactly one bucket.
BUCKET_ORDER: tuple[BucketSpec, ...] = (
    BucketSpec(
        "indexability",
        "Indexability",
        ("Indexability", "Robots", "Canonical", "Redirect", "Hreflang", "Link"),
    ),
    BucketSpec(
        "content",
        "Content",
        ("Meta tag", "Header H1-H6", "Images", "Content quality", "Keywords"),
    ),
    BucketSpec("speed", "Speed", ("Performance",)),
    BucketSpec("trust", "Trust", ("Structured data", "Social", "SERP", "Accessibility")),
    BucketSpec("ai_geo", "AI/GEO", ("Bot Matrix", "AI Visibility")),
)


# Maps an ``AuditIssue.source`` to the leaf tab label its recap row should focus.
# Lives here (not in a window) so both the Single Page window and the Site Crawl
# detail dialog navigate with one source of truth.
RECAP_SOURCE_TABS: dict[str, str] = {
    "Meta": "Meta tag",
    "Headers": "Header H1-H6",
    "Images": "Images",
    "Links": "Link",
    "Redirect": "Redirect",
    "Canonical": "Canonical",
    "Indexability": "Indexability",
    "Robots": "Robots",
    "Hreflang": "Hreflang",
    "Structured data": "Structured data",
    "Structured eligibility": "Structured data",
    "Content quality": "Content quality",
    "AI Visibility": "AI Visibility",
    "Performance": "Performance",
    "Accessibility": "Accessibility",
}


@dataclass(frozen=True)
class TabEntry:
    label: str
    widget: QtWidgets.QWidget


@dataclass(frozen=True)
class _Location:
    outer_index: int
    inner: QtWidgets.QTabWidget
    inner_index: int


class BucketedTabs:
    """Handle over the assembled outer ``QTabWidget``.

    ``focus`` and ``contains`` let a caller drive recap navigation across the
    nested structure without knowing the bucket layout.
    """

    def __init__(
        self,
        outer: QtWidgets.QTabWidget,
        locations: dict[str, _Location],
        overview_label: str,
        overview_index: int,
    ) -> None:
        self._outer = outer
        self._locations = locations
        self._overview_label = overview_label
        self._overview_index = overview_index

    @property
    def outer(self) -> QtWidgets.QTabWidget:
        return self._outer

    def contains(self, leaf_label: str) -> bool:
        return leaf_label == self._overview_label or leaf_label in self._locations

    def focus(self, leaf_label: str) -> bool:
        """Select the bucket holding ``leaf_label`` and its sub-tab. Returns
        False for an unknown label (recap rows without a tab simply no-op)."""
        if leaf_label == self._overview_label:
            return self._focus_overview()
        location = self._locations.get(leaf_label)
        if location is None:
            return False
        self._outer.setCurrentIndex(location.outer_index)
        location.inner.setCurrentIndex(location.inner_index)
        return True

    def _focus_overview(self) -> bool:
        if self._overview_index < 0:
            return False
        self._outer.setCurrentIndex(self._overview_index)
        return True


def build_bucketed_tabs(
    host: QtWidgets.QTabWidget,
    entries: tuple[TabEntry, ...],
    *,
    overview_label: str = OVERVIEW_LABEL,
) -> BucketedTabs:
    """Populate ``host`` with the Overview tab and one inner tab widget per
    bucket, placing each entry under the bucket that claims its label."""
    _require_known_labels(entries, overview_label)
    by_label = {entry.label: entry.widget for entry in entries}
    overview_index = _add_overview(host, by_label, overview_label)
    locations = _add_buckets(host, by_label)
    return BucketedTabs(host, locations, overview_label, overview_index)


def _add_overview(host: QtWidgets.QTabWidget, by_label: dict[str, QtWidgets.QWidget], overview_label: str) -> int:
    overview = by_label.get(overview_label)
    if overview is None:
        return -1
    return host.addTab(overview, overview_label)


def _add_buckets(host: QtWidgets.QTabWidget, by_label: dict[str, QtWidgets.QWidget]) -> dict[str, _Location]:
    locations: dict[str, _Location] = {}
    for spec in BUCKET_ORDER:
        inner = QtWidgets.QTabWidget()
        _configure_tabwidget(inner)
        outer_index = host.addTab(inner, spec.title)
        _fill_bucket(inner, outer_index, spec, by_label, locations)
    return locations


def _fill_bucket(
    inner: QtWidgets.QTabWidget,
    outer_index: int,
    spec: BucketSpec,
    by_label: dict[str, QtWidgets.QWidget],
    locations: dict[str, _Location],
) -> None:
    for label in spec.tab_labels:
        widget = by_label.get(label)
        if widget is None:
            continue  # entry not supplied by this caller — skip defensively
        inner_index = inner.addTab(widget, label)
        locations[label] = _Location(outer_index, inner, inner_index)


def _configure_tabwidget(tabs: QtWidgets.QTabWidget) -> None:
    """Match the existing flat-tab look: scrollable, elided, left-aligned."""
    tabs.setUsesScrollButtons(True)
    tabs.setElideMode(QtCore.Qt.TextElideMode.ElideRight)
    tabs.tabBar().setExpanding(False)
    tabs.setStyleSheet("QTabBar::tab { min-width: 0px; }")
    left_align_tab_bar(tabs)


def _bucketed_labels() -> set[str]:
    return {label for spec in BUCKET_ORDER for label in spec.tab_labels}


def _require_known_labels(entries: tuple[TabEntry, ...], overview_label: str) -> None:
    known = _bucketed_labels() | {overview_label}
    unknown = [entry.label for entry in entries if entry.label not in known]
    if unknown:
        raise ValueError(f"tab labels not assigned to a bucket: {unknown}")


__all__ = [
    "BUCKET_ORDER",
    "OVERVIEW_LABEL",
    "RECAP_SOURCE_TABS",
    "BucketSpec",
    "BucketedTabs",
    "TabEntry",
    "build_bucketed_tabs",
]
