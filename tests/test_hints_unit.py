"""Unit tests for the v3 G1 prioritized hints engine."""

from __future__ import annotations

from silentfrog.audit_issues import AuditIssue, IssueCategory, IssueSeverity
from silentfrog.hints import build_hints


def _issue(issue_id: str, severity: IssueSeverity, url: str, category=IssueCategory.META) -> AuditIssue:
    return AuditIssue(
        issue_id=issue_id,
        category=category,
        severity=severity,
        source="Test",
        reason=f"{issue_id} reason",
        recommendation=f"Fix {issue_id}.",
        evidence=(),
        url=url,
    )


def test_hints_group_by_issue_id_and_count_distinct_urls() -> None:
    issues = [
        _issue("meta.description_missing", IssueSeverity.WARNING, "https://e.com/a"),
        _issue("meta.description_missing", IssueSeverity.WARNING, "https://e.com/b"),
        _issue("meta.description_missing", IssueSeverity.WARNING, "https://e.com/b"),  # dup url
    ]
    hints = build_hints(issues)
    assert len(hints) == 1
    assert hints[0].affected_urls == 2  # distinct urls only
    assert hints[0].sample_urls == ("https://e.com/a", "https://e.com/b")


def test_severity_dominates_prevalence_in_ranking() -> None:
    issues = [_issue("crit.one", IssueSeverity.CRITICAL, "https://e.com/x")]
    # 50 warning-affected pages must NOT outrank a single critical.
    issues += [_issue("warn.many", IssueSeverity.WARNING, f"https://e.com/p{i}") for i in range(50)]
    hints = build_hints(issues)
    assert hints[0].issue_id == "crit.one"
    assert hints[0].severity == IssueSeverity.CRITICAL
    assert hints[1].issue_id == "warn.many"
    assert hints[1].affected_urls == 50


def test_prevalence_breaks_ties_within_a_severity_band() -> None:
    issues = [_issue("warn.rare", IssueSeverity.WARNING, "https://e.com/a")]
    issues += [_issue("warn.common", IssueSeverity.WARNING, f"https://e.com/c{i}") for i in range(10)]
    ordered = [h.issue_id for h in build_hints(issues)]
    assert ordered == ["warn.common", "warn.rare"]  # more-affected first


def test_strongest_severity_in_a_group_wins() -> None:
    issues = [
        _issue("mixed", IssueSeverity.WARNING, "https://e.com/a"),
        _issue("mixed", IssueSeverity.CRITICAL, "https://e.com/b"),
    ]
    hint = build_hints(issues)[0]
    assert hint.severity == IssueSeverity.CRITICAL
    assert "mixed" in hint.title


def test_headline_scales_with_page_count() -> None:
    issues = [_issue("meta.title_missing", IssueSeverity.WARNING, f"https://e.com/p{i}") for i in range(3)]
    hint = build_hints(issues)[0]
    assert "3 pages" in hint.headline()
    assert "3 of 100 pages" in hint.headline(total_items=100)
    # A single-page audit (no url) reads as the bare title, no page count.
    single = build_hints([_issue("meta.title_missing", IssueSeverity.WARNING, "")])[0]
    assert single.affected_urls == 1
    assert single.headline() == single.title
