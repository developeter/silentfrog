"""Semrush authority AI Visibility checks (v2.0 V17).

A new "Authority signals" area surfacing Semrush domain-level authority
(Authority Score, organic footprint, backlink profile, paid presence).

Per §1.5: these are off-page signals the page does not control cheaply,
so they are never "defects". Above threshold => ``good``; otherwise
``info`` (never ``warning``/``critical``). Unmeasured => a single
``info`` row. Mirrors the V7 GSC checks, which use good/info only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ...crawl_types import AiVisibilityCheck
from .types import SemrushMetrics

AUTHORITY_AREA = "Authority signals"

_AUTHORITY_SCORE_GOOD = 30
_ORGANIC_TRAFFIC_GOOD = 1000
_BACKLINKS_GOOD = 100
_REFERRING_DOMAINS_GOOD = 25


def _check(area: str, name: str, status: str, details: str, recommendation: str, key: str) -> AiVisibilityCheck:
    return AiVisibilityCheck(
        area=area, check=name, status=status, details=details, recommendation=recommendation, key=key
    )


@dataclass(frozen=True)
class _Spec:
    key: str
    name: str
    # (metrics) -> True when the signal clears its "good" bar.
    good_when: Callable[[SemrushMetrics], bool]
    # (metrics) -> the human-readable detail string.
    details: Callable[[SemrushMetrics], str]
    recommendation: str


# Each spec routes to good (cleared) or info (not cleared) — never a
# warning, keeping the area §1.5-safe. Dispatch is data, not an if-ladder.
_SPECS: tuple[_Spec, ...] = (
    _Spec(
        key="semrush_domain_authority_above_30",
        name="Domain Authority Score",
        good_when=lambda m: m.domain_authority >= _AUTHORITY_SCORE_GOOD,
        details=lambda m: f"Authority Score {m.domain_authority}/100.",
        recommendation="Earn links from authoritative, topically relevant sites to lift Authority Score over time.",
    ),
    _Spec(
        key="semrush_organic_keywords_present",
        name="Organic keyword footprint",
        good_when=lambda m: m.organic_keywords > 0,
        details=lambda m: f"{m.organic_keywords} ranking organic keywords.",
        recommendation="Publish and optimise topical content so the domain ranks for more organic keywords.",
    ),
    _Spec(
        key="semrush_organic_traffic_above_threshold",
        name="Organic traffic",
        good_when=lambda m: m.organic_traffic >= _ORGANIC_TRAFFIC_GOOD,
        details=lambda m: f"Estimated {m.organic_traffic} organic visits/month.",
        recommendation="Grow rankings on higher-volume queries to build an organic traffic base AI engines trust.",
    ),
    _Spec(
        key="semrush_backlinks_above_threshold",
        name="Backlink volume",
        good_when=lambda m: m.backlinks_total >= _BACKLINKS_GOOD,
        details=lambda m: f"{m.backlinks_total} total backlinks.",
        recommendation="Pursue genuine editorial backlinks; quality matters more than raw volume.",
    ),
    _Spec(
        key="semrush_referring_domains_diverse",
        name="Referring domain diversity",
        good_when=lambda m: m.referring_domains >= _REFERRING_DOMAINS_GOOD,
        details=lambda m: f"{m.referring_domains} unique referring domains.",
        recommendation="Diversify link sources across distinct, authoritative domains rather than repeat referrers.",
    ),
    _Spec(
        key="semrush_paid_signal_present",
        name="Paid search presence",
        good_when=lambda m: m.paid_keywords > 0 or m.paid_traffic > 0,
        details=lambda m: f"{m.paid_keywords} paid keywords, ~{m.paid_traffic} paid visits/month.",
        recommendation="-",
    ),
)


def _row(spec: _Spec, metrics: SemrushMetrics) -> AiVisibilityCheck:
    good = spec.good_when(metrics)
    return _check(
        AUTHORITY_AREA,
        spec.name,
        "good" if good else "info",
        spec.details(metrics),
        "-" if good else spec.recommendation,
        spec.key,
    )


def build_semrush_authority_checks(metrics: SemrushMetrics) -> list[AiVisibilityCheck]:
    """Six rows in the optional "Authority signals" area. Unmeasured => a
    single ``info`` row; otherwise one good/info row per signal — never a
    warning, per §1.5."""
    if not metrics.measured:
        return [
            _check(
                AUTHORITY_AREA,
                "Semrush authority data",
                "info",
                "Not connected.",
                "Settings -> Authority (Semrush): add an API key to fetch authority signals.",
                "semrush_domain_authority_above_30",
            )
        ]
    return [_row(spec, metrics) for spec in _SPECS]


__all__ = ["AUTHORITY_AREA", "build_semrush_authority_checks"]
