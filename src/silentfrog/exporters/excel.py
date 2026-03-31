from __future__ import annotations

import json
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, List, Sequence

import xlsxwriter

from ..crawl_types import AiVisibilityPayload, CrawlPayload, PerformanceMetrics
from ..content_quality import build_content_quality_rows
from ..image_diagnostics import (
    ALT_COL,
    CACHE_COL,
    DECLARED_HEIGHT_COL,
    DECLARED_WIDTH_COL,
    DIAGNOSTIC_COL,
    FETCH_PRIORITY_COL,
    FORMAT_HINT_COL,
    IMAGE_HEADERS,
    SIZE_COL,
    normalize_image_rows,
)
from ..indexability import build_indexability_rows

Formatter = Callable[[int, int, str], xlsxwriter.format.Format | None]
SummaryRow = tuple[str, str, xlsxwriter.format.Format | None]

_PIXELS_PER_CHAR = 7.2
_TITLE_MIN, _TITLE_MAX = 200, 600
_DESCRIPTION_MIN, _DESCRIPTION_MAX = 400, 920
_WARN_MARGIN = 40
_AI_VISIBILITY_VERDICT_STYLES = {"strong": "good", "needs work": "warn", "weak": "bad"}
_PERFORMANCE_VERDICT_STYLES = {
    "good": "good",
    "needs work": "warn",
    "high performance risk": "bad",
}


class _Formats:
    def __init__(self, workbook: xlsxwriter.Workbook) -> None:
        self.good = workbook.add_format({"bg_color": "#D1E7DD"})
        self.warn = workbook.add_format({"bg_color": "#FFF3CD"})
        self.bad = workbook.add_format({"bg_color": "#F8D7DA"})


def _pixel_brush(formats: _Formats, pixels: float, min_px: int, max_px: int):
    if pixels <= 0:
        return formats.bad
    if pixels < min_px - _WARN_MARGIN or pixels > max_px + _WARN_MARGIN:
        return formats.bad
    if pixels < min_px or pixels > max_px:
        return formats.warn
    if pixels < min_px + _WARN_MARGIN or pixels > max_px - _WARN_MARGIN:
        return formats.warn
    return formats.good


def _write_sheet(
    workbook: xlsxwriter.Workbook,
    name: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    formatter: Formatter | None = None,
) -> None:
    sheet_name = name[:31]
    worksheet = workbook.add_worksheet(sheet_name)

    for col, header in enumerate(headers):
        worksheet.write(0, col, header)

    has_rows = False
    for row_idx, row in enumerate(rows, start=1):
        has_rows = True
        for col_idx, cell in enumerate(row[: len(headers)]):
            fmt = formatter(row_idx - 1, col_idx, cell) if formatter else None
            worksheet.write(row_idx, col_idx, cell, fmt)

    if has_rows and headers:
        worksheet.autofilter(0, 0, row_idx, len(headers) - 1)
    if headers:
        worksheet.freeze_panes(1, 0)


def _sheet(workbook: xlsxwriter.Workbook, name: str):
    worksheet = workbook.add_worksheet(name[:31])
    worksheet.freeze_panes(1, 0)
    return worksheet


def _style_format(formats: _Formats, style: str | None):
    return getattr(formats, style, None) if style else None


def _mapped_format(formats: _Formats, value: str, styles: dict[str, str]):
    return _style_format(formats, styles.get(value.strip().lower()))


def _write_summary_section(worksheet, rows: Sequence[SummaryRow], start_row: int = 0) -> int:
    worksheet.write_row(start_row, 0, ["Metric", "Value"])
    for offset, (label, value, fmt) in enumerate(rows, start=1):
        worksheet.write(start_row + offset, 0, label)
        worksheet.write(start_row + offset, 1, value, fmt)
    return start_row + len(rows)


def _write_table_section(worksheet, start_row: int, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> int:
    worksheet.write_row(start_row, 0, list(headers))
    for offset, row in enumerate(rows, start=1):
        worksheet.write_row(start_row + offset, 0, list(row))
    return start_row + max(len(rows), 1)


def _stringify_rows(data: Sequence[Sequence[object]]) -> List[List[str]]:
    return [[str(cell) for cell in row] for row in data]


def _social_rows(payload: CrawlPayload) -> List[List[str]]:
    rows: List[List[str]] = []
    for source, card in (("OpenGraph", payload.social.open_graph), ("Twitter", payload.social.twitter)):
        rows.append(
            [
                source,
                card.title or "-",
                card.description or "-",
                card.image or "-",
                card.card or "-",
                card.image_type or "-",
                _parse_size(card.image_bytes),
                f"{card.image_width}x{card.image_height}" if card.image_width and card.image_height else "-",
                "; ".join(card.issues) if card.issues else "",
            ]
        )
    return rows or [["OpenGraph", "No social data", "-", "-", "-", "-", "-", "-", ""]]


def _parse_int(text: object) -> int | None:
    try:
        return int(str(text))
    except (TypeError, ValueError):
        return None


def _parse_size(text: str) -> int:
    text = str(text).strip().lower()
    if not text:
        return -1
    parts = text.split()
    if len(parts) != 2:
        return -1
    try:
        number = float(parts[0].replace(",", "."))
    except ValueError:
        return -1
    unit = parts[1]
    multipliers = {
        "b": 1,
        "kb": 1_024,
        "mb": 1_048_576,
        "gb": 1_073_741_824,
        "kib": 1_024,
        "mib": 1_048_576,
        "gib": 1_073_741_824,
    }
    return int(number * multipliers.get(unit, 1))


def _schema_type_label(value: Any) -> str:
    candidate = ""
    if isinstance(value, str):
        candidate = value
    elif isinstance(value, list):
        for part in value:
            if isinstance(part, str) and part.strip():
                candidate = part
                break
    if not candidate:
        return ""
    text = candidate.strip()
    if not text:
        return ""
    for sep in ("#", "/"):
        if sep in text:
            text = text.rsplit(sep, 1)[-1]
    return text.strip()


def _enum_format(
    formats: _Formats,
    value: str,
    *,
    good: Sequence[str] = (),
    warn: Sequence[str] = (),
    bad: Sequence[str] = (),
):
    normalized = value.strip().lower()
    if normalized in {item.lower() for item in bad}:
        return formats.bad
    if normalized in {item.lower() for item in warn}:
        return formats.warn
    if normalized in {item.lower() for item in good}:
        return formats.good
    return None


def _performance_severity_format(formats: _Formats, severity: str):
    return _enum_format(
        formats,
        severity,
        good=("good", "ok"),
        warn=("warning",),
        bad=("critical",),
    )


def _ai_visibility_status_format(formats: _Formats, status: str):
    return _enum_format(
        formats,
        status,
        good=("good",),
        warn=("warning",),
        bad=("critical",),
    )


def _ai_visibility_summary_rows(formats: _Formats, payload: AiVisibilityPayload) -> List[SummaryRow]:
    checks = list(payload.checks)
    area_names = ", ".join(dict.fromkeys(check.area for check in checks if check.area)) or "-"
    summary = payload.summary
    verdict = summary.verdict or "-"
    return [
        ("Verdict", verdict, _mapped_format(formats, verdict, _AI_VISIBILITY_VERDICT_STYLES)),
        ("Good checks", str(summary.good_count), None),
        ("Warning checks", str(summary.warning_count), None),
        ("Critical checks", str(summary.critical_count), None),
        ("Total checks", str(len(checks)), None),
        ("Areas covered", area_names, None),
    ]


def _write_ai_visibility_checks(
    worksheet,
    workbook: xlsxwriter.Workbook,
    start_row: int,
    formats: _Formats,
    payload: AiVisibilityPayload,
) -> int:
    wrap = workbook.add_format({"text_wrap": True, "valign": "top"})
    rows = list(payload.checks)
    headers = ["Area", "Check", "Status", "Details", "Recommendation"]
    worksheet.write_row(start_row, 0, headers)
    if not rows:
        worksheet.write_row(
            start_row + 1,
            0,
            ["Info", "No AI visibility data yet", "-", "Run an analysis to populate this sheet.", "-"],
        )
        return start_row + 1
    for offset, check in enumerate(rows, start=1):
        status = check.status.title()
        worksheet.write(start_row + offset, 0, check.area or "-")
        worksheet.write(start_row + offset, 1, check.check or "-", wrap)
        worksheet.write(start_row + offset, 2, status, _ai_visibility_status_format(formats, check.status))
        worksheet.write(start_row + offset, 3, check.details or "-", wrap)
        worksheet.write(start_row + offset, 4, check.recommendation or "-", wrap)
    return start_row + len(rows)


def _write_ai_visibility_sheet(
    workbook: xlsxwriter.Workbook,
    formats: _Formats,
    payload: AiVisibilityPayload,
) -> None:
    worksheet = _sheet(workbook, "AI Visibility")
    summary_rows = _ai_visibility_summary_rows(formats, payload)
    summary_end = _write_summary_section(worksheet, summary_rows)
    checks_start = summary_end + 2
    end_row = _write_ai_visibility_checks(worksheet, workbook, checks_start, formats, payload)
    worksheet.autofilter(checks_start, 0, end_row, 4)
    worksheet.set_column(0, 0, 20)
    worksheet.set_column(1, 1, 34)
    worksheet.set_column(2, 2, 12)
    worksheet.set_column(3, 4, 68)


def _performance_summary_rows(formats: _Formats, performance: PerformanceMetrics) -> List[SummaryRow]:
    summary = performance.summary
    total_page_kb = (
        summary.total_page_bytes
        or (performance.transfer_size + sum(info.get("bytes", 0) for info in performance.resource_summary.values()))
    ) / 1024
    total_resource_kb = (
        summary.total_resource_bytes or sum(info.get("bytes", 0) for info in performance.resource_summary.values())
    ) / 1024
    verdict = summary.verdict or "Good"
    return [
        ("Verdict", verdict, _mapped_format(formats, verdict, _PERFORMANCE_VERDICT_STYLES)),
        ("HTTP status", "-" if performance.status == 0 else str(performance.status), None),
        ("TTFB (ms)", f"{performance.nav_ttfb_ms:.0f}", None),
        ("Total (ms)", f"{performance.nav_total_ms:.0f}", None),
        ("Transfer (KB)", f"{performance.transfer_size / 1024:.1f}", None),
        ("Resource bytes (KB)", f"{total_resource_kb:.1f}", None),
        ("Page weight (KB)", f"{total_page_kb:.1f}", None),
        ("Resource count", str(summary.total_resource_count), None),
        ("Third-party bytes (KB)", f"{summary.third_party_bytes / 1024:.1f}", None),
        ("Third-party resources", str(summary.third_party_count), None),
        ("Critical issues", str(summary.critical_issue_count), None),
        ("Warnings", str(summary.warning_issue_count), None),
    ]


def _performance_resource_rows(performance: PerformanceMetrics) -> List[List[str]]:
    resource_rows = [
        [row.resource_type.upper(), str(row.count), f"{row.bytes / 1024:.1f} KB"]
        for row in performance.resource_breakdown
    ]
    if not resource_rows:
        for resource, info in sorted(performance.resource_summary.items()):
            count = info.get("count", 0)
            bytes_val = info.get("bytes", 0)
            resource_rows.append([resource.upper(), str(count), f"{bytes_val / 1024:.1f} KB"])
    return resource_rows or [["-", "-", "-"]]


def _performance_script_rows(performance: PerformanceMetrics) -> List[List[str]]:
    return [
        ["Blocking", str(performance.scripts.blocking_count), f"{performance.scripts.blocking_bytes / 1024:.1f} KB"],
        ["Async/Deferred", str(performance.scripts.async_count), f"{performance.scripts.async_bytes / 1024:.1f} KB"],
    ]


def _write_performance_issues(worksheet, start_row: int, workbook: xlsxwriter.Workbook, formats: _Formats, performance: PerformanceMetrics) -> int:
    worksheet.write_row(start_row, 0, ["Severity", "Issue", "Evidence", "Recommendation"])
    wrap = workbook.add_format({"text_wrap": True})
    if performance.issues:
        for offset, item in enumerate(performance.issues, start=1):
            severity = item.severity.title()
            fmt = _performance_severity_format(formats, item.severity)
            worksheet.write(start_row + offset, 0, severity, fmt)
            worksheet.write(start_row + offset, 1, item.message, wrap)
            worksheet.write(start_row + offset, 2, item.evidence, wrap)
            worksheet.write(start_row + offset, 3, item.recommendation, wrap)
        return start_row + len(performance.issues)
    worksheet.write_row(start_row + 1, 0, ["OK", "No major performance issues detected", "-", "-"], formats.good)
    return start_row + 1


def _write_performance_opportunities(
    worksheet,
    start_row: int,
    workbook: xlsxwriter.Workbook,
    formats: _Formats,
    performance: PerformanceMetrics,
) -> int:
    worksheet.write_row(start_row, 0, ["Severity", "Opportunity"])
    wrap = workbook.add_format({"text_wrap": True})
    if performance.opportunity_details:
        for offset, item in enumerate(performance.opportunity_details, start=1):
            severity = item.severity.title()
            fmt = _performance_severity_format(formats, item.severity)
            worksheet.write(start_row + offset, 0, severity, fmt)
            worksheet.write(start_row + offset, 1, item.message, wrap)
        return start_row + len(performance.opportunity_details)
    if performance.opportunities:
        for offset, item in enumerate(performance.opportunities, start=1):
            worksheet.write(start_row + offset, 0, "Info")
            worksheet.write(start_row + offset, 1, item, wrap)
        return start_row + len(performance.opportunities)
    worksheet.write_row(start_row + 1, 0, ["-", "-"])
    return start_row + 1


def _performance_offender_rows(performance: PerformanceMetrics) -> List[List[str]]:
    rows = [
        [
            offender.resource_type.upper() or "-",
            offender.url or "-",
            "Blocking" if offender.blocking else "Async",
            f"{offender.bytes / 1024:.1f} KB",
        ]
        for offender in performance.top_offenders
    ]
    return rows or [["-", "-", "-", "-"]]


def _write_performance_sheet(workbook: xlsxwriter.Workbook, formats: _Formats, performance: PerformanceMetrics) -> None:
    worksheet = _sheet(workbook, "Performance")
    summary_rows = _performance_summary_rows(formats, performance)
    _write_summary_section(worksheet, summary_rows)

    resource_rows = _performance_resource_rows(performance)
    resource_start = len(summary_rows) + 2
    _write_table_section(worksheet, resource_start, ["Resource", "Count", "Bytes"], resource_rows)

    scripts_start = resource_start + len(resource_rows) + 2
    _write_table_section(worksheet, scripts_start, ["Scripts", "Count", "Bytes"], _performance_script_rows(performance))

    issues_start = scripts_start + 4
    _write_performance_issues(worksheet, issues_start, workbook, formats, performance)

    opp_start = issues_start + max(2, len(performance.issues) + 2)
    _write_performance_opportunities(worksheet, opp_start, workbook, formats, performance)

    offenders_start = opp_start + max(2, len(performance.opportunity_details) + 2, len(performance.opportunities) + 2)
    _write_table_section(worksheet, offenders_start, ["Type", "URL", "Script", "Bytes"], _performance_offender_rows(performance))

    worksheet.set_column(0, 0, 80)
    worksheet.set_column(1, 3, 80)


def _write_meta_sheet(workbook: xlsxwriter.Workbook, formats: _Formats, payload: CrawlPayload) -> None:
    raw_meta = [list(row) for row in payload.meta]
    names = [(row[0] or "").lower() for row in raw_meta]
    counts = Counter(name for name in names if name)
    duplicate_rows = {idx for idx, name in enumerate(names) if name and counts[name] > 1}
    empty_rows = {idx for idx, row in enumerate(raw_meta) if not str(row[1]).strip()}
    meta_rows = _stringify_rows(raw_meta)

    viewport_state: dict[int, str] = {idx: "good" for idx, name in enumerate(names) if name == "viewport"}
    if "viewport" not in names:
        viewport_state[len(meta_rows)] = "warn"
        meta_rows.append(["viewport", "", "0"])
        names.append("viewport")

    charset_state: dict[int, str] = {}
    charset_indices = [idx for idx, name in enumerate(names) if name == "charset"]
    if charset_indices:
        for idx in charset_indices:
            charset_state[idx] = "good" if idx <= 5 else "warn"
    else:
        charset_state[len(meta_rows)] = "warn"
        meta_rows.append(["charset", "", "0"])
        names.append("charset")

    def _meta_formatter(row_idx: int, col_idx: int, value: str):
        name = names[row_idx] if row_idx < len(names) else ""
        if row_idx in duplicate_rows and col_idx == 0:
            return formats.bad
        if row_idx in empty_rows and col_idx == 1:
            return formats.bad
        if name == "title" and col_idx == 2:
            length = _parse_int(meta_rows[row_idx][2]) or 0
            return _pixel_brush(formats, length * _PIXELS_PER_CHAR, _TITLE_MIN, _TITLE_MAX)
        if name == "description" and col_idx == 2:
            length = _parse_int(meta_rows[row_idx][2]) or 0
            return _pixel_brush(formats, length * _PIXELS_PER_CHAR, _DESCRIPTION_MIN, _DESCRIPTION_MAX)
        if name == "robots" and col_idx == 1:
            content = meta_rows[row_idx][1].lower()
            if "noindex" in content:
                return formats.bad
            if "nofollow" in content:
                return formats.warn
            return formats.good
        if name == "viewport" and col_idx == 0:
            return formats.warn if viewport_state.get(row_idx) == "warn" else formats.good
        if name == "charset" and col_idx == 0:
            return formats.warn if charset_state.get(row_idx) == "warn" else formats.good
        return None

    _write_sheet(workbook, "Meta", ["Name/Property", "Content", "Length"], meta_rows, _meta_formatter)


def _write_headers_sheet(workbook: xlsxwriter.Workbook, formats: _Formats, payload: CrawlPayload) -> None:
    headers_rows = _stringify_rows(payload.headers)
    h1_count = sum(1 for row in payload.headers if row and str(row[0]).strip().lower() == "h1")
    empty_header_rows = {idx for idx, row in enumerate(payload.headers) if len(row) > 1 and not str(row[1]).strip()}

    jump_rows = set()
    prev_level = None
    for idx, row in enumerate(payload.headers):
        tag = str(row[0]).strip().lower() if row else ""
        if not (tag.startswith("h") and len(tag) > 1 and tag[1:].isdigit()):
            continue
        level = int(tag[1:])
        if prev_level is not None and abs(level - prev_level) > 1:
            jump_rows.add(idx)
        prev_level = level

    title_reference = next(
        (row[1] for row in payload.meta if row and (row[0] or "").lower() == "title"),
        "",
    ).strip().lower()
    title_warn_rows = set()
    if title_reference:
        for idx, row in enumerate(payload.headers):
            tag = str(row[0]).strip().lower() if row else ""
            if tag != "h1":
                continue
            text = str(row[1]).strip().lower() if len(row) > 1 else ""
            if text and SequenceMatcher(None, text, title_reference).ratio() >= 0.9:
                title_warn_rows.add(idx)

    def _headers_formatter(row_idx: int, col_idx: int, value: str):
        if row_idx >= len(payload.headers) or col_idx not in (0, 1):
            return None
        if row_idx in empty_header_rows:
            return formats.bad
        if row_idx in jump_rows and col_idx == 0:
            return formats.warn
        if row_idx in title_warn_rows and col_idx == 1:
            return formats.warn
        tag = str(payload.headers[row_idx][0]).strip().lower()
        if tag == "h1":
            return formats.good if h1_count == 1 else formats.warn
        return None

    _write_sheet(workbook, "Headers", ["Tag", "Text"], headers_rows, _headers_formatter)


def _write_images_sheet(workbook: xlsxwriter.Workbook, formats: _Formats, payload: CrawlPayload) -> None:
    images_rows = _stringify_rows(normalize_image_rows(payload.images))

    def _images_formatter(row_idx: int, col_idx: int, value: str):
        if row_idx >= len(images_rows):
            return None
        if col_idx == ALT_COL:
            return formats.good if str(images_rows[row_idx][col_idx]).strip() else formats.warn
        if col_idx == SIZE_COL:
            size = _parse_size(images_rows[row_idx][col_idx])
            if size < 0:
                return None
            if size > 500 * 1024:
                return formats.bad
            if size > 100 * 1024:
                return formats.warn
            return formats.good
        if col_idx in (DECLARED_WIDTH_COL, DECLARED_HEIGHT_COL) and not images_rows[row_idx][col_idx].strip():
            return formats.warn
        if col_idx == CACHE_COL and not images_rows[row_idx][col_idx].strip():
            return formats.warn
        if col_idx == FORMAT_HINT_COL and images_rows[row_idx][col_idx].strip():
            return formats.good if images_rows[row_idx][col_idx].strip() == "Next-gen format" else formats.warn
        if col_idx == FETCH_PRIORITY_COL:
            return formats.warn if not images_rows[row_idx][col_idx].strip().lower() else None
        if col_idx == DIAGNOSTIC_COL:
            return formats.good if images_rows[row_idx][col_idx].strip() == "OK" else formats.warn
        return None

    _write_sheet(workbook, "Images", IMAGE_HEADERS, images_rows, _images_formatter)


def _write_social_sheet(workbook: xlsxwriter.Workbook, formats: _Formats, payload: CrawlPayload) -> None:
    social_rows = _social_rows(payload)

    def _social_formatter(row_idx: int, col_idx: int, value: str):
        return formats.warn if col_idx == 8 and value else None

    _write_sheet(
        workbook,
        "Social",
        ["Source", "Title", "Description", "Image", "Card", "Type", "Size (B)", "Dims", "Issues"],
        social_rows,
        _social_formatter,
    )


def _write_links_sheet(workbook: xlsxwriter.Workbook, formats: _Formats, payload: CrawlPayload) -> None:
    links_rows = _stringify_rows(payload.links)

    def _links_formatter(row_idx: int, col_idx: int, value: str):
        if row_idx >= len(payload.links):
            return None
        if col_idx == 4:
            code = _parse_int(payload.links[row_idx][4])
            if code is None:
                return formats.bad
            if 200 <= code < 300:
                return formats.good
            if 300 <= code < 400:
                return formats.warn
            return formats.bad
        if col_idx == 5:
            note = (payload.links[row_idx][5] or "").strip().lower()
            if note == "ok":
                return formats.good
            if note == "redirect":
                return formats.warn
            if note in {"client error", "server error", "fetch error"}:
                return formats.bad
        return None

    _write_sheet(
        workbook,
        "Links",
        ["URL", "Anchor", "Type", "Rel", "Status", "Status note", "Section", "Heading", "TLD"],
        links_rows,
        _links_formatter,
    )


def _write_redirect_sheet(workbook: xlsxwriter.Workbook, formats: _Formats, payload: CrawlPayload) -> None:
    redirect_rows = [
        ["Redirect chain", " â†’ ".join(payload.redirect.chain)],
        ["Hop count", str(payload.redirect.hops)],
        ["Final status", payload.redirect.final_status],
        ["Loop detected", "Yes" if payload.redirect.loop else "No"],
    ]

    def _redirect_formatter(row_idx: int, col_idx: int, value: str):
        if col_idx != 1 or row_idx >= len(redirect_rows):
            return None
        key = redirect_rows[row_idx][0].lower()
        val = redirect_rows[row_idx][1]
        if key == "redirect chain":
            return formats.warn if "â†’" in val else formats.good
        if key == "hop count":
            hops = _parse_int(val)
            if hops is None:
                return formats.bad
            if hops == 0:
                return formats.good
            if hops <= 2:
                return formats.warn
            return formats.bad
        if key == "final status":
            code = _parse_int(val)
            if code is None:
                return formats.warn if val else formats.bad
            if 200 <= code < 300:
                return formats.good
            if 300 <= code < 400:
                return formats.warn
            return formats.bad
        if key == "loop detected":
            return formats.bad if val.lower().startswith("y") else formats.good
        return None

    _write_sheet(workbook, "Redirect", ["Check", "Value"], redirect_rows, _redirect_formatter)


def _write_canonical_sheet(workbook: xlsxwriter.Workbook, formats: _Formats, payload: CrawlPayload) -> None:
    canonical_rows = [
        ["Canonical URL", payload.canonical.target or "-"],
        ["Self-referencing", "Yes" if payload.canonical.is_self else "No"],
        ["Multiple canonicals", "Yes" if payload.canonical.multiple else "No"],
        ["Canonical status", payload.canonical.status or "-"],
    ]

    def _canonical_formatter(row_idx: int, col_idx: int, value: str):
        if col_idx != 1 or row_idx >= len(canonical_rows):
            return None
        key = canonical_rows[row_idx][0].lower()
        val = canonical_rows[row_idx][1]
        if key == "canonical url":
            return formats.good if val and val != "-" else formats.bad
        if key == "self-referencing":
            return formats.good if val.lower().startswith("y") else formats.bad
        if key == "multiple canonicals":
            return formats.bad if val.lower().startswith("y") else formats.good
        if key == "canonical status":
            if not val:
                return formats.bad
            code = _parse_int(val)
            if code is None:
                return formats.warn
            return formats.good if 200 <= code < 400 else formats.warn
        return None

    _write_sheet(workbook, "Canonical", ["Check", "Value"], canonical_rows, _canonical_formatter)


def _style_value(formats: _Formats, style: str | None):
    if style == "good":
        return formats.good
    if style == "warn":
        return formats.warn
    if style == "bad":
        return formats.bad
    return None


def _map_value_style(formats: _Formats, value: str, style_map: dict[str, str | None]):
    return _style_value(formats, style_map.get(value.lower()))


def _yes_no_style(formats: _Formats, value: str, yes_style: str, no_style: str):
    return _style_value(formats, yes_style if value.lower().startswith("y") else no_style)


def _http_status_style(formats: _Formats, value: str, missing_style: str = "bad"):
    code = _parse_int(value)
    if code is None:
        return _style_value(formats, missing_style)
    if 200 <= code < 300:
        return formats.good
    if 300 <= code < 400:
        return formats.warn
    return formats.bad


def _redirect_hops_style(formats: _Formats, value: str):
    hops = _parse_int(value)
    if hops is None:
        return formats.bad
    return formats.good if hops == 0 else formats.warn


def _meta_robots_style(formats: _Formats, value: str):
    lower_val = value.lower()
    if lower_val == "-":
        return formats.warn
    if "noindex" in lower_val or lower_val == "none":
        return formats.bad
    if "nofollow" in lower_val:
        return formats.warn
    return formats.good


def _canonical_status_style(formats: _Formats, value: str):
    code = _parse_int(value)
    if code is None:
        return formats.warn if value == "-" else formats.bad
    return formats.good if 200 <= code < 400 else formats.bad


def _indexability_verdict_style(formats: _Formats, value: str):
    style_map = {
        "indexable": "good",
        "redirected": "warn",
        "canonicalized elsewhere": "warn",
        "indexable with warnings": "warn",
        "not indexable": "bad",
    }
    return _map_value_style(formats, value, style_map) or formats.bad


def _indexability_value_format(formats: _Formats, key: str, value: str):
    dispatch = {
        "crawl allowed by robots.txt": lambda: _yes_no_style(formats, value, "good", "bad"),
        "index directive": lambda: _map_value_style(formats, value, {"index": "good"}) or formats.bad,
        "follow directive": lambda: _map_value_style(formats, value, {"follow": "good"}) or formats.warn,
        "canonical url": lambda: formats.good if value and value != "-" else formats.warn,
        "canonical self-reference": lambda: _yes_no_style(formats, value, "good", "warn"),
        "multiple canonicals": lambda: _yes_no_style(formats, value, "bad", "good"),
        "final status": lambda: _http_status_style(formats, value),
        "redirect hops": lambda: _redirect_hops_style(formats, value),
        "meta / x-robots-tag": lambda: _meta_robots_style(formats, value),
        "canonical status": lambda: _canonical_status_style(formats, value),
        "overall verdict": lambda: _indexability_verdict_style(formats, value),
    }
    handler = dispatch.get(key)
    return handler() if handler else None


def _write_indexability_sheet(workbook: xlsxwriter.Workbook, formats: _Formats, payload: CrawlPayload) -> None:
    rows = build_indexability_rows(
        payload.redirect.to_dict(),
        payload.canonical.to_dict(),
        payload.meta_robots,
        payload.robots,
    )

    def _formatter(row_idx: int, col_idx: int, value: str):
        if col_idx != 1 or row_idx >= len(rows):
            return None
        return _indexability_value_format(formats, rows[row_idx][0].lower(), str(rows[row_idx][1] or ""))

    _write_sheet(workbook, "Indexability", ["Check", "Value"], rows, _formatter)


def _robots_value_format(formats: _Formats, row_idx: int, col_idx: int, row: List[str]):
    key = row[0].lower()
    value = row[1].lower() if len(row) > 1 else ""
    if row_idx == 0 and col_idx == 1:
        if "noindex" in value:
            return formats.bad
        if "nofollow" in value:
            return formats.warn
        return formats.good if value else None
    if key.startswith("user-agent"):
        return None
    if key == "allow" and col_idx == 1:
        return formats.good
    if key == "disallow" and col_idx == 1:
        return formats.bad if value.strip() not in ("", "/") else formats.warn
    if key.startswith("meta") and col_idx == 1:
        if "noindex" in value:
            return formats.bad
        if "nofollow" in value:
            return formats.warn
        return formats.good
    if key.startswith("x-robots") and col_idx == 1:
        if "noindex" in value:
            return formats.bad
        if "nofollow" in value:
            return formats.warn
        return formats.good
    return None


def _write_robots_sheet(workbook: xlsxwriter.Workbook, formats: _Formats, payload: CrawlPayload) -> None:
    rows: List[List[str]] = [["Meta robots", payload.meta_robots or "-"]]
    for agent, directives in payload.robots.items():
        rows.append([f"User-agent: {agent}", ""])
        for verb, value in directives:
            rows.append([verb, value])

    def _formatter(row_idx: int, col_idx: int, value: str):
        if row_idx >= len(rows):
            return None
        return _robots_value_format(formats, row_idx, col_idx, rows[row_idx])

    _write_sheet(workbook, "Robots", ["Directive", "Value"], rows, _formatter)


def _write_hreflang_sheet(workbook: xlsxwriter.Workbook, formats: _Formats, payload: CrawlPayload) -> None:
    rows = _stringify_rows(payload.hreflang)

    def _formatter(row_idx: int, col_idx: int, value: str):
        if row_idx >= len(payload.hreflang):
            return None
        if col_idx == 2:
            code = _parse_int(payload.hreflang[row_idx][2])
            if code is None:
                return formats.bad
            if 200 <= code < 300:
                return formats.good
            if 300 <= code < 400:
                return formats.warn
            return formats.bad
        if col_idx == 3:
            return formats.good if str(payload.hreflang[row_idx][3]).strip().lower().startswith("y") else formats.bad
        if col_idx == 4:
            return formats.good if str(payload.hreflang[row_idx][4]).strip().lower().startswith("y") else formats.warn
        return None

    _write_sheet(workbook, "Hreflang", ["Lang", "Target URL", "Status", "Lang-OK?", "Return?"], rows, _formatter)


def _write_ai_crawl_sheet(workbook: xlsxwriter.Workbook, formats: _Formats, payload: CrawlPayload) -> None:
    rows = _stringify_rows(payload.ai_crawl)

    def _formatter(row_idx: int, col_idx: int, value: str):
        if row_idx >= len(payload.ai_crawl):
            return None
        if col_idx == 5:
            verdict = str(payload.ai_crawl[row_idx][5]).strip().lower()
            if verdict == "allowed":
                return formats.good
            if verdict == "limited":
                return formats.warn
            return formats.bad
        if col_idx in {3, 4} and str(payload.ai_crawl[row_idx][col_idx]).strip() != "-":
            return formats.warn
        return None

    _write_sheet(
        workbook,
        "AI crawl",
        ["Agent", "Token", "Robots.txt OK", "Nonstandard directive", "Google controls", "Verdict", "Notes"],
        rows,
        _formatter,
    )


def _write_structured_sheets(workbook: xlsxwriter.Workbook, formats: _Formats, payload: CrawlPayload) -> None:
    structured = payload.schema
    blocks = list(structured.blocks)
    if not blocks and structured.fallback_raw:
        blocks = [{"@raw": raw, "_extracted_via": "json-ld-raw"} for raw in structured.fallback_raw]

    syntax_labels = {
        "json-ld": "JSON-LD",
        "json-ld-raw": "JSON-LD raw",
        "microdata": "Microdata",
        "microformat": "Microformat",
        "opengraph": "OpenGraph",
        "rdfa": "RDFa",
    }
    summary = structured.summary
    syntax_text = ", ".join(
        f"{syntax_labels.get(name, name)} {count}"
        for name, count in sorted(summary.by_syntax.items())
        if count
    )
    type_text = ", ".join(
        f"{schema_type} {count}" for schema_type, count in sorted(summary.by_type.items()) if count
    )
    summary_rows = [
        ["Total items", str(summary.total or len(blocks))],
        ["Syntax", syntax_text or "-"],
        ["Types", type_text or "-"],
    ]
    if summary.errors:
        summary_rows.append(["Errors", "\n".join(summary.errors)])
    _write_sheet(workbook, "Structured summary", ["Metric", "Value"], summary_rows)

    eligibility_rows = [
        [
            item.schema_type,
            "Yes" if item.detected else "No",
            item.eligibility,
            ", ".join(item.missing_fields) or "-",
            "; ".join(item.warnings) or "-",
        ]
        for item in structured.eligibility
    ] or [["-", "No", "Not detected", "-", "-"]]

    def _eligibility_formatter(row_idx: int, col_idx: int, value: str):
        if col_idx != 2 or row_idx >= len(eligibility_rows):
            return None
        status = str(eligibility_rows[row_idx][2]).strip().lower()
        if status == "eligible":
            return formats.good
        if status == "incomplete":
            return formats.warn
        return None

    _write_sheet(
        workbook,
        "Structured eligibility",
        ["Type", "Detected", "Eligibility", "Missing fields", "Warnings"],
        eligibility_rows,
        _eligibility_formatter,
    )

    detail_rows: List[List[str]] = []
    for idx, item in enumerate(blocks, start=1):
        if isinstance(item, dict):
            raw_snapshot = json.dumps(
                {key: value for key, value in item.items() if key != "_schema_errors"},
                ensure_ascii=False,
            )
            error_text = "; ".join(str(err).strip() for err in item.get("_schema_errors", []) if str(err).strip())
            detail_rows.append([str(idx), str(item.get("_extracted_via", "")), _schema_type_label(item.get("@type")), error_text or "-", raw_snapshot])
            continue
        if isinstance(item, list):
            detail_rows.append([str(idx), "list", "", "-", json.dumps(item, ensure_ascii=False)])
            continue
        detail_rows.append([str(idx), "", "", "-", str(item)])
    _write_sheet(workbook, "Structured data", ["#", "Source", "Type", "Errors", "Raw"], detail_rows or [["-", "-", "-", "-", "-"]])


def _h1_count_style(formats: _Formats, value: str):
    return _map_value_style(formats, value, {"1": "good", "0": "bad"}) or formats.warn


def _title_alignment_style(formats: _Formats, value: str):
    style_map = {
        "aligned": "good",
        "exact match": "good",
        "different": "warn",
        "missing": "bad",
    }
    return _map_value_style(formats, value, style_map)


def _thin_content_style(formats: _Formats, value: str):
    return _map_value_style(formats, value, {"low": "good", "medium": "warn", "high": "bad"})


def _heading_structure_style(formats: _Formats, value: str):
    style_map = {
        "good": "good",
        "multiple h1s": "warn",
        "no subheadings": "warn",
        "missing h1": "bad",
    }
    return _map_value_style(formats, value, style_map)


def _content_verdict_style(formats: _Formats, value: str):
    return _map_value_style(formats, value, {"strong": "good", "needs work": "warn", "weak": "bad"})


def _content_quality_value_format(formats: _Formats, key: str, value: str):
    dispatch = {
        "page language": lambda: _map_value_style(formats, value, {"not declared": "warn"}),
        "title present": lambda: _yes_no_style(formats, value, "good", "bad"),
        "meta description present": lambda: _yes_no_style(formats, value, "good", "warn"),
        "intro paragraph": lambda: _map_value_style(formats, value, {"present": "good"}) or formats.warn,
        "h1 count": lambda: _h1_count_style(formats, value),
        "h2-h6 count": lambda: _map_value_style(formats, value, {"0": "warn"}),
        "title / h1 alignment": lambda: _title_alignment_style(formats, value),
        "thin-content risk": lambda: _thin_content_style(formats, value),
        "heading structure": lambda: _heading_structure_style(formats, value),
        "overall verdict": lambda: _content_verdict_style(formats, value),
    }
    handler = dispatch.get(key)
    return handler() if handler else None


def _write_content_quality_sheet(workbook: xlsxwriter.Workbook, formats: _Formats, payload: CrawlPayload) -> None:
    rows = build_content_quality_rows(payload.content_quality)

    def _formatter(row_idx: int, col_idx: int, value: str):
        if col_idx != 1 or row_idx >= len(rows):
            return None
        return _content_quality_value_format(formats, rows[row_idx][0].lower(), str(rows[row_idx][1] or ""))

    _write_sheet(workbook, "Content quality", ["Check", "Value"], rows, _formatter)


def _write_serp_sheets(workbook: xlsxwriter.Workbook, formats: _Formats, payload: CrawlPayload) -> None:
    serp = payload.serp
    serp_rows = [
        ["Title", serp.title],
        ["Description", serp.description],
        ["URL", serp.url],
        ["Site name", serp.site_name],
        ["Breadcrumb", serp.breadcrumb],
        ["Favicon", serp.favicon],
    ]
    _write_sheet(workbook, "SERP Preview", ["Field", "Value"], serp_rows)

    audit_rows = [[key.replace("_", " ").title(), value] for key, value in payload.serp_audit.to_dict().items()]

    def _audit_formatter(row_idx: int, col_idx: int, value: str):
        if col_idx != 1 or row_idx >= len(audit_rows):
            return None
        key = audit_rows[row_idx][0].lower()
        val = str(audit_rows[row_idx][1]).strip().lower()
        if key in {"> 60 chars", "< 30 chars", "> 561 px", "< 200 px", "equals h1"}:
            return formats.warn if val in {"yes", "true", "1"} else formats.good
        if key == "missing":
            return formats.bad if val in {"yes", "true", "1"} else formats.good
        return None

    _write_sheet(workbook, "SERP Audit", ["Metric", "Value"], audit_rows, _audit_formatter)


def _write_keywords_sheet(workbook: xlsxwriter.Workbook, payload: CrawlPayload) -> None:
    keyword_rows = [
        [
            entry.term,
            f"{entry.length}-gram",
            str(entry.frequency),
            f"{entry.density:.2f}",
            "Yes" if entry.in_title else "No",
            "Yes" if entry.in_description else "No",
            str(entry.heading_count),
            "-" if entry.first_position is None else str(entry.first_position + 1),
        ]
        for entry in payload.keywords
    ]
    _write_sheet(
        workbook,
        "Keywords",
        ["Keyword", "Type", "Frequency", "Density %", "In Title", "Meta Description", "Headings", "1st Occurrence"],
        keyword_rows or [["-", "-", "-", "-", "-", "-", "-", "-"]],
    )


def export_page_analysis(payload: CrawlPayload, file_path: Path) -> None:
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with xlsxwriter.Workbook(str(file_path)) as workbook:
        formats = _Formats(workbook)
        writers = (
            lambda: _write_performance_sheet(workbook, formats, payload.performance),
            lambda: _write_ai_visibility_sheet(workbook, formats, payload.ai_visibility),
            lambda: _write_meta_sheet(workbook, formats, payload),
            lambda: _write_headers_sheet(workbook, formats, payload),
            lambda: _write_images_sheet(workbook, formats, payload),
            lambda: _write_social_sheet(workbook, formats, payload),
            lambda: _write_links_sheet(workbook, formats, payload),
            lambda: _write_redirect_sheet(workbook, formats, payload),
            lambda: _write_canonical_sheet(workbook, formats, payload),
            lambda: _write_indexability_sheet(workbook, formats, payload),
            lambda: _write_robots_sheet(workbook, formats, payload),
            lambda: _write_hreflang_sheet(workbook, formats, payload),
            lambda: _write_ai_crawl_sheet(workbook, formats, payload),
            lambda: _write_structured_sheets(workbook, formats, payload),
            lambda: _write_content_quality_sheet(workbook, formats, payload),
            lambda: _write_serp_sheets(workbook, formats, payload),
            lambda: _write_keywords_sheet(workbook, payload),
        )
        for writer in writers:
            writer()
