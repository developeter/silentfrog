from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from .crawl_run_repository import open_report_repository
from .crawl_types import CrawlPayload
from .image_diagnostics import DIAGNOSTIC_COL, SRC_COL
from .indexability import build_indexability_rows
from .site_crawl_types import SiteCrawlReport, SiteCrawlResult


class IssueSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class IssueCategory(str, Enum):
    INDEXABILITY = "indexability"
    META = "meta"
    CONTENT = "content"
    CANONICAL = "canonical"
    LINKS = "links"
    IMAGES = "images"
    STRUCTURED_DATA = "structured_data"
    PERFORMANCE = "performance"
    AI_GEO = "ai_geo"
    LOGS = "logs"
    CRAWL = "crawl"
    ACCESSIBILITY = "accessibility"


@dataclass(frozen=True, slots=True)
class IssueEvidence:
    label: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"label": self.label, "value": self.value}


@dataclass(frozen=True, slots=True)
class AuditIssue:
    issue_id: str
    category: IssueCategory
    severity: IssueSeverity
    source: str
    reason: str
    recommendation: str
    evidence: tuple[IssueEvidence, ...]
    url: str = ""
    scope: str = "page"
    confidence: str = "high"

    def key(self) -> tuple[str, str, str]:
        return self.issue_id, self.url, self.scope

    def to_dict(self) -> dict[str, object]:
        """JSON-native serialization for CLI/export surfaces (M6 log issues)."""
        return {
            "issue_id": self.issue_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "source": self.source,
            "reason": self.reason,
            "recommendation": self.recommendation,
            "evidence": [item.to_dict() for item in self.evidence],
            "url": self.url,
            "scope": self.scope,
            "confidence": self.confidence,
        }


def issues_for_payload(url: str, payload: CrawlPayload) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    issues.extend(_indexability_issues(url, payload))
    issues.extend(_meta_issues(url, payload))
    issues.extend(_content_issues(url, payload))
    issues.extend(_image_issues(url, payload.images))
    issues.extend(_link_issues(url, payload.links))
    issues.extend(_structured_data_issues(url, payload))
    issues.extend(_performance_issues(url, payload))
    issues.extend(_ai_visibility_issues(url, payload))
    issues.extend(_accessibility_issues(url, payload))
    return dedupe_issues(issues)


def issues_for_site_report(report: SiteCrawlReport) -> list[AuditIssue]:
    """Aggregate issues across a crawl by streaming every audited URL through the
    report's run-bound repository (H1/H2), so large store-backed crawls are never
    silently truncated to the first in-memory window. Successful rows carry their
    full payload (losslessly rebuilt, H0); failed/skipped rows contribute only
    their crawl-level issue."""
    issues: list[AuditIssue] = []
    with open_report_repository(report) as repo:
        for result in repo.stream_results():
            issues.extend(_site_result_issues(result))
            if result.payload:
                issues.extend(issues_for_payload(result.url, result.payload))
    return dedupe_issues(issues)


def dedupe_issues(issues: Iterable[AuditIssue]) -> list[AuditIssue]:
    output: list[AuditIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in sorted(issues, key=_issue_sort_key):
        key = issue.key()
        if key in seen:
            continue
        output.append(issue)
        seen.add(key)
    return output


def severity_rank(severity: IssueSeverity) -> int:
    return {
        IssueSeverity.CRITICAL: 0,
        IssueSeverity.WARNING: 1,
        IssueSeverity.INFO: 2,
    }[severity]


def severity_color_role(severity: IssueSeverity) -> str:
    return {
        IssueSeverity.CRITICAL: "bad",
        IssueSeverity.WARNING: "warn",
        IssueSeverity.INFO: "info",
    }[severity]


def _issue_sort_key(issue: AuditIssue) -> tuple[int, str, str]:
    return severity_rank(issue.severity), issue.category.value, issue.url


def _site_result_issues(result: SiteCrawlResult) -> list[AuditIssue]:
    if result.status == "skipped":
        return []
    if result.status == "error":
        return [
            _issue(
                "crawl.fetch_error",
                IssueCategory.CRAWL,
                IssueSeverity.CRITICAL,
                result.url,
                "The URL could not be crawled.",
                "Review the error, retry with gentle crawl settings, or check whether the URL is reachable.",
                "Site Crawl",
                [("Error", result.error or "Unknown error")],
            )
        ]
    status = _to_int(result.status)
    if status and status >= 400:
        return [
            _issue(
                "crawl.http_error",
                IssueCategory.CRAWL,
                IssueSeverity.CRITICAL,
                result.url,
                "The page fetch returned an HTTP error.",
                "Fix the URL response or remove it from the crawl target set.",
                "Site Crawl",
                [("HTTP status", result.status)],
            )
        ]
    return []


def _indexability_issues(url: str, payload: CrawlPayload) -> list[AuditIssue]:
    rows = build_indexability_rows(
        payload.redirect.to_dict(),
        payload.canonical.to_dict(),
        payload.meta_robots,
        payload.robots,
    )
    verdict = _row_value(rows, "Overall verdict")
    if verdict in {"", "-", "Indexable"}:
        return []
    severity = IssueSeverity.WARNING if verdict == "Indexable with warnings" else IssueSeverity.CRITICAL
    return [
        _issue(
            f"indexability.{_slug(verdict)}",
            IssueCategory.INDEXABILITY,
            severity,
            url,
            f"The page is reported as {verdict}.",
            "Review robots, meta robots, canonical, redirects, and final HTTP status.",
            "Indexability",
            _row_evidence(rows),
        )
    ]


def _meta_issues(url: str, payload: CrawlPayload) -> list[AuditIssue]:
    title = _meta_value(payload, "title")
    description = _meta_value(payload, "description")
    issues: list[AuditIssue] = []
    if not title:
        issues.append(
            _issue(
                "meta.title_missing",
                IssueCategory.META,
                IssueSeverity.WARNING,
                url,
                "The page has no title tag.",
                "Add a unique, descriptive title.",
                "Meta",
                [("Title", "Missing")],
            )
        )
    if not description:
        issues.append(
            _issue(
                "meta.description_missing",
                IssueCategory.META,
                IssueSeverity.WARNING,
                url,
                "The page has no meta description.",
                "Add a concise meta description for search snippets and sharing context.",
                "Meta",
                [("Meta description", "Missing")],
            )
        )
    return issues


def _content_issues(url: str, payload: CrawlPayload) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    h1_count = sum(1 for row in payload.headers if row and str(row[0]).strip().lower() == "h1")
    if h1_count == 0:
        issues.append(
            _issue(
                "content.h1_missing",
                IssueCategory.CONTENT,
                IssueSeverity.WARNING,
                url,
                "The page has no H1 heading.",
                "Add one clear H1 that describes the primary page topic.",
                "Headers",
                [("H1 count", "0")],
            )
        )
    if h1_count > 1:
        issues.append(
            _issue(
                "content.h1_multiple",
                IssueCategory.CONTENT,
                IssueSeverity.INFO,
                url,
                "The page has multiple H1 headings.",
                "Review heading structure and keep one primary H1 where practical.",
                "Headers",
                [("H1 count", str(h1_count))],
            )
        )
    if payload.content_quality.verdict == "Weak":
        issues.append(
            _issue(
                "content.quality_weak",
                IssueCategory.CONTENT,
                IssueSeverity.WARNING,
                url,
                "The content quality verdict is weak.",
                "Review word count, intro clarity, heading structure, and title/H1 alignment.",
                "Content quality",
                _content_evidence(payload),
            )
        )
    return issues


def _image_issues(url: str, rows: Iterable[Sequence[object]]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for row in rows:
        diagnostic = _row_cell(row, DIAGNOSTIC_COL)
        if not diagnostic or diagnostic == "OK":
            continue
        issues.append(
            _issue(
                "images.diagnostic",
                IssueCategory.IMAGES,
                IssueSeverity.WARNING,
                url,
                "An image has optimization or implementation issues.",
                "Review dimensions, caching, responsive sizes, and format recommendations.",
                "Images",
                [("Image", _row_cell(row, SRC_COL) or "-"), ("Diagnostic", diagnostic)],
            )
        )
    return issues


def _link_issues(url: str, rows: Iterable[Sequence[object]]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for row in rows:
        status = _to_int(_row_cell(row, 4))
        if status and status < 400:
            continue
        issues.append(
            _issue(
                "links.bad_status",
                IssueCategory.LINKS,
                IssueSeverity.WARNING,
                url,
                "A link returned a fetch, client, or server error.",
                "Update, remove, or fix the linked target.",
                "Links",
                [("Link URL", _row_cell(row, 0) or "-"), ("Status", _row_cell(row, 4) or "0")],
            )
        )
    return issues


def _structured_data_issues(url: str, payload: CrawlPayload) -> list[AuditIssue]:
    issues = [
        _issue(
            "structured_data.error",
            IssueCategory.STRUCTURED_DATA,
            IssueSeverity.WARNING,
            url,
            "Structured data contains extraction or validation issues.",
            "Review the structured data block and fix the reported error.",
            "Structured data",
            [("Error", error)],
        )
        for error in payload.schema.summary.errors
    ]
    for item in payload.schema.eligibility:
        if item.eligibility.lower() in {"eligible", "not detected"}:
            continue
        issues.append(
            _issue(
                "structured_data.eligibility_incomplete",
                IssueCategory.STRUCTURED_DATA,
                IssueSeverity.WARNING,
                url,
                "Detected structured data is incomplete for a rich result opportunity.",
                "Add the missing recommended or required fields where relevant.",
                "Structured eligibility",
                [
                    ("Type", item.schema_type or "-"),
                    ("Eligibility", item.eligibility),
                    ("Missing fields", ", ".join(item.missing_fields) or "-"),
                ],
            )
        )
    return issues


def _performance_issues(url: str, payload: CrawlPayload) -> list[AuditIssue]:
    output: list[AuditIssue] = []
    for item in payload.performance.issues:
        output.append(
            _issue(
                f"performance.{item.key or 'issue'}",
                IssueCategory.PERFORMANCE,
                _severity_from_text(item.severity),
                url,
                item.message or "A performance issue was detected.",
                item.recommendation or "Review the performance evidence and optimize the affected resource.",
                "Performance",
                [("Evidence", item.evidence or "-")],
            )
        )
    return output


def _ai_visibility_issues(url: str, payload: CrawlPayload) -> list[AuditIssue]:
    output: list[AuditIssue] = []
    for check in payload.ai_visibility.checks:
        severity = _severity_from_text(check.status)
        if severity == IssueSeverity.INFO:
            continue
        output.append(
            _issue(
                f"ai_geo.{check.key or _slug(check.check)}",
                IssueCategory.AI_GEO,
                severity,
                url,
                check.details or check.check,
                check.recommendation or "Review the AI/GEO visibility recommendation.",
                "AI Visibility",
                [("Area", check.area), ("Check", check.check), ("Status", check.status)],
                confidence="medium",
            )
        )
    return output


# v3 G4 Stage 1: axe-core "impact" tiers -> issue severity. §1.5 — a
# measured-but-bad signal may warn/critical, but moderate/minor axe findings
# are numerous and often low real-world impact (e.g. redundant ARIA), so they
# stay info-level to keep the hints view high-signal; only critical/serious
# (broken keyboard access, missing labels, failed contrast, etc.) surface as
# actionable issues.
_IMPACT_SEVERITY = {
    "critical": IssueSeverity.CRITICAL,
    "serious": IssueSeverity.WARNING,
    "moderate": IssueSeverity.INFO,
    "minor": IssueSeverity.INFO,
}


def _accessibility_issues(url: str, payload: CrawlPayload) -> list[AuditIssue]:
    violations = payload.accessibility.get("violations")
    if not isinstance(violations, list):
        return []
    return [_accessibility_issue(url, item) for item in violations if isinstance(item, dict)]


def _accessibility_issue(url: str, violation: dict[str, object]) -> AuditIssue:
    rule_id = str(violation.get("id") or "unknown")
    impact = str(violation.get("impact") or "")
    help_text = str(violation.get("help") or "An accessibility rule failed.")
    help_url = str(violation.get("help_url") or "")
    node_count = violation.get("nodes", 0)
    recommendation = (
        f"Fix per {help_url}" if help_url else "Review the axe-core violation and fix the affected elements."
    )
    return _issue(
        f"accessibility.{rule_id}",
        IssueCategory.ACCESSIBILITY,
        _IMPACT_SEVERITY.get(impact, IssueSeverity.INFO),
        url,
        f"{help_text} ({node_count} element(s) affected).",
        recommendation,
        "Accessibility",
        [("Rule", rule_id), ("Impact", impact or "-"), ("Elements affected", node_count)],
    )


def _issue(
    issue_id: str,
    category: IssueCategory,
    severity: IssueSeverity,
    url: str,
    reason: str,
    recommendation: str,
    source: str,
    evidence: Iterable[tuple[str, object]],
    *,
    scope: str = "page",
    confidence: str = "high",
) -> AuditIssue:
    return AuditIssue(
        issue_id=issue_id,
        category=category,
        severity=severity,
        source=source,
        reason=reason,
        recommendation=recommendation,
        evidence=tuple(IssueEvidence(str(label), str(value)) for label, value in evidence),
        url=url,
        scope=scope,
        confidence=confidence,
    )


def _severity_from_text(value: str) -> IssueSeverity:
    normalized = value.strip().lower()
    if normalized in {"critical", "bad", "high", "weak"}:
        return IssueSeverity.CRITICAL
    if normalized in {"warning", "warn", "needs work", "medium"}:
        return IssueSeverity.WARNING
    return IssueSeverity.INFO


def _meta_value(payload: CrawlPayload, name: str) -> str:
    expected = name.lower()
    for row in payload.meta:
        if len(row) > 1 and str(row[0]).strip().lower() == expected:
            return str(row[1]).strip()
    return ""


def _row_value(rows: Iterable[Sequence[object]], key: str) -> str:
    expected = key.lower()
    for row in rows:
        if len(row) > 1 and str(row[0]).strip().lower() == expected:
            return str(row[1]).strip()
    return ""


def _row_evidence(rows: Iterable[Sequence[object]]) -> tuple[tuple[str, str], ...]:
    return tuple((str(row[0]), str(row[1])) for row in rows if len(row) > 1)


def _content_evidence(payload: CrawlPayload) -> list[tuple[str, object]]:
    quality = payload.content_quality
    return [
        ("Word count", quality.word_count),
        ("Thin content risk", quality.thin_content_risk or "-"),
        ("Heading structure", quality.heading_structure or "-"),
        ("Title/H1 alignment", quality.title_h1_alignment or "-"),
    ]


def _row_cell(row: Sequence[object], index: int) -> str:
    if len(row) <= index:
        return ""
    return str(row[index]).strip()


def _to_int(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _slug(value: str) -> str:
    return "_".join(part for part in value.strip().lower().replace("/", " ").split() if part)


__all__ = [
    "AuditIssue",
    "IssueCategory",
    "IssueEvidence",
    "IssueSeverity",
    "dedupe_issues",
    "issues_for_payload",
    "issues_for_site_report",
    "severity_color_role",
    "severity_rank",
]
