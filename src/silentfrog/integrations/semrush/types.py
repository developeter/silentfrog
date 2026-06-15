"""Typed Semrush authority metrics (v2.0 V17).

Frozen dataclass so the data crosses module boundaries typed, per
AGENTS.md. ``measured`` distinguishes "we fetched real Semrush data" from
"the integration isn't connected" — absent data is informational and
never penalises the GEO Score (§1.5 myth rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _to_int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class SemrushMetrics:
    domain_authority: int = 0
    organic_keywords: int = 0
    organic_traffic: int = 0
    backlinks_total: int = 0
    referring_domains: int = 0
    top_organic_keywords: tuple[str, ...] = field(default_factory=tuple)
    paid_keywords: int = 0
    paid_traffic: int = 0
    measured: bool = False

    @classmethod
    def empty(cls) -> SemrushMetrics:
        return cls()

    @classmethod
    def from_dict(cls, value: Any) -> SemrushMetrics:
        if not isinstance(value, dict):
            return cls()
        keywords_raw = value.get("top_organic_keywords", [])
        keywords = tuple(str(item) for item in keywords_raw if item) if isinstance(keywords_raw, (list, tuple)) else ()
        return cls(
            domain_authority=_to_int(value.get("domain_authority", 0)),
            organic_keywords=_to_int(value.get("organic_keywords", 0)),
            organic_traffic=_to_int(value.get("organic_traffic", 0)),
            backlinks_total=_to_int(value.get("backlinks_total", 0)),
            referring_domains=_to_int(value.get("referring_domains", 0)),
            top_organic_keywords=keywords,
            paid_keywords=_to_int(value.get("paid_keywords", 0)),
            paid_traffic=_to_int(value.get("paid_traffic", 0)),
            measured=bool(value.get("measured", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_authority": self.domain_authority,
            "organic_keywords": self.organic_keywords,
            "organic_traffic": self.organic_traffic,
            "backlinks_total": self.backlinks_total,
            "referring_domains": self.referring_domains,
            "top_organic_keywords": list(self.top_organic_keywords),
            "paid_keywords": self.paid_keywords,
            "paid_traffic": self.paid_traffic,
            "measured": self.measured,
        }


__all__ = ["SemrushMetrics"]
