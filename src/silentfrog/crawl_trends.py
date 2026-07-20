"""Health-score and per-issue trends across stored crawl history runs (v3 G2).

Pure derivation: reads :class:`~silentfrog.crawl_history.CrawlHistoryRun`
only, does no I/O, and imports no Qt. It reuses the existing lower-is-better
``CrawlHistoryRun.health_score()`` and ``audit_issues.severity_rank`` — this
module invents no new scoring formula. The §1.5 myth rule (absence is
informational, never a penalty) is enforced upstream where issues are
emitted (``audit_issues.py``); this module only counts and ranks what is
already there.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .audit_issues import IssueSeverity, severity_rank
from .crawl_history import CrawlHistoryRun

_DEFAULT_MAX_RUNS = 12
_DEFAULT_MAX_ISSUES = 8


@dataclass(frozen=True, slots=True)
class TrendPoint:
    """One run's position in the health-score series."""

    run_id: str
    created_at: str
    health_score: int
    critical: int
    warning: int
    info: int


@dataclass(frozen=True, slots=True)
class IssueTrend:
    """One issue_id's instance count across the run window, oldest->newest."""

    issue_id: str
    severity: IssueSeverity
    counts: tuple[int, ...]
    latest_count: int
    delta: int | None  # latest - previous point; None when there is no previous point


@dataclass(frozen=True, slots=True)
class CrawlTrend:
    points: tuple[TrendPoint, ...]  # oldest -> newest
    issue_trends: tuple[IssueTrend, ...]  # ranked worst-first, capped to max_issues


def build_trend(
    runs: Sequence[CrawlHistoryRun],
    *,
    max_runs: int = _DEFAULT_MAX_RUNS,
    max_issues: int = _DEFAULT_MAX_ISSUES,
) -> CrawlTrend:
    """Build a trend over the most recent ``max_runs`` runs.

    ``runs`` is expected ascending by ``created_at`` (as returned by
    ``CrawlHistoryStore.load_runs``); the window keeps the tail. Per-issue
    severity is the worst severity seen for that issue_id in the window, and
    ranking is (severity_rank, -latest_count, issue_id) so the most severe,
    most frequent regressions surface first.
    """
    window = list(runs[-max_runs:]) if max_runs > 0 else list(runs)
    points = tuple(_point_for_run(run) for run in window)
    return CrawlTrend(points=points, issue_trends=_rank_issue_trends(window, max_issues))


def _point_for_run(run: CrawlHistoryRun) -> TrendPoint:
    return TrendPoint(
        run_id=run.run_id,
        created_at=run.created_at,
        health_score=run.health_score(),
        critical=run.severity_count(IssueSeverity.CRITICAL),
        warning=run.severity_count(IssueSeverity.WARNING),
        info=run.severity_count(IssueSeverity.INFO),
    )


def _rank_issue_trends(window: list[CrawlHistoryRun], max_issues: int) -> tuple[IssueTrend, ...]:
    counts_by_issue = _counts_by_issue(window)
    severity_by_issue = _worst_severity_by_issue(window)
    trends = [
        _issue_trend(issue_id, severity_by_issue[issue_id], counts) for issue_id, counts in counts_by_issue.items()
    ]
    trends.sort(key=lambda item: (severity_rank(item.severity), -item.latest_count, item.issue_id))
    return tuple(trends[:max_issues])


def _counts_by_issue(window: list[CrawlHistoryRun]) -> dict[str, list[int]]:
    issue_ids = _all_issue_ids(window)
    return {issue_id: [_count_in_run(run, issue_id) for run in window] for issue_id in issue_ids}


def _all_issue_ids(window: list[CrawlHistoryRun]) -> list[str]:
    seen: dict[str, None] = {}
    for run in window:
        for issue in run.issues:
            seen.setdefault(issue.issue_id, None)
    return list(seen)


def _count_in_run(run: CrawlHistoryRun, issue_id: str) -> int:
    return sum(1 for issue in run.issues if issue.issue_id == issue_id)


def _worst_severity_by_issue(window: list[CrawlHistoryRun]) -> dict[str, IssueSeverity]:
    worst: dict[str, IssueSeverity] = {}
    for run in window:
        for issue in run.issues:
            worst[issue.issue_id] = _worse_of(worst.get(issue.issue_id), issue.severity)
    return worst


def _worse_of(current: IssueSeverity | None, candidate: IssueSeverity) -> IssueSeverity:
    if current is None or severity_rank(candidate) < severity_rank(current):
        return candidate
    return current


def _issue_trend(issue_id: str, severity: IssueSeverity, counts: list[int]) -> IssueTrend:
    latest = counts[-1] if counts else 0
    previous = counts[-2] if len(counts) >= 2 else None
    delta = None if previous is None else latest - previous
    return IssueTrend(issue_id=issue_id, severity=severity, counts=tuple(counts), latest_count=latest, delta=delta)


__all__ = ["CrawlTrend", "IssueTrend", "TrendPoint", "build_trend"]
