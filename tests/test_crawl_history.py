from __future__ import annotations

from pathlib import Path

from silentfrog.audit_issues import (  # type: ignore[reportMissingImports]
    IssueCategory,
    IssueSeverity,
    issues_for_payload,
)
from silentfrog.crawl_history import (  # type: ignore[reportMissingImports]
    CrawlHistoryIssue,
    CrawlHistoryRun,
    CrawlHistoryStore,
    build_history_run,
    diff_runs,
    format_history_status,
)
from silentfrog.crawl_run_repository import CrawlRunRef  # type: ignore[reportMissingImports]
from silentfrog.crawl_store import CrawlStore, StoredAudit  # type: ignore[reportMissingImports]
from silentfrog.crawl_types import CrawlPayload  # type: ignore[reportMissingImports]
from silentfrog.site_crawl_types import SiteCrawlReport, SiteCrawlResult  # type: ignore[reportMissingImports]


def _payload(url: str = "https://example.com/page") -> CrawlPayload:
    return CrawlPayload.from_raw(
        {
            "meta": [["title", "Example", "7"], ["description", "Useful description.", "19"]],
            "headers": [["h1", "Example"]],
            "images": [],
            "links": [],
            "schema": {"summary": {"total": 0, "by_type": {}, "errors": []}, "blocks": [], "issues": []},
            "canonical": {"target": url, "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": [url], "hops": 0, "final_status": "200", "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": "index, follow",
            "hreflang": [],
            "ai_crawl": [],
            "serp": {
                "title": "Example",
                "description": "",
                "url": url,
                "site_name": "",
                "breadcrumb": "",
                "favicon": "",
            },
            "serp_audit": {},
            "keywords": [],
            "content_quality": {},
            "ai_visibility": {
                "summary": {"verdict": "Strong", "good_count": 1, "warning_count": 0, "critical_count": 0},
                "checks": [],
            },
            "performance": {"status": 200, "summary": {"verdict": "Good"}},
            "social": {},
        }
    )


def _issue_bearing_payload(url: str = "https://example.com/page") -> CrawlPayload:
    # A page that yields >=1 AuditIssue: canonicalized-elsewhere + missing title.
    return CrawlPayload.from_raw(
        {
            "meta": [["title", "", "0"], ["description", "", "0"]],
            "headers": [],
            "images": [],
            "links": [],
            "schema": {"summary": {"total": 0, "by_type": {}, "errors": []}, "blocks": [], "issues": []},
            "canonical": {"target": "https://example.com/other", "self": False, "multiple": False, "status": "200"},
            "redirect": {"chain": [url], "hops": 0, "final_status": "200", "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": "index, follow",
            "hreflang": [],
            "ai_crawl": [],
            "serp": {"title": "", "description": "", "url": url, "site_name": "", "breadcrumb": "", "favicon": ""},
            "serp_audit": {},
            "keywords": [],
            "content_quality": {},
            "ai_visibility": {"summary": {"verdict": "Needs work"}, "checks": []},
            "performance": {"status": 200, "summary": {"verdict": "Good"}},
            "social": {},
        }
    )


def test_history_run_streams_full_payload_from_run_repository(tmp_path: Path) -> None:
    # H1/H2: history routes through the run-bound repository, so a store-backed
    # report (carrying only a CrawlRunRef) yields the same issue set as the
    # in-memory report that kept the payload inline.
    url = "https://example.com/page"
    payload = _issue_bearing_payload(url)
    assert issues_for_payload(url, payload)  # precondition: payload yields issues

    db = tmp_path / "crawl.db"
    store = CrawlStore(db)
    run_id = store.start_run("example.com", "https://example.com/", "list")
    store.save_audit(run_id, StoredAudit(url=url, http_status="200", payload=payload.to_mapping()))
    store.finish_run(run_id)
    store.close()

    run_report = SiteCrawlReport.from_run(
        CrawlRunRef(db, run_id),
        discovered_count=1,
        crawled_count=1,
        skipped_count=0,
        failed_count=0,
        base_url="https://example.com/",
    )
    inline_report = SiteCrawlReport.from_results(
        [SiteCrawlResult.from_payload(url, payload)], discovered_count=1, base_url="https://example.com/"
    )

    run = build_history_run(run_report)
    assert run.issues  # payload-derived issues recovered from the store
    assert run.issues == build_history_run(inline_report).issues


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


def _run(run_id: str, issues: list[CrawlHistoryIssue]) -> CrawlHistoryRun:
    return CrawlHistoryRun(
        run_id=run_id,
        created_at=f"2026-01-01T00:00:0{run_id[-1]}Z",
        scope_key="example.com",
        discovered_count=3,
        crawled_count=3,
        failed_count=0,
        skipped_count=0,
        issues=tuple(issues),
    )


def test_history_issue_rebuilds_a_full_audit_issue() -> None:
    # Regression: to_audit_issue() omitted the required `evidence` argument
    # (added to AuditIssue after this method was written), so reopening a past
    # scan crashed the recap rebuild with a TypeError.
    issue = _issue("meta.title_missing", IssueSeverity.WARNING, "https://example.com/a")

    audit = issue.to_audit_issue()

    assert audit.issue_id == issue.issue_id
    assert audit.severity is issue.severity
    assert audit.category is issue.category
    assert audit.url == issue.url
    assert audit.evidence == ()  # history records carry no evidence rows


def test_build_history_run_extracts_site_scope_and_issue_counts() -> None:
    failed = SiteCrawlResult.failed("https://example.com/fail", "boom")
    report = SiteCrawlReport.from_results([failed], discovered_count=1, base_url="https://example.com/fail")

    run = build_history_run(report, created_at="2026-01-01T00:00:00Z")

    assert run.scope_key == "example.com"
    assert run.discovered_count == 1
    assert run.severity_count(IssueSeverity.CRITICAL) == 1
    assert run.health_score() == 5


def test_history_store_saves_and_loads_runs_by_scope(tmp_path: Path) -> None:
    report = SiteCrawlReport.from_results(
        [SiteCrawlResult.from_payload("https://example.com/page", _payload())],
        discovered_count=1,
        base_url="https://example.com/page",
    )
    run = build_history_run(report, created_at="2026-01-01T00:00:00Z")
    store = CrawlHistoryStore(tmp_path)

    path = store.save_run(run)
    loaded = store.load_runs("example.com")

    assert path.exists()
    assert loaded == [run]
    assert store.latest_run("missing.example") is None


def test_history_store_deletes_runs_by_id(tmp_path: Path) -> None:
    run = _run("run-1", [_issue("meta.title_missing", IssueSeverity.WARNING, "https://example.com/page")])
    store = CrawlHistoryStore(tmp_path)
    store.save_run(run)

    assert store.delete_run(run.run_id) is True
    assert store.load_runs("example.com") == []
    assert store.delete_run(run.run_id) is False


def test_diff_runs_reports_new_fixed_recurring_worsened_and_health_trend() -> None:
    previous = _run(
        "run-1",
        [
            _issue("meta.title_missing", IssueSeverity.WARNING, "https://example.com/fixed"),
            _issue(
                "links.bad_status",
                IssueSeverity.WARNING,
                "https://example.com/recurring",
                IssueCategory.LINKS,
            ),
            _issue(
                "indexability.noindex",
                IssueSeverity.WARNING,
                "https://example.com/worse",
                IssueCategory.INDEXABILITY,
            ),
        ],
    )
    current = _run(
        "run-2",
        [
            _issue(
                "links.bad_status",
                IssueSeverity.WARNING,
                "https://example.com/recurring",
                IssueCategory.LINKS,
            ),
            _issue(
                "indexability.noindex",
                IssueSeverity.CRITICAL,
                "https://example.com/worse",
                IssueCategory.INDEXABILITY,
            ),
            _issue("crawl.http_error", IssueSeverity.CRITICAL, "https://example.com/new", IssueCategory.CRAWL),
        ],
    )

    diff = diff_runs(previous, current)

    assert [issue.url for issue in diff.new_issues] == ["https://example.com/new"]
    assert [issue.url for issue in diff.fixed_issues] == ["https://example.com/fixed"]
    assert sorted(issue.url for issue in diff.recurring_issues) == [
        "https://example.com/recurring",
        "https://example.com/worse",
    ]
    assert [issue.url for issue in diff.worsened_issues] == ["https://example.com/worse"]
    assert diff.trend == "regressed"
    assert "1 new, 1 fixed, 1 worsened, 2 recurring" in format_history_status(current, diff)
