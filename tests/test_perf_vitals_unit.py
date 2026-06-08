from __future__ import annotations

from silentfrog.perf_crux import CruxData
from silentfrog.perf_vitals import (
    WebVitals,
    build_lab_performance_checks,
    build_performance_checks,
    vitals_from_cdp_metrics,
)


def _by_key(rows):
    return {r.key: r for r in rows}


def test_lab_checks_route_to_performance_area() -> None:
    rows = build_lab_performance_checks(WebVitals.empty())
    assert {r.area for r in rows} == {"Performance"}
    assert {r.key for r in rows} == {
        "perf_lcp",
        "perf_inp",
        "perf_cls",
        "perf_fcp",
        "perf_tbt",
        "perf_speed_index",
    }


def test_lab_check_good_threshold_for_lcp() -> None:
    rows = _by_key(build_lab_performance_checks(WebVitals(lcp_ms=1800)))
    assert rows["perf_lcp"].status == "good"
    assert "1800 ms" in rows["perf_lcp"].details


def test_lab_check_critical_threshold_for_lcp() -> None:
    rows = _by_key(build_lab_performance_checks(WebVitals(lcp_ms=5000)))
    assert rows["perf_lcp"].status == "critical"


def test_lab_check_missing_metric_emits_info() -> None:
    rows = _by_key(build_lab_performance_checks(WebVitals(lcp_ms=None)))
    assert rows["perf_lcp"].status == "info"
    assert "-" in rows["perf_lcp"].details


def test_lab_check_propagates_reason_on_info() -> None:
    vitals = WebVitals(reason="CDP unavailable")
    rows = _by_key(build_lab_performance_checks(vitals))
    assert rows["perf_lcp"].status == "info"
    assert "CDP unavailable" in rows["perf_lcp"].details


def test_cls_uses_unitless_threshold_and_format() -> None:
    rows = _by_key(build_lab_performance_checks(WebVitals(cls=0.05)))
    assert rows["perf_cls"].status == "good"
    assert "0.050" in rows["perf_cls"].details


def test_build_performance_checks_emits_three_crux_rows_when_no_field_data() -> None:
    rows = build_performance_checks(WebVitals.empty(), crux=None)
    crux_keys = {r.key for r in rows if r.key.startswith("perf_crux_")}
    assert crux_keys == {"perf_crux_lcp", "perf_crux_inp", "perf_crux_cls"}
    # Without field data the three rows route to info.
    for row in rows:
        if row.key.startswith("perf_crux_"):
            assert row.status == "info"


def test_build_performance_checks_uses_crux_values_when_has_field_data() -> None:
    crux = CruxData(
        lcp_p75_ms=2200,
        inp_p75_ms=180,
        cls_p75=0.05,
        has_field_data=True,
    )
    rows = _by_key(build_performance_checks(WebVitals.empty(), crux=crux))
    assert rows["perf_crux_lcp"].status == "good"
    assert rows["perf_crux_inp"].status == "good"
    assert rows["perf_crux_cls"].status == "good"


def test_vitals_from_cdp_metrics_parses_known_names() -> None:
    response = {
        "metrics": [
            {"name": "LargestContentfulPaint", "value": 1800},
            {"name": "FirstContentfulPaint", "value": 900},
            {"name": "CumulativeLayoutShift", "value": 0.04},
            {"name": "UnknownMetric", "value": 999},
        ]
    }
    vitals = vitals_from_cdp_metrics(response)
    assert vitals.lcp_ms == 1800
    assert vitals.fcp_ms == 900
    assert vitals.cls == 0.04
    assert vitals.inp_ms is None  # not in payload


def test_vitals_from_cdp_metrics_handles_non_dict() -> None:
    vitals = vitals_from_cdp_metrics(None)
    assert vitals.lcp_ms is None
    assert "non-dict" in vitals.reason


def test_webvitals_roundtrips_through_dict() -> None:
    original = WebVitals(lcp_ms=1500, cls=0.05, reason="ok")
    restored = WebVitals.from_raw(original.to_dict())
    assert restored == original
