from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import xlsxwriter

from ..content_quality import build_content_quality_rows
from ..crawl_types import CrawlPayload
from ..image_diagnostics import IMAGE_HEADERS, normalize_image_rows
from ..indexability import build_indexability_rows
from ..site_crawl_types import SITE_CRAWL_HEADERS, SiteCrawlReport, SiteCrawlResult
from .action_workbook import write_site_crawl_action_sheets

_PayloadRows = list[tuple[str, CrawlPayload]]


def export_site_crawl_report(report: SiteCrawlReport, file_path: Path) -> None:
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    results = list(report.results)
    payload_rows = _payload_rows(results)
    with xlsxwriter.Workbook(str(file_path)) as workbook:
        formats = _WorkbookFormats(workbook)
        write_site_crawl_action_sheets(workbook, report)
        _write_summary_sheets(workbook, formats, results)
        _write_detail_sheets(workbook, formats, payload_rows)


class _WorkbookFormats:
    def __init__(self, workbook: xlsxwriter.Workbook) -> None:
        self.header = workbook.add_format({"bold": True, "bg_color": "#D1E7DD", "border": 1})
        self.warning = workbook.add_format({"bg_color": "#FFF3CD"})
        self.bad = workbook.add_format({"bg_color": "#F8D7DA"})


def _write_summary_sheets(
    workbook: xlsxwriter.Workbook,
    formats: _WorkbookFormats,
    results: list[SiteCrawlResult],
) -> None:
    _write_rows(workbook, "Summary", SITE_CRAWL_HEADERS, [result.row() for result in results], formats)
    _write_rows(workbook, "Indexability issues", _issue_headers(), _indexability_rows(results), formats)
    _write_rows(workbook, "Meta issues", _issue_headers(), _meta_issue_rows(results), formats)
    _write_rows(
        workbook,
        "Structured data",
        ["URL", "Schema count", "Types", "Error count"],
        _structured_rows(results),
        formats,
    )
    _write_rows(workbook, "Images", ["URL", "Images", "Image issues"], _image_rows(results), formats)
    _write_rows(
        workbook,
        "GEO Score",
        ["URL", "Score", "Verdict", "Good", "Warning", "Critical"],
        _geo_score_rows(results),
        formats,
    )
    _write_rows(
        workbook,
        "AI Visibility",
        ["URL", "Verdict", "Good", "Warning", "Critical"],
        _ai_rows(results),
        formats,
    )
    _write_rows(workbook, "Errors", ["URL", "Status", "Error"], _error_rows(results), formats)


def _write_detail_sheets(
    workbook: xlsxwriter.Workbook,
    formats: _WorkbookFormats,
    rows: _PayloadRows,
) -> None:
    detail_specs = [
        ("Meta detail", ["Page URL", "Name/Property", "Content", "Length"], _meta_detail_rows(rows)),
        ("Headers detail", ["Page URL", "Tag", "Text"], _headers_detail_rows(rows)),
        ("Images detail", ["Page URL", *IMAGE_HEADERS], _images_detail_rows(rows)),
        ("Links detail", _links_headers(), _links_detail_rows(rows)),
        ("Redirect detail", ["Page URL", "Check", "Value"], _redirect_detail_rows(rows)),
        ("Canonical detail", ["Page URL", "Check", "Value"], _canonical_detail_rows(rows)),
        ("Indexability detail", ["Page URL", "Check", "Value"], _indexability_detail_rows(rows)),
        ("Robots detail", ["Page URL", "Directive", "Value"], _robots_detail_rows(rows)),
        ("Hreflang detail", _hreflang_headers(), _hreflang_detail_rows(rows)),
        ("Structured detail", ["Page URL", "Source", "Type", "Errors", "Raw"], _structured_detail_rows(rows)),
        ("Structured eligibility", _structured_eligibility_headers(), _structured_eligibility_rows(rows)),
        ("Content quality detail", ["Page URL", "Check", "Value"], _content_quality_detail_rows(rows)),
        ("Keywords detail", _keyword_headers(), _keyword_detail_rows(rows)),
        ("AI crawl detail", _ai_crawl_headers(), _ai_crawl_detail_rows(rows)),
        ("GEO Score detail", _geo_score_detail_headers(), _geo_score_detail_rows(rows)),
        ("AI Visibility detail", _ai_visibility_headers(), _ai_visibility_detail_rows(rows)),
        ("Performance detail", _performance_headers(), _performance_detail_rows(rows)),
        ("SERP detail", ["Page URL", "Section", "Field", "Value"], _serp_detail_rows(rows)),
        ("Social detail", _social_headers(), _social_detail_rows(rows)),
    ]
    for name, headers, detail_rows in detail_specs:
        _write_rows(workbook, name, headers, detail_rows or [_empty_row(headers)], formats)


def _write_rows(
    workbook: xlsxwriter.Workbook,
    name: str,
    headers: list[str],
    rows: Iterable[Iterable[object]],
    formats: _WorkbookFormats,
) -> None:
    worksheet = workbook.add_worksheet(name[:31])
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, formats.header)
    materialized = [list(row) for row in rows]
    for row_idx, row in enumerate(materialized, start=1):
        for col_idx, value in enumerate(row[: len(headers)]):
            worksheet.write(row_idx, col_idx, value)
    if headers:
        worksheet.freeze_panes(1, 0)
    if materialized and headers:
        worksheet.autofilter(0, 0, len(materialized), len(headers) - 1)
    _size_columns(worksheet, headers, materialized)


def _size_columns(worksheet, headers: list[str], rows: list[list[object]]) -> None:
    for col_idx, header in enumerate(headers):
        values = [str(row[col_idx]) for row in rows if col_idx < len(row)]
        width = min(80, max([len(header), *[len(value) for value in values], 10]) + 2)
        worksheet.set_column(col_idx, col_idx, width)


def _payload_rows(results: Iterable[SiteCrawlResult]) -> _PayloadRows:
    return [(result.url, result.payload) for result in results if result.payload]


def _empty_row(headers: list[str]) -> list[str]:
    return ["-"] * len(headers)


def _pad(row: Iterable[object], length: int) -> list[object]:
    values = list(row)
    return [*values[:length], *([""] * max(0, length - len(values)))]


def _json_value(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def _join(values: Iterable[object]) -> str:
    return ", ".join(str(value).strip() for value in values if str(value).strip()) or "-"


def _issue_headers() -> list[str]:
    return ["URL", "Issue", "Evidence", "Recommendation"]


def _indexability_rows(results: Iterable[SiteCrawlResult]) -> list[list[str]]:
    rows: list[list[str]] = []
    for result in results:
        verdict = result.indexability.strip()
        if verdict in {"", "-", "Indexable", "Skipped", "Failed"}:
            continue
        rows.append(
            [
                result.url,
                "Indexability risk",
                verdict,
                "Review robots, canonical, redirects, and meta robots.",
            ]
        )
    return rows or [["-", "-", "-", "-"]]


def _meta_issue_rows(results: Iterable[SiteCrawlResult]) -> list[list[str]]:
    rows: list[list[str]] = []
    title_counts = _text_counts(result.title for result in results)
    for result in results:
        rows.extend(_single_meta_rows(result, title_counts))
    return rows or [["-", "-", "-", "-"]]


def _single_meta_rows(result: SiteCrawlResult, title_counts: Counter[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    if not result.title:
        rows.append([result.url, "Missing title", "No title found", "Add a unique descriptive title."])
    elif title_counts[result.title.strip().lower()] > 1:
        rows.append([result.url, "Duplicate title", result.title, "Make the title unique for this URL."])
    if result.description_state not in {"", "OK"}:
        rows.append(
            [
                result.url,
                "Meta description",
                result.description_state,
                "Review description length and presence.",
            ]
        )
    return rows


def _text_counts(values: Iterable[str]) -> Counter[str]:
    normalized = [value.strip().lower() for value in values if value.strip()]
    return Counter(normalized)


def _structured_rows(results: Iterable[SiteCrawlResult]) -> list[list[object]]:
    rows: list[list[object]] = []
    for result in results:
        if not result.payload:
            continue
        summary = result.payload.schema.summary
        rows.append([result.url, summary.total, ", ".join(summary.by_type.keys()) or "-", len(summary.errors)])
    return rows or [["-", 0, "-", 0]]


def _image_rows(results: Iterable[SiteCrawlResult]) -> list[list[object]]:
    rows = [[result.url, len(result.payload.images), result.image_issue_count] for result in results if result.payload]
    return rows or [["-", 0, 0]]


def _ai_rows(results: Iterable[SiteCrawlResult]) -> list[list[object]]:
    rows: list[list[object]] = []
    for result in results:
        if not result.payload:
            continue
        summary = result.payload.ai_visibility.summary
        rows.append(
            [
                result.url,
                summary.verdict or "-",
                summary.good_count,
                summary.warning_count,
                summary.critical_count,
            ]
        )
    return rows or [["-", "-", 0, 0, 0]]


def _geo_score_rows(results: Iterable[SiteCrawlResult]) -> list[list[object]]:
    rows: list[list[object]] = []
    for result in results:
        if not result.payload:
            continue
        summary = result.payload.ai_visibility.summary
        rows.append(
            [
                result.url,
                summary.score,
                summary.verdict or "-",
                summary.good_count,
                summary.warning_count,
                summary.critical_count,
            ]
        )
    return rows or [["-", 0, "-", 0, 0, 0]]


def _geo_score_detail_headers() -> list[str]:
    return ["Page URL", "Score", "Area", "Check", "Status", "Key", "Details", "Recommendation"]


def _geo_score_detail_rows(rows: _PayloadRows) -> list[list[object]]:
    out: list[list[object]] = []
    for url, payload in rows:
        score = payload.ai_visibility.summary.score
        for check in payload.ai_visibility.checks:
            out.append(
                [
                    url,
                    score,
                    check.area,
                    check.check,
                    check.status.title(),
                    check.key,
                    check.details,
                    check.recommendation,
                ]
            )
    return out


def _error_rows(results: Iterable[SiteCrawlResult]) -> list[list[str]]:
    rows = [
        [result.url, result.status, result.error]
        for result in results
        if result.error or result.status in {"error", "skipped"}
    ]
    return rows or [["-", "-", "-"]]


def _meta_detail_rows(rows: _PayloadRows) -> list[list[object]]:
    return [[url, *_pad(row, 3)] for url, payload in rows for row in payload.meta]


def _headers_detail_rows(rows: _PayloadRows) -> list[list[object]]:
    return [[url, *_pad(row, 2)] for url, payload in rows for row in payload.headers]


def _images_detail_rows(rows: _PayloadRows) -> list[list[object]]:
    return [[url, *row] for url, payload in rows for row in normalize_image_rows(payload.images)]


def _links_headers() -> list[str]:
    return ["Page URL", "URL", "Anchor", "Type", "Rel", "Status", "Status note", "Section", "Heading", "TLD"]


def _links_detail_rows(rows: _PayloadRows) -> list[list[object]]:
    return [[url, *_pad(row, 9)] for url, payload in rows for row in payload.links]


def _redirect_detail_rows(rows: _PayloadRows) -> list[list[str]]:
    return [row for url, payload in rows for row in _redirect_rows(url, payload)]


def _redirect_rows(url: str, payload: CrawlPayload) -> list[list[str]]:
    return [
        [url, "Redirect chain", " -> ".join(payload.redirect.chain)],
        [url, "Hop count", str(payload.redirect.hops)],
        [url, "Final status", payload.redirect.final_status],
        [url, "Loop detected", "Yes" if payload.redirect.loop else "No"],
    ]


def _canonical_detail_rows(rows: _PayloadRows) -> list[list[str]]:
    return [row for url, payload in rows for row in _canonical_rows(url, payload)]


def _canonical_rows(url: str, payload: CrawlPayload) -> list[list[str]]:
    return [
        [url, "Canonical URL", payload.canonical.target or "-"],
        [url, "Self-referencing", "Yes" if payload.canonical.is_self else "No"],
        [url, "Multiple canonicals", "Yes" if payload.canonical.multiple else "No"],
        [url, "Canonical status", payload.canonical.status or "-"],
    ]


def _indexability_detail_rows(rows: _PayloadRows) -> list[list[str]]:
    output: list[list[str]] = []
    for url, payload in rows:
        output.extend([url, *row] for row in _indexability_rows_for_payload(payload))
    return output


def _indexability_rows_for_payload(payload: CrawlPayload) -> list[list[str]]:
    return build_indexability_rows(
        payload.redirect.to_dict(),
        payload.canonical.to_dict(),
        payload.meta_robots,
        payload.robots,
    )


def _robots_detail_rows(rows: _PayloadRows) -> list[list[str]]:
    return [row for url, payload in rows for row in _robots_rows(url, payload)]


def _robots_rows(url: str, payload: CrawlPayload) -> list[list[str]]:
    output = [[url, "Meta robots", payload.meta_robots or "-"]]
    for agent, directives in payload.robots.items():
        output.append([url, f"User-agent: {agent}", ""])
        output.extend([url, verb, value] for verb, value in directives)
    return output


def _hreflang_headers() -> list[str]:
    return ["Page URL", "Lang", "Target URL", "Status", "Lang-OK?", "Return?"]


def _hreflang_detail_rows(rows: _PayloadRows) -> list[list[object]]:
    return [[url, *_pad(row, 5)] for url, payload in rows for row in payload.hreflang]


def _structured_detail_rows(rows: _PayloadRows) -> list[list[str]]:
    return [row for url, payload in rows for row in _structured_rows_for_payload(url, payload)]


def _structured_rows_for_payload(url: str, payload: CrawlPayload) -> list[list[str]]:
    rows = [_structured_block_row(url, item) for item in payload.schema.blocks]
    fallback_rows = [[url, "fallback", "", "-", raw] for raw in payload.schema.fallback_raw]
    return [*rows, *fallback_rows]


def _structured_block_row(url: str, item: Any) -> list[str]:
    if isinstance(item, Mapping):
        errors = _join(item.get("_schema_errors", []))
        raw = {key: value for key, value in item.items() if key != "_schema_errors"}
        return [
            url,
            str(item.get("_extracted_via", "")),
            _schema_type_label(item.get("@type")),
            errors,
            _json_value(raw),
        ]
    source = "list" if isinstance(item, list) else ""
    return [url, source, "", "-", _json_value(item)]


def _schema_type_label(value: Any) -> str:
    candidate = _first_schema_type(value)
    for separator in ("#", "/"):
        if separator in candidate:
            candidate = candidate.rsplit(separator, 1)[-1]
    return candidate.strip()


def _first_schema_type(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return ""


def _structured_eligibility_headers() -> list[str]:
    return ["Page URL", "Type", "Detected", "Eligibility", "Missing fields", "Warnings"]


def _structured_eligibility_rows(rows: _PayloadRows) -> list[list[object]]:
    output: list[list[object]] = []
    for url, payload in rows:
        output.extend(_eligibility_row(url, item) for item in payload.schema.eligibility)
    return output


def _eligibility_row(url: str, item) -> list[object]:
    return [
        url,
        item.schema_type,
        "Yes" if item.detected else "No",
        item.eligibility,
        _join(item.missing_fields),
        _join(item.warnings),
    ]


def _content_quality_detail_rows(rows: _PayloadRows) -> list[list[str]]:
    return [[url, *row] for url, payload in rows for row in build_content_quality_rows(payload.content_quality)]


def _keyword_headers() -> list[str]:
    return [
        "Page URL",
        "Keyword",
        "Type",
        "Frequency",
        "Density %",
        "In Title",
        "Meta Description",
        "Headings",
        "1st Occurrence",
        "Density warning",
    ]


def _keyword_detail_rows(rows: _PayloadRows) -> list[list[object]]:
    return [row for url, payload in rows for row in _keyword_rows(url, payload)]


def _keyword_rows(url: str, payload: CrawlPayload) -> list[list[object]]:
    return [
        [
            url,
            entry.term,
            f"{entry.length}-gram",
            entry.frequency,
            f"{entry.density:.2f}",
            "Yes" if entry.in_title else "No",
            "Yes" if entry.in_description else "No",
            entry.heading_count,
            "-" if entry.first_position is None else entry.first_position + 1,
            "Yes" if entry.density_warning else "No",
        ]
        for entry in payload.keywords
    ]


def _ai_crawl_headers() -> list[str]:
    return [
        "Page URL",
        "Agent",
        "Token",
        "Robots.txt OK",
        "Nonstandard directive",
        "Google controls",
        "Verdict",
        "Notes",
    ]


def _ai_crawl_detail_rows(rows: _PayloadRows) -> list[list[object]]:
    return [[url, *_pad(row, 7)] for url, payload in rows for row in payload.ai_crawl]


def _ai_visibility_headers() -> list[str]:
    return ["Page URL", "Area", "Check", "Status", "Details", "Recommendation"]


def _ai_visibility_detail_rows(rows: _PayloadRows) -> list[list[str]]:
    return [row for url, payload in rows for row in _ai_visibility_rows(url, payload)]


def _ai_visibility_rows(url: str, payload: CrawlPayload) -> list[list[str]]:
    return [
        [url, check.area, check.check, check.status.title(), check.details, check.recommendation]
        for check in payload.ai_visibility.checks
    ]


def _performance_headers() -> list[str]:
    return ["Page URL", "Section", "Name", "Value", "Evidence", "Recommendation"]


def _performance_detail_rows(rows: _PayloadRows) -> list[list[object]]:
    return [row for url, payload in rows for row in _performance_rows(url, payload)]


def _performance_rows(url: str, payload: CrawlPayload) -> list[list[object]]:
    return [
        *_performance_summary_rows(url, payload),
        *_performance_resource_rows(url, payload),
        *_performance_script_rows(url, payload),
        *_performance_issue_rows(url, payload),
        *_performance_opportunity_rows(url, payload),
        *_performance_offender_rows(url, payload),
    ]


def _performance_summary_rows(url: str, payload: CrawlPayload) -> list[list[object]]:
    metrics = payload.performance.summary.to_dict()
    return [[url, "Summary", label.replace("_", " ").title(), value, "", ""] for label, value in metrics.items()]


def _performance_resource_rows(url: str, payload: CrawlPayload) -> list[list[object]]:
    return [
        [url, "Resource", item.resource_type.upper(), item.count, f"{item.bytes} bytes", ""]
        for item in payload.performance.resource_breakdown
    ]


def _performance_script_rows(url: str, payload: CrawlPayload) -> list[list[object]]:
    scripts = payload.performance.scripts
    return [
        [url, "Script", "Blocking", scripts.blocking_count, f"{scripts.blocking_bytes} bytes", ""],
        [url, "Script", "Async/Deferred", scripts.async_count, f"{scripts.async_bytes} bytes", ""],
    ]


def _performance_issue_rows(url: str, payload: CrawlPayload) -> list[list[str]]:
    return [
        [url, "Issue", item.severity.title(), item.message, item.evidence, item.recommendation]
        for item in payload.performance.issues
    ]


def _performance_opportunity_rows(url: str, payload: CrawlPayload) -> list[list[str]]:
    detail_rows = [
        [url, "Opportunity", item.severity.title(), item.message, "", ""]
        for item in payload.performance.opportunity_details
    ]
    legacy_rows = [[url, "Opportunity", "Info", item, "", ""] for item in payload.performance.opportunities]
    return [*detail_rows, *legacy_rows]


def _performance_offender_rows(url: str, payload: CrawlPayload) -> list[list[object]]:
    return [
        [
            url,
            "Top offender",
            item.resource_type.upper(),
            item.url,
            f"{item.bytes} bytes",
            "Blocking" if item.blocking else "Async",
        ]
        for item in payload.performance.top_offenders
    ]


def _serp_detail_rows(rows: _PayloadRows) -> list[list[object]]:
    return [row for url, payload in rows for row in _serp_rows(url, payload)]


def _serp_rows(url: str, payload: CrawlPayload) -> list[list[object]]:
    preview = [[url, "Preview", key.replace("_", " ").title(), value] for key, value in payload.serp.to_dict().items()]
    audit = [
        [url, "Audit", key.replace("_", " ").title(), value] for key, value in payload.serp_audit.to_dict().items()
    ]
    return [*preview, *audit]


def _social_headers() -> list[str]:
    return [
        "Page URL",
        "Source",
        "Title",
        "Description",
        "Image",
        "Card",
        "Image type",
        "Image size",
        "Issues",
    ]


def _social_detail_rows(rows: _PayloadRows) -> list[list[object]]:
    return [row for url, payload in rows for row in _social_rows(url, payload)]


def _social_rows(url: str, payload: CrawlPayload) -> list[list[object]]:
    cards = (("OpenGraph", payload.social.open_graph), ("Twitter", payload.social.twitter))
    return [
        [
            url,
            source,
            card.title,
            card.description,
            card.image,
            card.card,
            card.image_type,
            f"{card.image_width}x{card.image_height}" if card.image_width and card.image_height else "-",
            _join(card.issues),
        ]
        for source, card in cards
    ]


__all__ = ["export_site_crawl_report"]
