"""Unit tests for the v2.0 V17 Semrush authority checks (§1.5-safe)."""

from __future__ import annotations

from silentfrog.integrations.semrush.checks import (
    AUTHORITY_AREA,
    build_semrush_authority_checks,
)
from silentfrog.integrations.semrush.types import SemrushMetrics

_KEYS = {
    "semrush_domain_authority_above_30",
    "semrush_organic_keywords_present",
    "semrush_organic_traffic_above_threshold",
    "semrush_backlinks_above_threshold",
    "semrush_referring_domains_diverse",
    "semrush_paid_signal_present",
}


def test_unmeasured_returns_single_info_row() -> None:
    rows = build_semrush_authority_checks(SemrushMetrics(measured=False))
    assert len(rows) == 1
    assert rows[0].status == "info"
    assert rows[0].area == AUTHORITY_AREA


def test_measured_emits_six_keys_in_authority_area() -> None:
    metrics = SemrushMetrics(
        domain_authority=55,
        organic_keywords=1500,
        organic_traffic=52000,
        backlinks_total=120000,
        referring_domains=3400,
        paid_keywords=30,
        paid_traffic=800,
        measured=True,
    )
    rows = build_semrush_authority_checks(metrics)
    assert {row.key for row in rows} == _KEYS
    assert all(row.area == AUTHORITY_AREA for row in rows)


def test_above_threshold_is_good() -> None:
    metrics = SemrushMetrics(
        domain_authority=55,
        organic_keywords=1500,
        organic_traffic=52000,
        backlinks_total=120000,
        referring_domains=3400,
        paid_keywords=30,
        measured=True,
    )
    by_key = {row.key: row for row in build_semrush_authority_checks(metrics)}
    assert by_key["semrush_domain_authority_above_30"].status == "good"
    assert by_key["semrush_organic_keywords_present"].status == "good"
    assert by_key["semrush_organic_traffic_above_threshold"].status == "good"
    assert by_key["semrush_backlinks_above_threshold"].status == "good"
    assert by_key["semrush_referring_domains_diverse"].status == "good"
    assert by_key["semrush_paid_signal_present"].status == "good"


def test_below_threshold_is_info_never_warning() -> None:
    # All-zero measured metrics: every signal is below its bar.
    metrics = SemrushMetrics(measured=True)
    rows = build_semrush_authority_checks(metrics)
    assert all(row.status == "info" for row in rows)
    assert all(row.status not in {"warning", "critical"} for row in rows)


def test_never_emits_warning_or_critical_anywhere() -> None:
    for metrics in (
        SemrushMetrics(measured=False),
        SemrushMetrics(measured=True),
        SemrushMetrics(domain_authority=10, organic_keywords=5, measured=True),
        SemrushMetrics(domain_authority=90, backlinks_total=9_000_000, measured=True),
    ):
        for row in build_semrush_authority_checks(metrics):
            assert row.status in {"good", "info"}
