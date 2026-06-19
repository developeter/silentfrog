from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from silentfrog.audit_issues import (  # type: ignore[reportMissingImports]
    AuditIssue,
    IssueCategory,
    IssueEvidence,
    IssueSeverity,
    dedupe_issues,
    issues_for_payload,
    issues_for_site_report,
    severity_color_role,
    severity_rank,
)
from silentfrog.crawl_run_repository import CrawlRunRef  # type: ignore[reportMissingImports]
from silentfrog.crawl_store import CrawlStore, StoredAudit  # type: ignore[reportMissingImports]
from silentfrog.crawl_types import CrawlPayload  # type: ignore[reportMissingImports]
from silentfrog.image_diagnostics import normalize_image_row  # type: ignore[reportMissingImports]
from silentfrog.site_crawl_types import SiteCrawlReport, SiteCrawlResult  # type: ignore[reportMissingImports]


def _payload(url: str = "https://example.com/page") -> CrawlPayload:
    return CrawlPayload.from_raw(
        {
            "meta": [["title", "", "0"], ["description", "", "0"]],
            "headers": [],
            "images": [
                normalize_image_row(
                    [
                        "https://example.com/hero.jpg",
                        "Hero",
                        "",
                        "image/jpeg",
                        "",
                        "",
                        "",
                        "",
                        "Lazy",
                        "High",
                    ]
                )
            ],
            "links": [
                [
                    "https://example.com/missing",
                    "Missing",
                    "Interno",
                    "follow",
                    "404",
                    "Client error",
                    "Body",
                    "",
                    "com",
                ]
            ],
            "schema": {
                "summary": {"total": 1, "by_type": {"Product": 1}, "errors": ["missing offers"]},
                "blocks": [],
                "issues": [],
                "eligibility": [
                    {
                        "type": "Product",
                        "detected": True,
                        "count": 1,
                        "eligibility": "Incomplete",
                        "missing_fields": ["offers"],
                        "warnings": ["missing price"],
                    }
                ],
            },
            "canonical": {
                "target": "https://example.com/other",
                "self": False,
                "multiple": False,
                "status": "200",
            },
            "redirect": {"chain": [url], "hops": 0, "final_status": "200", "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": "index, follow",
            "hreflang": [],
            "ai_crawl": [],
            "serp": {
                "title": "",
                "description": "",
                "url": url,
                "site_name": "",
                "breadcrumb": "",
                "favicon": "",
            },
            "serp_audit": {},
            "keywords": [],
            "content_quality": {
                "word_count": 80,
                "thin_content_risk": "High",
                "heading_structure": "Missing H1",
                "title_h1_alignment": "Missing",
                "verdict": "Weak",
            },
            "ai_visibility": {
                "summary": {
                    "verdict": "Needs work",
                    "good_count": 0,
                    "warning_count": 1,
                    "critical_count": 0,
                },
                "checks": [
                    {
                        "area": "Answerability",
                        "check": "Intro answers the topic quickly",
                        "status": "warning",
                        "details": "The answer is not explicit.",
                        "recommendation": "Add a concise answer near the top.",
                        "key": "answerability_intro",
                    }
                ],
            },
            "performance": {
                "summary": {"verdict": "Needs work"},
                "issues": [
                    {
                        "key": "image_weight",
                        "severity": "warning",
                        "message": "Large image",
                        "evidence": "Hero image is heavy.",
                        "recommendation": "Compress the hero image.",
                    }
                ],
            },
            "social": {},
        }
    )


def test_issues_for_site_report_hydrates_stripped_payload_via_repository(tmp_path: Path) -> None:
    # H1: recap/history route through the run-bound repository, so a result
    # whose in-memory payload was stripped (to bound RAM) still contributes its
    # full issues — recovered from the store, identical to the in-memory case.
    url = "https://example.com/page"
    payload = _payload(url)
    assert issues_for_payload(url, payload)  # precondition: this payload yields issues

    db = tmp_path / "crawl.db"
    store = CrawlStore(db)
    run_id = store.start_run("example.com", "https://example.com/", "list")
    store.save_audit(run_id, StoredAudit(url=url, payload=payload.to_mapping()))
    store.finish_run(run_id)
    store.close()

    in_memory_result = SiteCrawlResult.from_payload(url, payload)
    stripped_result = replace(in_memory_result, payload=None)
    stripped_report = SiteCrawlReport.from_results([stripped_result], discovered_count=1, run_id=run_id)
    full_report = SiteCrawlReport.from_results([in_memory_result], discovered_count=1, run_id=run_id)

    # Without a repository the stripped payload's issues are silently lost...
    truncated = issues_for_site_report(stripped_report)
    # ...with the run-bound repository they are recovered — identical to the
    # result that kept its payload in memory.
    with CrawlRunRef(db, run_id).open() as repo:
        hydrated = issues_for_site_report(stripped_report, repository=repo)

    assert hydrated == issues_for_site_report(full_report)
    assert len(hydrated) > len(truncated)


def test_issues_for_payload_extracts_prioritized_evidence() -> None:
    url = "https://example.com/page"
    issues = issues_for_payload(url, _payload(url))
    by_id = {issue.issue_id: issue for issue in issues}

    assert by_id["indexability.canonicalized_elsewhere"].severity == IssueSeverity.CRITICAL
    assert by_id["meta.title_missing"].category == IssueCategory.META
    assert by_id["content.h1_missing"].recommendation
    assert by_id["images.diagnostic"].evidence[0] == IssueEvidence("Image", "https://example.com/hero.jpg")
    assert by_id["links.bad_status"].evidence[-1] == IssueEvidence("Status", "404")
    assert by_id["structured_data.error"].reason
    assert by_id["structured_data.eligibility_incomplete"].evidence[-1] == IssueEvidence("Missing fields", "offers")
    assert by_id["performance.image_weight"].recommendation == "Compress the hero image."
    assert by_id["ai_geo.answerability_intro"].confidence == "medium"


def test_severity_order_and_color_roles_are_conservative() -> None:
    assert severity_rank(IssueSeverity.CRITICAL) < severity_rank(IssueSeverity.WARNING)
    assert severity_rank(IssueSeverity.WARNING) < severity_rank(IssueSeverity.INFO)
    assert severity_color_role(IssueSeverity.CRITICAL) == "bad"
    assert severity_color_role(IssueSeverity.WARNING) == "warn"
    assert severity_color_role(IssueSeverity.INFO) == "info"


def test_dedupe_issues_keeps_first_sorted_unique_issue() -> None:
    first = AuditIssue(
        issue_id="meta.title_missing",
        category=IssueCategory.META,
        severity=IssueSeverity.WARNING,
        source="Meta",
        reason="Missing title",
        recommendation="Add title",
        evidence=(IssueEvidence("Title", "Missing"),),
        url="https://example.com/page",
    )
    duplicate = AuditIssue(
        issue_id=first.issue_id,
        category=first.category,
        severity=IssueSeverity.CRITICAL,
        source=first.source,
        reason="Duplicate",
        recommendation="Different",
        evidence=first.evidence,
        url=first.url,
    )

    assert dedupe_issues([first, duplicate]) == [duplicate]


def test_issues_for_site_report_includes_failed_rows_and_payload_issues() -> None:
    ok = SiteCrawlResult.from_payload("https://example.com/page", _payload())
    failed = SiteCrawlResult.failed("https://example.com/fail", "boom")
    report = SiteCrawlReport.from_results([ok, failed], discovered_count=2)

    issues = issues_for_site_report(report)
    ids = {issue.issue_id for issue in issues}

    assert "crawl.fetch_error" in ids
    assert "meta.title_missing" in ids
    assert any(issue.url == "https://example.com/fail" for issue in issues)
