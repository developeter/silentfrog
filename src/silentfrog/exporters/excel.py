from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, List, Sequence

import xlsxwriter

from ..crawl_types import CrawlPayload

Formatter = Callable[[int, int, str], xlsxwriter.format.Format | None]


class _Formats:
    def __init__(self, workbook: xlsxwriter.Workbook) -> None:
        self.good = workbook.add_format({"bg_color": "#D1E7DD"})
        self.warn = workbook.add_format({"bg_color": "#FFF3CD"})
        self.bad = workbook.add_format({"bg_color": "#F8D7DA"})


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
        for col_idx, cell in enumerate(row):
            fmt = formatter(row_idx - 1, col_idx, cell) if formatter else None
            worksheet.write(row_idx, col_idx, cell, fmt)

    if has_rows and headers:
        worksheet.autofilter(0, 0, row_idx, len(headers) - 1)
    if headers:
        worksheet.freeze_panes(1, 0)


def _stringify_rows(data: Sequence[Sequence[object]]) -> List[List[str]]:
    return [[str(cell) for cell in row] for row in data]


def _parse_int(text: object) -> int | None:
    try:
        return int(str(text))
    except (TypeError, ValueError):
        return None


def _parse_size(text: str) -> int:
    text = text.strip().lower()
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


def export_page_analysis(payload: CrawlPayload, file_path: Path) -> None:
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with xlsxwriter.Workbook(str(file_path)) as workbook:
        formats = _Formats(workbook)

        meta_rows = _stringify_rows(payload.meta)

        def _meta_formatter(row_idx: int, col_idx: int, value: str):
            if row_idx >= len(payload.meta) or col_idx != 2:
                return None
            name = str(payload.meta[row_idx][0]).lower()
            if name == "description":
                length = _parse_int(payload.meta[row_idx][2])
                if length is None:
                    return formats.bad
                return formats.good if 120 <= length <= 160 else formats.bad
            if name == "robots":
                content = str(payload.meta[row_idx][1] or "").lower()
                if "noindex" in content:
                    return formats.bad
                if "nofollow" in content:
                    return formats.warn
                return formats.good
            return None

        _write_sheet(
            workbook,
            "Meta",
            ["Name/Property", "Content", "Length"],
            meta_rows,
            _meta_formatter,
        )

        headers_rows = _stringify_rows(payload.headers)
        h1_count = sum(
            1 for row in payload.headers if row and str(row[0]).strip().lower() == "h1"
        )

        def _headers_formatter(row_idx: int, col_idx: int, value: str):
            if row_idx >= len(payload.headers) or col_idx not in (0, 1):
                return None
            tag = str(payload.headers[row_idx][0]).strip().lower()
            if tag == "h1":
                return formats.good if h1_count == 1 else formats.warn
            return None

        _write_sheet(
            workbook,
            "Headers",
            ["Tag", "Text"],
            headers_rows,
            _headers_formatter,
        )

        images_rows = _stringify_rows(payload.images)

        def _images_formatter(row_idx: int, col_idx: int, value: str):
            if row_idx >= len(payload.images):
                return None
            if col_idx in (1, 2):
                return (
                    formats.good
                    if str(payload.images[row_idx][col_idx]).strip()
                    else formats.warn
                )
            if col_idx == 5:
                size = _parse_size(str(payload.images[row_idx][col_idx]))
                if size < 0:
                    return None
                if size > 500 * 1024:
                    return formats.bad
                if size > 100 * 1024:
                    return formats.warn
                return formats.good
            return None

        _write_sheet(
            workbook,
            "Images",
            ["Src", "Alt", "Title", "W", "H", "Size"],
            images_rows,
            _images_formatter,
        )

        links_rows = _stringify_rows(payload.links)

        def _links_formatter(row_idx: int, col_idx: int, value: str):
            if col_idx != 3 or row_idx >= len(payload.links):
                return None
            code = _parse_int(payload.links[row_idx][3])
            if code is None:
                return formats.bad
            if 200 <= code < 300:
                return formats.good
            if 300 <= code < 400:
                return formats.warn
            return formats.bad

        _write_sheet(
            workbook,
            "Links",
            ["URL", "Anchor", "Follow ?", "Status"],
            links_rows,
            _links_formatter,
        )

        redirect_rows = [
            ["Redirect chain", " → ".join(payload.redirect.chain)],
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
                return formats.warn if "→" in val else formats.good
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

        _write_sheet(
            workbook,
            "Redirect",
            ["Check", "Value"],
            redirect_rows,
            _redirect_formatter,
        )

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
                if 200 <= code < 400:
                    return formats.good
                return formats.warn
            return None

        _write_sheet(
            workbook,
            "Canonical",
            ["Check", "Value"],
            canonical_rows,
            _canonical_formatter,
        )

        robots_rows: List[List[str]] = [
            ["Meta robots", payload.meta_robots or "-"],
        ]
        for agent, directives in payload.robots.items():
            robots_rows.append([f"User-agent: {agent}", ""])
            for verb, value in directives:
                robots_rows.append([verb, value])

        def _robots_formatter(row_idx: int, col_idx: int, value: str):
            if row_idx >= len(robots_rows):
                return None
            key = robots_rows[row_idx][0].lower()
            val = robots_rows[row_idx][1].lower() if len(robots_rows[row_idx]) > 1 else ""
            if row_idx == 0 and col_idx == 1:
                if "noindex" in val:
                    return formats.bad
                if "nofollow" in val:
                    return formats.warn
                return formats.good if val else None
            if key.startswith("user-agent"):
                return None
            if key == "allow" and col_idx == 1:
                return formats.good
            if key == "disallow" and col_idx == 1:
                return formats.bad if val.strip() not in ("", "/") else formats.warn
            if key.startswith("meta") and col_idx == 1:
                if "noindex" in val:
                    return formats.bad
                if "nofollow" in val:
                    return formats.warn
                return formats.good
            if key.startswith("x-robots") and col_idx == 1:
                if "noindex" in val:
                    return formats.bad
                if "nofollow" in val:
                    return formats.warn
                return formats.good
            return None

        _write_sheet(
            workbook,
            "Robots",
            ["Directive", "Value"],
            robots_rows,
            _robots_formatter,
        )

        hreflang_rows = _stringify_rows(payload.hreflang)

        def _hreflang_formatter(row_idx: int, col_idx: int, value: str):
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
                return (
                    formats.good
                    if str(payload.hreflang[row_idx][3]).strip().lower().startswith("y")
                    else formats.bad
                )
            if col_idx == 4:
                return (
                    formats.good
                    if str(payload.hreflang[row_idx][4]).strip().lower().startswith("y")
                    else formats.warn
                )
            return None

        _write_sheet(
            workbook,
            "Hreflang",
            ["Lang", "Target URL", "Status", "Lang-OK?", "Return?"],
            hreflang_rows,
            _hreflang_formatter,
        )

        ai_rows = _stringify_rows(payload.ai_crawl)

        def _ai_formatter(row_idx: int, col_idx: int, value: str):
            if col_idx != 3 or row_idx >= len(payload.ai_crawl):
                return None
            verdict = str(payload.ai_crawl[row_idx][3]).strip().lower()
            return formats.good if verdict == "allowed" else formats.bad

        _write_sheet(
            workbook,
            "AI crawl",
            ["Agent", "Robots.txt OK", "Meta noai?", "Verdict"],
            ai_rows,
            _ai_formatter,
        )

        schema_rows: List[List[str]] = []
        for idx, item in enumerate(payload.schema, start=1):
            if isinstance(item, dict):
                schema_rows.append(
                    [
                        str(idx),
                        item.get("_extracted_via", ""),
                        json.dumps(item, ensure_ascii=False),
                    ]
                )
            elif isinstance(item, list):
                schema_rows.append(
                    [
                        str(idx),
                        "list",
                        json.dumps(item, ensure_ascii=False),
                    ]
                )
            else:
                schema_rows.append(
                    [
                        str(idx),
                        "",
                        str(item),
                    ]
                )

        _write_sheet(
            workbook,
            "Schema",
            ["#", "Source", "Raw"],
            schema_rows or [["-", "-", "-"]],
        )

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

        audit_dict = payload.serp_audit.to_dict()
        audit_rows = [
            [key.replace("_", " ").title(), value] for key, value in audit_dict.items()
        ]

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

        _write_sheet(
            workbook,
            "SERP Audit",
            ["Metric", "Value"],
            audit_rows,
            _audit_formatter,
        )

        _write_sheet(
            workbook,
            "Keywords",
            ["Keyword / Ngram", "Frequency"],
            _stringify_rows(payload.keywords),
        )
