"""GSC + GA4 AI Visibility checks (v2.0 V7).

Two new areas — "Real performance" (Search Console) and "Engagement"
(GA4) — that close the loop between the audit and what actually happens
in search. Per §1.5, unconnected/unmeasured data is ``info`` and never
penalises the GEO Score.
"""

from __future__ import annotations

from ...crawl_types import AiVisibilityCheck
from .types import Ga4Metrics, GscMetrics

_CTR_GOOD = 0.02  # ~2% CTR is around average; above is a good signal
_POSITION_TOP = 10.0
_ENGAGEMENT_GOOD_SECONDS = 30.0
_BOUNCE_WARN = 0.70

REAL_PERFORMANCE_AREA = "Real performance"
ENGAGEMENT_AREA = "Engagement"


def _check(area: str, name: str, status: str, details: str, recommendation: str, key: str) -> AiVisibilityCheck:
    return AiVisibilityCheck(
        area=area, check=name, status=status, details=details, recommendation=recommendation, key=key
    )


def _gsc_checks(gsc: GscMetrics) -> list[AiVisibilityCheck]:
    if not gsc.measured:
        return [
            _check(
                REAL_PERFORMANCE_AREA,
                "Search Console data",
                "info",
                "Not connected.",
                "Settings -> Connect Google Search Console.",
                "gsc_impressions_present",
            )
        ]
    ctr_good = gsc.ctr >= _CTR_GOOD
    pos_good = 0 < gsc.position <= _POSITION_TOP
    return [
        _check(
            REAL_PERFORMANCE_AREA,
            "Search Console impressions",
            "info",
            f"{gsc.impressions} impressions, {gsc.clicks} clicks.",
            "-",
            "gsc_impressions_present",
        ),
        _check(
            REAL_PERFORMANCE_AREA,
            "Click-through rate",
            "good" if ctr_good else "info",
            f"CTR {gsc.ctr * 100:.1f}%.",
            "-" if ctr_good else "Sharpen the title/meta description to lift CTR.",
            "gsc_ctr_above_average",
        ),
        _check(
            REAL_PERFORMANCE_AREA,
            "Average position",
            "good" if pos_good else "info",
            f"Avg position {gsc.position:.1f}.",
            "-",
            "gsc_position_in_top_10",
        ),
        _check(
            REAL_PERFORMANCE_AREA,
            "Top queries",
            "info",
            "Top: " + (", ".join(gsc.top_queries) or "none"),
            "-",
            "gsc_query_count",
        ),
    ]


def _ga4_checks(ga4: Ga4Metrics) -> list[AiVisibilityCheck]:
    if not ga4.measured:
        return [
            _check(
                ENGAGEMENT_AREA,
                "Analytics data",
                "info",
                "Not connected.",
                "Settings -> Connect Google Analytics 4.",
                "ga4_engagement_above_median",
            )
        ]
    bounce_high = ga4.bounce_rate > _BOUNCE_WARN
    engaged = ga4.avg_engagement_seconds >= _ENGAGEMENT_GOOD_SECONDS
    return [
        _check(
            ENGAGEMENT_AREA,
            "Engagement time",
            "good" if engaged else "info",
            f"Avg engagement {ga4.avg_engagement_seconds:.0f}s over {ga4.pageviews} views.",
            "-",
            "ga4_engagement_above_median",
        ),
        _check(
            ENGAGEMENT_AREA,
            "Bounce rate",
            "warning" if bounce_high else "good",
            f"Bounce {ga4.bounce_rate * 100:.0f}%.",
            "High bounce — improve above-the-fold relevance and intent match." if bounce_high else "-",
            "ga4_bounce_below_threshold",
        ),
    ]


def build_real_performance_checks(gsc: GscMetrics, ga4: Ga4Metrics) -> list[AiVisibilityCheck]:
    return [*_gsc_checks(gsc), *_ga4_checks(ga4)]


__all__ = ["ENGAGEMENT_AREA", "REAL_PERFORMANCE_AREA", "build_real_performance_checks"]
