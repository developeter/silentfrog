from __future__ import annotations

from silentfrog.audit_issues import IssueCategory, IssueSeverity  # type: ignore[reportMissingImports]
from silentfrog.crawl_history import CrawlHistoryIssue, CrawlHistoryRun  # type: ignore[reportMissingImports]
from silentfrog.crawl_trends import build_trend  # type: ignore[reportMissingImports]


def _issue(
    issue_id: str,
    severity: IssueSeverity,
    url: str,
    category: IssueCategory = IssueCategory.META,
) -> CrawlHistoryIssue:
    return CrawlHistoryIssue(
        issue_id=issue_id,
        severity=severity,
        category=category,
        url=url,
        reason=f"{issue_id} reason",
        recommendation="Fix it.",
        source=category.value,
        confidence="high",
    )


def _run(run_id: str, created_at: str, issues: tuple[CrawlHistoryIssue, ...]) -> CrawlHistoryRun:
    return CrawlHistoryRun(
        run_id=run_id,
        created_at=created_at,
        scope_key="example.com",
        discovered_count=5,
        crawled_count=5,
        failed_count=0,
        skipped_count=0,
        issues=issues,
    )


def _three_runs() -> list[CrawlHistoryRun]:
    # run-1: only a warning; run-2: warning persists + a critical appears;
    # run-3: warning count grows, critical is fixed. Deliberately gives
    # meta.title_missing 0-fill coverage nowhere (present in all three) and
    # indexability.noindex a gap in run-3 to exercise 0-fill.
    return [
        _run(
            "run-1",
            "2026-01-01T00:00:00Z",
            (_issue("meta.title_missing", IssueSeverity.WARNING, "https://example.com/a"),),
        ),
        _run(
            "run-2",
            "2026-01-02T00:00:00Z",
            (
                _issue("meta.title_missing", IssueSeverity.WARNING, "https://example.com/a"),
                _issue("meta.title_missing", IssueSeverity.WARNING, "https://example.com/b"),
                _issue(
                    "indexability.noindex",
                    IssueSeverity.CRITICAL,
                    "https://example.com/c",
                    IssueCategory.INDEXABILITY,
                ),
            ),
        ),
        _run(
            "run-3",
            "2026-01-03T00:00:00Z",
            (
                _issue("meta.title_missing", IssueSeverity.WARNING, "https://example.com/a"),
                _issue("meta.title_missing", IssueSeverity.WARNING, "https://example.com/b"),
                _issue("meta.title_missing", IssueSeverity.WARNING, "https://example.com/d"),
            ),
        ),
    ]


def test_build_trend_orders_points_oldest_to_newest_with_health_values() -> None:
    trend = build_trend(_three_runs())

    assert [point.run_id for point in trend.points] == ["run-1", "run-2", "run-3"]
    assert [point.health_score for point in trend.points] == [2, 9, 6]  # 2, 2+2+5, 2+2+2
    assert trend.points[1].critical == 1
    assert trend.points[2].critical == 0


def test_build_trend_zero_fills_issue_counts_and_ranks_critical_above_warning() -> None:
    trend = build_trend(_three_runs())

    by_id = {item.issue_id: item for item in trend.issue_trends}
    assert by_id["indexability.noindex"].counts == (0, 1, 0)  # absent in run-1 and run-3 -> 0
    assert by_id["meta.title_missing"].counts == (1, 2, 3)
    # A critical issue ranks above a warning issue even though it has a lower
    # latest count (0 vs 3) — severity dominates the ranking.
    assert [item.issue_id for item in trend.issue_trends] == ["indexability.noindex", "meta.title_missing"]


def test_build_trend_computes_latest_count_and_delta_vs_previous_run() -> None:
    trend = build_trend(_three_runs())

    by_id = {item.issue_id: item for item in trend.issue_trends}
    assert by_id["meta.title_missing"].latest_count == 3
    assert by_id["meta.title_missing"].delta == 1  # 3 - 2
    assert by_id["indexability.noindex"].latest_count == 0
    assert by_id["indexability.noindex"].delta == -1  # 0 - 1


def test_build_trend_max_runs_window_keeps_only_the_most_recent_tail() -> None:
    trend = build_trend(_three_runs(), max_runs=2)

    assert [point.run_id for point in trend.points] == ["run-2", "run-3"]
    by_id = {item.issue_id: item for item in trend.issue_trends}
    assert by_id["meta.title_missing"].counts == (2, 3)  # run-1 dropped from the window


def test_build_trend_max_issues_caps_the_ranked_list() -> None:
    trend = build_trend(_three_runs(), max_issues=1)

    assert len(trend.issue_trends) == 1
    assert trend.issue_trends[0].issue_id == "indexability.noindex"  # the more severe one wins the cap


def test_build_trend_single_run_has_one_point_and_no_previous_delta() -> None:
    single = [_three_runs()[0]]

    trend = build_trend(single)

    assert len(trend.points) == 1
    assert trend.points[0].run_id == "run-1"
    assert len(trend.issue_trends) == 1
    only = trend.issue_trends[0]
    assert only.counts == (1,)
    assert only.latest_count == 1
    assert only.delta is None  # no previous point to compare against


def test_build_trend_empty_runs_yields_empty_trend() -> None:
    trend = build_trend([])

    assert trend.points == ()
    assert trend.issue_trends == ()
