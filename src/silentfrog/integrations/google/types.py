"""Typed GSC + GA4 metrics (v2.0 V7).

Frozen dataclasses so the data crosses module boundaries typed, per
AGENTS.md. ``measured`` distinguishes "we fetched real data" from "the
integration isn't connected" — absent data is informational and never
penalises the GEO Score (§1.5 myth rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GscMetrics:
    impressions: int = 0
    clicks: int = 0
    ctr: float = 0.0
    position: float = 0.0
    top_queries: tuple[str, ...] = field(default_factory=tuple)
    measured: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "impressions": self.impressions,
            "clicks": self.clicks,
            "ctr": round(self.ctr, 4),
            "position": round(self.position, 1),
            "top_queries": list(self.top_queries),
            "measured": self.measured,
        }

    @classmethod
    def from_dict(cls, value: Any) -> GscMetrics:
        if not isinstance(value, dict):
            return cls()
        return cls(
            impressions=int(value.get("impressions", 0) or 0),
            clicks=int(value.get("clicks", 0) or 0),
            ctr=float(value.get("ctr", 0.0) or 0.0),
            position=float(value.get("position", 0.0) or 0.0),
            top_queries=tuple(str(q) for q in value.get("top_queries", []) if q),
            measured=bool(value.get("measured", False)),
        )


@dataclass(frozen=True)
class Ga4Metrics:
    pageviews: int = 0
    avg_engagement_seconds: float = 0.0
    bounce_rate: float = 0.0
    conversions: int = 0
    measured: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "pageviews": self.pageviews,
            "avg_engagement_seconds": round(self.avg_engagement_seconds, 1),
            "bounce_rate": round(self.bounce_rate, 4),
            "conversions": self.conversions,
            "measured": self.measured,
        }

    @classmethod
    def from_dict(cls, value: Any) -> Ga4Metrics:
        if not isinstance(value, dict):
            return cls()
        return cls(
            pageviews=int(value.get("pageviews", 0) or 0),
            avg_engagement_seconds=float(value.get("avg_engagement_seconds", 0.0) or 0.0),
            bounce_rate=float(value.get("bounce_rate", 0.0) or 0.0),
            conversions=int(value.get("conversions", 0) or 0),
            measured=bool(value.get("measured", False)),
        )


__all__ = ["Ga4Metrics", "GscMetrics"]
