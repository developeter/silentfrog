"""GSC + GA4 AI Visibility checks (v2.0 V7).

Two new areas — "Real performance" (Search Console) and "Engagement"
(GA4) — that close the loop between the audit and what actually happens
in search. Per §1.5, unconnected/unmeasured data is ``info`` and never
penalises the GEO Score.
"""

from __future__ import annotations

from ...crawl_types import AiVisibilityCheck
from .lighthouse import LighthouseScores
from .rich_results import RichResultsReport
from .types import Ga4Metrics, GscMetrics

_CTR_GOOD = 0.02  # ~2% CTR is around average; above is a good signal
_POSITION_TOP = 10.0
_ENGAGEMENT_GOOD_SECONDS = 30.0
_BOUNCE_WARN = 0.70

REAL_PERFORMANCE_AREA = "Real performance"
ENGAGEMENT_AREA = "Engagement"
PERFORMANCE_AREA = "Performance"
CITATION_AREA = "Citation readiness"

_LIGHTHOUSE_GOOD = 90
# (label, LighthouseScores attribute, check key)
_LIGHTHOUSE_CATEGORIES = (
    ("Performance", "performance", "lighthouse_perf_above_90"),
    ("Accessibility", "accessibility", "lighthouse_a11y_above_90"),
    ("SEO", "seo", "lighthouse_seo_above_90"),
)


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
                "Connect via Settings → Connect Google, or set SILENTFROG_GOOGLE_ENABLE=1 and "
                "SILENTFROG_GSC_SITE_URL for headless use.",
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
                "Connect via Settings → Connect Google, or set SILENTFROG_GOOGLE_ENABLE=1 and "
                "SILENTFROG_GA4_PROPERTY_ID for headless use.",
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


def _lighthouse_row(label: str, score: int, key: str) -> AiVisibilityCheck:
    good = score >= _LIGHTHOUSE_GOOD
    return _check(
        PERFORMANCE_AREA,
        f"Lighthouse {label}",
        "good" if good else "warning",
        f"{label} score {score}/100.",
        "-" if good else f"Raise the Lighthouse {label} score to {_LIGHTHOUSE_GOOD}+.",
        key,
    )


def _lighthouse_freshness(scores: LighthouseScores) -> AiVisibilityCheck:
    return _check(
        PERFORMANCE_AREA,
        "Lighthouse freshness",
        "info",
        f"Fetched: {scores.fetched_at or 'unknown'}; Best practices {scores.best_practices}/100.",
        "-",
        "lighthouse_freshness",
    )


def build_lighthouse_checks(scores: LighthouseScores) -> list[AiVisibilityCheck]:
    """Lighthouse lab scores extend the Performance area. Unmeasured =>
    a single ``info`` row (the run is opt-in, single-page only)."""
    if not scores.measured:
        return [
            _check(
                PERFORMANCE_AREA,
                "Lighthouse",
                "info",
                "Not run.",
                "Open the page audit and click Run Lighthouse for lab scores.",
                "lighthouse_perf_above_90",
            )
        ]
    rows = [_lighthouse_row(label, getattr(scores, attr), key) for label, attr, key in _LIGHTHOUSE_CATEGORIES]
    rows.append(_lighthouse_freshness(scores))
    return rows


def _rich_eligible_row(report: RichResultsReport) -> AiVisibilityCheck:
    has_eligible = bool(report.eligible_types)
    return _check(
        CITATION_AREA,
        "Rich results eligibility",
        "good" if has_eligible else "info",
        f"Eligible: {', '.join(report.eligible_types) or 'none'}; "
        f"Incomplete: {', '.join(report.ineligible_types) or 'none'} ({report.source}).",
        "-" if has_eligible else "Complete the structured data so at least one type is rich-result eligible.",
        "rich_results_eligible",
    )


def _rich_warning_row(report: RichResultsReport) -> AiVisibilityCheck:
    count = len(report.warnings)
    detail = f"{count} structured-data warning(s)."
    if count:
        detail += " " + "; ".join(report.warnings[:3])
    return _check(
        CITATION_AREA,
        "Rich results warnings",
        "warning" if count else "good",
        detail,
        "Fix the structured-data issues so the markup stays rich-result eligible." if count else "-",
        "rich_results_warning_count",
    )


def build_rich_results_checks(report: RichResultsReport) -> list[AiVisibilityCheck]:
    """Rich-result eligibility extends the Citation readiness area. Per
    §1.5, no eligible markup => ``info``; warnings are genuine in-set
    defects so they may warn."""
    if not report.measured:
        return [
            _check(
                CITATION_AREA,
                "Rich results eligibility",
                "info",
                "No rich-result-eligible structured data detected.",
                "Add Product, Article, FAQ, Breadcrumb, or Organization markup if relevant.",
                "rich_results_eligible",
            )
        ]
    return [_rich_eligible_row(report), _rich_warning_row(report)]


__all__ = [
    "CITATION_AREA",
    "ENGAGEMENT_AREA",
    "PERFORMANCE_AREA",
    "REAL_PERFORMANCE_AREA",
    "build_lighthouse_checks",
    "build_real_performance_checks",
    "build_rich_results_checks",
]
