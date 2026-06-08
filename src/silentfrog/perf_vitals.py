"""Lab Core Web Vitals via Playwright's CDP API (v1.1 N1).

This module is the lab-data half of N1. It shares the M4 Playwright
session — `collect_web_vitals(page, timeout_seconds)` accepts the
existing `page` object so a single browser launch produces both the
SSR-parity diff AND the lab CWV reading.

Field data (CrUX P75 from real Chrome users) lives in the companion
module ``perf_crux.py``. ``build_performance_checks`` consumes both
and emits one row per metric in the new ``Performance`` area of the
AI Visibility tab.

Per the plan §1.5 myth alignment: when Playwright is not installed
OR a metric cannot be read, the row reports ``info`` ("not measured")
and does NOT down-weight the GEO Score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .crawl_types import AiVisibilityCheck


@dataclass(frozen=True)
class WebVitals:
    """Six Core Web Vitals + supplementary metrics, all optional.

    Any field that couldn't be measured stays ``None``; ``reason``
    explains why for debugging.
    """

    lcp_ms: float | None = None
    inp_ms: float | None = None
    cls: float | None = None
    fcp_ms: float | None = None
    tbt_ms: float | None = None
    speed_index_ms: float | None = None
    reason: str = ""

    @classmethod
    def empty(cls) -> WebVitals:
        return cls()

    @classmethod
    def from_raw(cls, value: Any) -> WebVitals:
        if not isinstance(value, dict):
            return cls.empty()

        def _opt_float(raw: Any) -> float | None:
            if raw is None or raw == "":
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None

        return cls(
            lcp_ms=_opt_float(value.get("lcp_ms")),
            inp_ms=_opt_float(value.get("inp_ms")),
            cls=_opt_float(value.get("cls")),
            fcp_ms=_opt_float(value.get("fcp_ms")),
            tbt_ms=_opt_float(value.get("tbt_ms")),
            speed_index_ms=_opt_float(value.get("speed_index_ms")),
            reason=str(value.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lcp_ms": self.lcp_ms,
            "inp_ms": self.inp_ms,
            "cls": self.cls,
            "fcp_ms": self.fcp_ms,
            "tbt_ms": self.tbt_ms,
            "speed_index_ms": self.speed_index_ms,
            "reason": self.reason,
        }


# Google's official Core Web Vitals thresholds (good / needs-improvement).
# https://web.dev/articles/vitals
_THRESHOLDS: dict[str, tuple[float, float]] = {
    "lcp": (2500, 4000),  # ms — < 2.5s good, < 4s warn, ≥ 4s critical
    "inp": (200, 500),
    "cls": (0.1, 0.25),  # unitless
    "fcp": (1800, 3000),
    "tbt": (200, 600),
    "speed_index": (3400, 5800),
}


def _status_from_thresholds(value: float | None, good_max: float, warn_max: float) -> str:
    if value is None:
        return "info"
    if value <= good_max:
        return "good"
    if value <= warn_max:
        return "warning"
    return "critical"


def _fmt_ms(value: float | None) -> str:
    return f"{value:.0f} ms" if value is not None else "-"


def _fmt_unitless(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "-"


_LAB_CHECK_META: dict[str, tuple[str, str, str, str]] = {
    # key: (area, title, threshold_key, recommendation)
    "perf_lcp": (
        "Performance",
        "Largest Contentful Paint (LCP)",
        "lcp",
        "Defer the hero asset behind a critical CSS budget; preload the LCP image; "
        "trim third-party scripts blocking the main thread.",
    ),
    "perf_inp": (
        "Performance",
        "Interaction to Next Paint (INP)",
        "inp",
        "Break up long tasks (>50 ms) on the main thread; defer non-essential JS; "
        "audit third-party tag manager scripts.",
    ),
    "perf_cls": (
        "Performance",
        "Cumulative Layout Shift (CLS)",
        "cls",
        "Reserve dimensions on images and ads; avoid inserting content above existing content; "
        "use CSS aspect-ratio for media.",
    ),
    "perf_fcp": (
        "Performance",
        "First Contentful Paint (FCP)",
        "fcp",
        "Inline critical CSS; eliminate render-blocking resources; serve a CDN-edge cache.",
    ),
    "perf_tbt": (
        "Performance",
        "Total Blocking Time (TBT)",
        "tbt",
        "Code-split bundles; defer non-essential third-party scripts; remove unused JS.",
    ),
    "perf_speed_index": (
        "Performance",
        "Speed Index",
        "speed_index",
        "Optimise the above-the-fold critical path; inline minimal CSS; lazy-load below-the-fold media.",
    ),
}


def _value_for_key(vitals: WebVitals, threshold_key: str) -> float | None:
    return {
        "lcp": vitals.lcp_ms,
        "inp": vitals.inp_ms,
        "cls": vitals.cls,
        "fcp": vitals.fcp_ms,
        "tbt": vitals.tbt_ms,
        "speed_index": vitals.speed_index_ms,
    }[threshold_key]


def _format_for_key(threshold_key: str, value: float | None) -> str:
    return _fmt_unitless(value) if threshold_key == "cls" else _fmt_ms(value)


def _lab_check(key: str, vitals: WebVitals) -> AiVisibilityCheck:
    area, title, threshold_key, recommendation = _LAB_CHECK_META[key]
    value = _value_for_key(vitals, threshold_key)
    good_max, warn_max = _THRESHOLDS[threshold_key]
    status = _status_from_thresholds(value, good_max, warn_max)
    detail_prefix = "Lab"
    formatted = _format_for_key(threshold_key, value)
    thresholds = (
        f"≤ {_format_for_key(threshold_key, good_max)} good / ≤ {_format_for_key(threshold_key, warn_max)} warn"
    )
    detail = f"{detail_prefix}: {formatted}; Thresholds: {thresholds}"
    if status == "info" and vitals.reason:
        detail = f"{detail}; Reason: {vitals.reason}"
    return AiVisibilityCheck(
        area=area,
        check=title,
        status=status,
        details=detail,
        recommendation=recommendation,
        key=key,
    )


def build_lab_performance_checks(vitals: WebVitals) -> list[AiVisibilityCheck]:
    """Six lab-data rows for the Performance area."""
    return [_lab_check(key, vitals) for key in _LAB_CHECK_META]


_CDP_NAME_MAP: dict[str, str] = {
    # CDP Performance.getMetrics names → WebVitals field names.
    # The exact set varies across Chromium versions; we treat missing
    # entries as None silently.
    "LargestContentfulPaint": "lcp_ms",
    "FirstContentfulPaint": "fcp_ms",
    "CumulativeLayoutShift": "cls",
    "InteractionToNextPaint": "inp_ms",
    "TotalBlockingTime": "tbt_ms",
    "SpeedIndex": "speed_index_ms",
}


def _vitals_from_cdp_metrics(response: Any) -> WebVitals:
    if not isinstance(response, dict):
        return WebVitals(reason="getMetrics returned non-dict")
    metrics = response.get("metrics") or []
    if not isinstance(metrics, list):
        return WebVitals(reason="metrics field is not a list")
    parsed: dict[str, float | None] = {}
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        name = str(metric.get("name", ""))
        if name not in _CDP_NAME_MAP:
            continue
        raw_value = metric.get("value")
        try:
            parsed[_CDP_NAME_MAP[name]] = float(raw_value)
        except (TypeError, ValueError):
            parsed[_CDP_NAME_MAP[name]] = None
    return WebVitals(
        lcp_ms=parsed.get("lcp_ms"),
        inp_ms=parsed.get("inp_ms"),
        cls=parsed.get("cls"),
        fcp_ms=parsed.get("fcp_ms"),
        tbt_ms=parsed.get("tbt_ms"),
        speed_index_ms=parsed.get("speed_index_ms"),
    )


# Combined builder so callers don't need to import the field-data
# helper separately. perf_crux.CruxData lives in a sibling module.
def build_performance_checks(
    vitals: WebVitals,
    crux: Any | None = None,
) -> list[AiVisibilityCheck]:
    """Six lab rows + (optionally) three CrUX field rows.

    ``crux`` is duck-typed so this module doesn't have a hard
    dependency on perf_crux — when the caller passes ``None`` (or a
    CruxData with ``has_field_data=False``), only lab rows are
    emitted plus three ``info`` rows explaining the gap.
    """
    rows: list[AiVisibilityCheck] = list(build_lab_performance_checks(vitals))
    rows.extend(_crux_rows(crux))
    return rows


_CRUX_CHECK_META: dict[str, tuple[str, str, str, str]] = {
    "perf_crux_lcp": (
        "Performance",
        "Field LCP (CrUX P75)",
        "lcp",
        "Improve LCP for real Chrome users; field data lags lab by ~28 days.",
    ),
    "perf_crux_inp": (
        "Performance",
        "Field INP (CrUX P75)",
        "inp",
        "Reduce long tasks impacting real users; CrUX captures actual interactions.",
    ),
    "perf_crux_cls": (
        "Performance",
        "Field CLS (CrUX P75)",
        "cls",
        "Stabilise above-the-fold layout for real users; CrUX measures real shifts.",
    ),
}


_CRUX_VALUE_KEY: dict[str, str] = {
    "perf_crux_lcp": "lcp_p75_ms",
    "perf_crux_inp": "inp_p75_ms",
    "perf_crux_cls": "cls_p75",
}


def _crux_status(value: float | None, threshold_key: str) -> str:
    if value is None:
        return "info"
    good_max, warn_max = _THRESHOLDS[threshold_key]
    return _status_from_thresholds(value, good_max, warn_max)


def _crux_rows(crux: Any | None) -> list[AiVisibilityCheck]:
    has_field_data = bool(getattr(crux, "has_field_data", False)) if crux is not None else False
    rows: list[AiVisibilityCheck] = []
    for key, (area, title, threshold_key, recommendation) in _CRUX_CHECK_META.items():
        value: float | None = None
        if has_field_data and crux is not None:
            raw = getattr(crux, _CRUX_VALUE_KEY[key], None)
            try:
                value = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                value = None
        status: Literal["good", "warning", "critical", "info"] = _crux_status(value, threshold_key)  # type: ignore[assignment]
        formatted = _format_for_key(threshold_key, value)
        good_max, warn_max = _THRESHOLDS[threshold_key]
        thresholds = (
            f"≤ {_format_for_key(threshold_key, good_max)} good / ≤ {_format_for_key(threshold_key, warn_max)} warn"
        )
        if has_field_data:
            detail = f"Field P75: {formatted}; Thresholds: {thresholds}"
        else:
            reason = getattr(crux, "reason", "") if crux is not None else ""
            detail = "Field: not measured (no CrUX data for this URL)"
            if reason:
                detail = f"{detail}; Reason: {reason}"
        rows.append(
            AiVisibilityCheck(
                area=area,
                check=title,
                status=status,
                details=detail,
                recommendation=recommendation,
                key=key,
            )
        )
    return rows


__all__ = [
    "WebVitals",
    "build_lab_performance_checks",
    "build_performance_checks",
    "vitals_from_cdp_metrics",
]


# Public re-export for callers driving Playwright themselves.
vitals_from_cdp_metrics = _vitals_from_cdp_metrics
