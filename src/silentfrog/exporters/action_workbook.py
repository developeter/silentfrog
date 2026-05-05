from __future__ import annotations

from collections import defaultdict
from typing import Iterable

import xlsxwriter

from ..audit_issues import (
    AuditIssue,
    IssueCategory,
    IssueSeverity,
    issues_for_payload,
    issues_for_site_report,
    severity_rank,
)
from ..crawl_types import CrawlPayload
from ..site_crawl_types import SiteCrawlReport

ACTION_SHEET_NAMES = [
    "Read me - Legend",
    "Executive summary",
    "Prioritized issues",
    "Affected URLs",
    "Indexability blockers",
    "Content-meta actions",
    "Technical actions",
    "Images actions",
    "AI-GEO actions",
    "Appendix - raw data",
]

_ISSUE_HEADERS = ["Severity", "Category", "URL", "Issue", "Evidence", "Recommendation", "Source", "Confidence"]


class ActionFormats:
    def __init__(self, workbook: xlsxwriter.Workbook) -> None:
        self.header = workbook.add_format({"bold": True, "bg_color": "#D1E7DD", "border": 1})
        self.wrap = workbook.add_format({"text_wrap": True, "valign": "top"})
        self.critical = workbook.add_format({"bg_color": "#F8D7DA", "text_wrap": True, "valign": "top"})
        self.warning = workbook.add_format({"bg_color": "#FFF3CD", "text_wrap": True, "valign": "top"})
        self.info = workbook.add_format({"bg_color": "#DDEBFF", "text_wrap": True, "valign": "top"})

    def severity(self, severity: IssueSeverity):
        return {
            IssueSeverity.CRITICAL: self.critical,
            IssueSeverity.WARNING: self.warning,
            IssueSeverity.INFO: self.info,
        }[severity]


def write_site_crawl_action_sheets(workbook: xlsxwriter.Workbook, report: SiteCrawlReport) -> None:
    formats = ActionFormats(workbook)
    issues = issues_for_site_report(report)
    _write_action_front_matter(workbook, formats, "Site crawl")
    _write_executive_summary(workbook, formats, _site_summary_rows(report, issues))
    _write_issue_sheet(workbook, formats, "Prioritized issues", issues)
    _write_affected_urls(workbook, formats, issues)
    _write_category_sheets(workbook, formats, issues)
    _write_appendix(workbook, formats, _site_appendix_rows())


def write_page_action_sheets(workbook: xlsxwriter.Workbook, payload: CrawlPayload) -> None:
    formats = ActionFormats(workbook)
    page_url = _page_url(payload)
    issues = issues_for_payload(page_url, payload)
    _write_action_front_matter(workbook, formats, "Single page")
    _write_executive_summary(workbook, formats, _page_summary_rows(page_url, issues))
    _write_issue_sheet(workbook, formats, "Prioritized issues", issues)
    _write_affected_urls(workbook, formats, issues)
    _write_category_sheets(workbook, formats, issues)
    _write_appendix(workbook, formats, _page_appendix_rows())


def _write_action_front_matter(workbook: xlsxwriter.Workbook, formats: ActionFormats, scope: str) -> None:
    rows = [
        ["Workbook purpose", "This report starts with prioritized actions. Raw/detail sheets follow as appendix evidence."],
        ["Scope", scope],
        ["Critical / red", "Only blockers or high-confidence damage."],
        ["Warning / yellow", "Issues worth reviewing, not necessarily immediate blockers."],
        ["Opportunity / blue", "Informational improvements or lower-risk opportunities."],
        ["Privacy", "The workbook is generated locally from the current crawl data."],
    ]
    _write_rows(workbook, "Read me - Legend", ["Topic", "Meaning"], rows, formats)


def _write_executive_summary(
    workbook: xlsxwriter.Workbook,
    formats: ActionFormats,
    rows: list[list[object]],
) -> None:
    _write_rows(workbook, "Executive summary", ["Metric", "Value"], rows, formats)


def _write_issue_sheet(
    workbook: xlsxwriter.Workbook,
    formats: ActionFormats,
    name: str,
    issues: Iterable[AuditIssue],
) -> None:
    rows = [_issue_row(issue) for issue in _sorted_issues(issues)]
    _write_rows(workbook, name, _ISSUE_HEADERS, rows or [_empty_issue_row()], formats, _issue_row_format)


def _write_affected_urls(
    workbook: xlsxwriter.Workbook,
    formats: ActionFormats,
    issues: Iterable[AuditIssue],
) -> None:
    rows = _affected_url_rows(issues)
    headers = ["URL", "Critical", "Warnings", "Opportunities", "Top issue", "Sources"]
    _write_rows(workbook, "Affected URLs", headers, rows or [["-", 0, 0, 0, "-", "-"]], formats)


def _write_category_sheets(
    workbook: xlsxwriter.Workbook,
    formats: ActionFormats,
    issues: list[AuditIssue],
) -> None:
    specs = {
        "Indexability blockers": {IssueCategory.INDEXABILITY},
        "Content-meta actions": {IssueCategory.META, IssueCategory.CONTENT},
        "Technical actions": {
            IssueCategory.CANONICAL,
            IssueCategory.CRAWL,
            IssueCategory.LINKS,
            IssueCategory.PERFORMANCE,
            IssueCategory.STRUCTURED_DATA,
        },
        "Images actions": {IssueCategory.IMAGES},
        "AI-GEO actions": {IssueCategory.AI_GEO},
    }
    for name, categories in specs.items():
        _write_issue_sheet(workbook, formats, name, _issues_in_categories(issues, categories))


def _write_appendix(
    workbook: xlsxwriter.Workbook,
    formats: ActionFormats,
    rows: list[list[str]],
) -> None:
    _write_rows(workbook, "Appendix - raw data", ["Sheet", "Contents"], rows, formats)


def _write_rows(
    workbook: xlsxwriter.Workbook,
    name: str,
    headers: list[str],
    rows: Iterable[Iterable[object]],
    formats: ActionFormats,
    row_formatter=None,
) -> None:
    worksheet = workbook.add_worksheet(name)
    materialized = [list(row) for row in rows]
    for column, header in enumerate(headers):
        worksheet.write(0, column, header, formats.header)
    for row_idx, row in enumerate(materialized, start=1):
        row_format = row_formatter(formats, row) if row_formatter else None
        for column, value in enumerate(row[: len(headers)]):
            worksheet.write(row_idx, column, value, row_format)
    worksheet.freeze_panes(1, 0)
    if materialized and headers:
        worksheet.autofilter(0, 0, len(materialized), len(headers) - 1)
    _size_columns(worksheet, headers, materialized)


def _site_summary_rows(report: SiteCrawlReport, issues: list[AuditIssue]) -> list[list[object]]:
    counts = _severity_counts(issues)
    return [
        ["Report type", "Site crawl"],
        ["Discovered URLs", report.discovered_count],
        ["Crawled URLs", report.crawled_count],
        ["Failed URLs", report.failed_count],
        ["Skipped URLs", report.skipped_count],
        ["Total prioritized issues", len(issues)],
        ["Critical blockers", counts[IssueSeverity.CRITICAL]],
        ["Warnings", counts[IssueSeverity.WARNING]],
        ["Opportunities", counts[IssueSeverity.INFO]],
        ["Top priority", _top_issue_text(issues)],
    ]


def _page_summary_rows(url: str, issues: list[AuditIssue]) -> list[list[object]]:
    counts = _severity_counts(issues)
    return [
        ["Report type", "Single page"],
        ["Page URL", url or "-"],
        ["Total prioritized issues", len(issues)],
        ["Critical blockers", counts[IssueSeverity.CRITICAL]],
        ["Warnings", counts[IssueSeverity.WARNING]],
        ["Opportunities", counts[IssueSeverity.INFO]],
        ["Top priority", _top_issue_text(issues)],
    ]


def _affected_url_rows(issues: Iterable[AuditIssue]) -> list[list[object]]:
    grouped: dict[str, list[AuditIssue]] = defaultdict(list)
    for issue in issues:
        grouped[issue.url or "Site-wide"].append(issue)
    return [_affected_url_row(url, rows) for url, rows in sorted(grouped.items())]


def _affected_url_row(url: str, issues: list[AuditIssue]) -> list[object]:
    counts = _severity_counts(issues)
    top = _top_issue_text(issues)
    sources = ", ".join(dict.fromkeys(issue.source for issue in issues if issue.source)) or "-"
    return [
        url,
        counts[IssueSeverity.CRITICAL],
        counts[IssueSeverity.WARNING],
        counts[IssueSeverity.INFO],
        top,
        sources,
    ]


def _issue_row(issue: AuditIssue) -> list[str]:
    return [
        issue.severity.value.title(),
        issue.category.value.replace("_", " ").title(),
        issue.url or "-",
        issue.reason,
        _evidence_text(issue),
        issue.recommendation,
        issue.source,
        issue.confidence,
    ]


def _empty_issue_row() -> list[str]:
    return ["Info", "-", "-", "No prioritized issues detected.", "-", "-", "-", "-"]


def _issue_row_format(formats: ActionFormats, row: list[object]):
    severity = {
        "Critical": IssueSeverity.CRITICAL,
        "Warning": IssueSeverity.WARNING,
        "Info": IssueSeverity.INFO,
    }.get(str(row[0]), IssueSeverity.INFO)
    return formats.severity(severity)


def _issues_in_categories(issues: Iterable[AuditIssue], categories: set[IssueCategory]) -> list[AuditIssue]:
    return [issue for issue in issues if issue.category in categories]


def _sorted_issues(issues: Iterable[AuditIssue]) -> list[AuditIssue]:
    return sorted(issues, key=lambda issue: (severity_rank(issue.severity), issue.category.value, issue.url))


def _severity_counts(issues: Iterable[AuditIssue]) -> dict[IssueSeverity, int]:
    rows = list(issues)
    return {severity: sum(1 for issue in rows if issue.severity == severity) for severity in IssueSeverity}


def _top_issue_text(issues: list[AuditIssue]) -> str:
    rows = _sorted_issues(issues)
    return rows[0].reason if rows else "-"


def _evidence_text(issue: AuditIssue) -> str:
    return "; ".join(f"{item.label}: {item.value}" for item in issue.evidence) or "-"


def _page_url(payload: CrawlPayload) -> str:
    return payload.serp.url or (payload.redirect.chain[0] if payload.redirect.chain else "")


def _site_appendix_rows() -> list[list[str]]:
    return [
        ["Summary", "Raw crawl overview, one row per URL."],
        ["Detail sheets", "Consolidated page evidence grouped by area."],
        ["Errors", "Failed or skipped URLs and their reasons."],
    ]


def _page_appendix_rows() -> list[list[str]]:
    return [
        ["Meta / Headers / Images", "Raw page-level evidence."],
        ["Indexability / Robots / Canonical", "Technical crawl evidence."],
        ["Performance / AI Visibility", "Specialized audit evidence and opportunities."],
    ]


def _size_columns(worksheet, headers: list[str], rows: list[list[object]]) -> None:
    for column, header in enumerate(headers):
        values = [str(row[column]) for row in rows if column < len(row)]
        width = min(80, max([len(header), *[len(value) for value in values], 10]) + 2)
        worksheet.set_column(column, column, width)


__all__ = [
    "ACTION_SHEET_NAMES",
    "write_page_action_sheets",
    "write_site_crawl_action_sheets",
]
