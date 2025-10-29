from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, List


@dataclass(frozen=True)
class PerformanceContext:
    """Snapshot of high-level performance data used to derive open-source hints."""

    transfer_size: int
    css_count: int
    js_count: int
    img_count: int
    font_count: int
    nav_total_ms: float
    nav_ttfb_ms: float


@dataclass(frozen=True)
class _GuideHint:
    title: str
    rationale: str
    url: str
    condition: Callable[[PerformanceContext], bool]

    def render(self) -> str:
        return f"{self.title}: {self.rationale} ({self.url})"


def _over_budget_transfer(context: PerformanceContext) -> bool:
    return context.transfer_size > 1_500_000


def _slow_navigation(context: PerformanceContext) -> bool:
    return context.nav_total_ms > 4_000


def _script_heavy(context: PerformanceContext) -> bool:
    return context.js_count > 30


_GUIDE_HINTS: List[_GuideHint] = [
    _GuideHint(
        title="HTTP Archive Web Almanac (open source)",
        rationale="Page weight is above 1.5 MB; compare with the community benchmarks",
        url="https://almanac.httparchive.org/en/2023/performance#page-weight",
        condition=_over_budget_transfer,
    ),
    _GuideHint(
        title="RAIL performance model (web.dev)",
        rationale="Navigation appears slower than the 4s budget; revisit the RAIL guidance",
        url="https://web.dev/rail/",
        condition=_slow_navigation,
    ),
    _GuideHint(
        title="Web Vitals patterns (GitHub)",
        rationale="JavaScript requests exceed 30; review bundling and loading strategies",
        url="https://github.com/GoogleChrome/web-vitals-patterns",
        condition=_script_heavy,
    ),
]


def guides_enabled() -> bool:
    raw = os.environ.get("SILENTFROG_PERF_GUIDES", "1").strip().lower()
    return raw not in {"0", "false", "no"}


def open_source_hints(context: PerformanceContext) -> List[str]:
    if not guides_enabled():
        return []
    return [hint.render() for hint in _GUIDE_HINTS if hint.condition(context)]


__all__ = ["PerformanceContext", "guides_enabled", "open_source_hints"]

