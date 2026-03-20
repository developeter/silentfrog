from __future__ import annotations

import json
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, List, Sequence

import xlsxwriter

from ..crawl_types import CrawlPayload, PerformanceMetrics
from ..content_quality import build_content_quality_rows
from ..indexability import build_indexability_rows

Formatter = Callable[[int, int, str], xlsxwriter.format.Format | None]

_PIXELS_PER_CHAR = 7.2
_TITLE_MIN, _TITLE_MAX = 200, 600
_DESCRIPTION_MIN, _DESCRIPTION_MAX = 400, 920
_WARN_MARGIN = 40


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


def _write_performance_sheet(workbook: xlsxwriter.Workbook, performance: PerformanceMetrics) -> None:
    worksheet = workbook.add_worksheet("Performance")
    worksheet.freeze_panes(1, 0)

    summary_rows = [
        ("HTTP status", "-" if performance.status == 0 else str(performance.status)),
        ("TTFB (ms)", f"{performance.nav_ttfb_ms:.0f}"),
        ("Total (ms)", f"{performance.nav_total_ms:.0f}"),
        ("Transfer (KB)", f"{performance.transfer_size / 1024:.1f}"),
        (
            "Page weight (KB)",
            f"{(performance.transfer_size + sum(info.get('bytes', 0) for info in performance.resource_summary.values())) / 1024:.1f}",
        ),
    ]
    worksheet.write_row(0, 0, ["Metric", "Value"])
    for idx, (label, value) in enumerate(summary_rows, start=1):
        worksheet.write(idx, 0, label)
        worksheet.write(idx, 1, value)

    resource_rows = []
    for resource, info in sorted(performance.resource_summary.items()):
        count = info.get("count", 0)
        bytes_val = info.get("bytes", 0)
        resource_rows.append(
            [
                resource.upper(),
                str(count),
                f"{bytes_val / 1024:.1f} KB",
            ]
        )
    if not resource_rows:
        resource_rows = [["-", "-", "-"]]

    resource_start = len(summary_rows) + 2
    worksheet.write_row(resource_start, 0, ["Resource", "Count", "Bytes"])
    for offset, row in enumerate(resource_rows, start=1):
        worksheet.write_row(resource_start + offset, 0, row)

    scripts_start = resource_start + len(resource_rows) + 2
    worksheet.write_row(scripts_start, 0, ["Scripts", "Count", "Bytes"])
    worksheet.write_row(
        scripts_start + 1,
        0,
        [
            "Blocking",
            str(performance.scripts.blocking_count),
            f"{performance.scripts.blocking_bytes / 1024:.1f} KB",
        ],
    )
    worksheet.write_row(
        scripts_start + 2,
        0,
        [
            "Async/Deferred",
            str(performance.scripts.async_count),
            f"{performance.scripts.async_bytes / 1024:.1f} KB",
        ],
    )

    opp_start = scripts_start + 4
    worksheet.write_row(opp_start, 0, ["Severity", "Opportunity"])
    wrap = workbook.add_format({"text_wrap": True})
    if performance.opportunity_details:
        for offset, item in enumerate(performance.opportunity_details, start=1):
            severity = item.severity.title()
            worksheet.write(opp_start + offset, 0, severity)
            worksheet.write(opp_start + offset, 1, item.message, wrap)
    elif performance.opportunities:
        for offset, item in enumerate(performance.opportunities, start=1):
            worksheet.write(opp_start + offset, 0, "Info")
            worksheet.write(opp_start + offset, 1, item, wrap)
    else:
        worksheet.write_row(opp_start + 1, 0, ["-", "-"])

    offenders_start = opp_start + max(2, len(performance.opportunity_details) + 2, len(performance.opportunities) + 2)
    worksheet.write_row(offenders_start, 0, ["Type", "URL", "Script", "Bytes"])
    offender_rows = [
        [
            offender.resource_type.upper() or "-",
            offender.url or "-",
            "Blocking" if offender.blocking else "Async",
            f"{offender.bytes / 1024:.1f} KB",
        ]
        for offender in performance.top_offenders
    ]
    if not offender_rows:
        offender_rows = [["-", "-", "-", "-"]]
    for offset, row in enumerate(offender_rows, start=1):
        worksheet.write_row(offenders_start + offset, 0, row)

    worksheet.set_column(0, 0, 80)
    worksheet.set_column(1, 1, 18)
    worksheet.set_column(1, 3, 80)


def export_page_analysis(payload: CrawlPayload, file_path: Path) -> None:
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with xlsxwriter.Workbook(str(file_path)) as workbook:
        formats = _Formats(workbook)
        _write_performance_sheet(workbook, payload.performance)

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
                pixels = length * _PIXELS_PER_CHAR
                return _pixel_brush(formats, pixels, _TITLE_MIN, _TITLE_MAX)
            if name == "description" and col_idx == 2:
                length = _parse_int(meta_rows[row_idx][2]) or 0
                pixels = length * _PIXELS_PER_CHAR
                return _pixel_brush(formats, pixels, _DESCRIPTION_MIN, _DESCRIPTION_MAX)
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
        empty_header_rows = {
            idx for idx, row in enumerate(payload.headers) if len(row) > 1 and not str(row[1]).strip()
        }

        jump_rows = set()
        prev_level = None
        for idx, row in enumerate(payload.headers):
            tag = str(row[0]).strip().lower() if row else ""
            if tag.startswith("h") and len(tag) > 1 and tag[1:].isdigit():
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
                if tag == "h1":
                    text = str(row[1]).strip().lower() if len(row) > 1 else ""
                    if text:
                        ratio = SequenceMatcher(None, text, title_reference).ratio()
                        if ratio >= 0.9:
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

        _write_sheet(
            workbook,
            "Headers",
            ["Tag", "Text"],
            headers_rows,
            _headers_formatter,
        )

        images_rows = _stringify_rows(payload.images)

        def _images_formatter(row_idx: int, col_idx: int, value: str):
            if row_idx >= len(images_rows):
                return None
            if col_idx in (1, 2):
                return formats.good if str(images_rows[row_idx][col_idx]).strip() else formats.warn
            if col_idx == 6:
                size = _parse_size(images_rows[row_idx][col_idx])
                if size < 0:
                    return None
                if size > 500 * 1024:
                    return formats.bad
                if size > 100 * 1024:
                    return formats.warn
                return formats.good
            if col_idx in (4, 5) and not images_rows[row_idx][col_idx].strip():
                return formats.warn
            if col_idx == 0 and images_rows[row_idx][8].strip().lower() != "yes":
                return formats.warn
            if col_idx == 8:
                return formats.good if images_rows[row_idx][8].strip().lower() == "yes" else formats.warn
            if col_idx == 9:
                value_norm = images_rows[row_idx][9].strip().lower()
                if not value_norm:
                    return formats.warn
                if value_norm in {"high", "true"}:
                    return formats.good
                return None
            return None

        _write_sheet(
            workbook,
            "Images",
            ["Src", "Alt", "Title", "Type", "W", "H", "Size", "Cache", "Lazy", "Fetch priority"],
            images_rows,
            _images_formatter,
        )

        social_rows = _social_rows(payload)

        def _social_formatter(row_idx: int, col_idx: int, value: str):
            if col_idx == 8 and value:
                return formats.warn
            return None

        _write_sheet(
            workbook,
            "Social",
            ["Source", "Title", "Description", "Image", "Card", "Type", "Size (B)", "Dims", "Issues"],
            social_rows,
            _social_formatter,
        )

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
            [
                "URL",
                "Anchor",
                "Type",
                "Rel",
                "Status",
                "Status note",
                "Section",
                "Heading",
                "TLD",
            ],
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

        indexability_rows = build_indexability_rows(
            payload.redirect.to_dict(),
            payload.canonical.to_dict(),
            payload.meta_robots,
            payload.robots,
        )

        def _indexability_formatter(row_idx: int, col_idx: int, value: str):
            if col_idx != 1 or row_idx >= len(indexability_rows):
                return None
            key = indexability_rows[row_idx][0].lower()
            val = str(indexability_rows[row_idx][1] or "")
            lower_val = val.lower()
            if key == "final status":
                code = _parse_int(val)
                if code is None:
                    return formats.bad
                if 200 <= code < 300:
                    return formats.good
                if 300 <= code < 400:
                    return formats.warn
                return formats.bad
            if key == "redirect hops":
                hops = _parse_int(val)
                if hops is None:
                    return formats.bad
                return formats.good if hops == 0 else formats.warn
            if key == "crawl allowed by robots.txt":
                return formats.good if lower_val.startswith("y") else formats.bad
            if key == "meta / x-robots-tag":
                if lower_val == "-":
                    return formats.warn
                if "noindex" in lower_val or lower_val == "none":
                    return formats.bad
                if "nofollow" in lower_val:
                    return formats.warn
                return formats.good
            if key == "index directive":
                return formats.good if lower_val == "index" else formats.bad
            if key == "follow directive":
                return formats.good if lower_val == "follow" else formats.warn
            if key == "canonical url":
                return formats.good if val and val != "-" else formats.warn
            if key == "canonical self-reference":
                return formats.good if lower_val.startswith("y") else formats.warn
            if key == "canonical status":
                code = _parse_int(val)
                if code is None:
                    return formats.warn if val == "-" else formats.bad
                return formats.good if 200 <= code < 400 else formats.bad
            if key == "multiple canonicals":
                return formats.bad if lower_val.startswith("y") else formats.good
            if key == "overall verdict":
                if lower_val == "indexable":
                    return formats.good
                if lower_val in {"redirected", "canonicalized elsewhere", "indexable with warnings"}:
                    return formats.warn
                return formats.bad
            return None

        _write_sheet(
            workbook,
            "Indexability",
            ["Check", "Value"],
            indexability_rows,
            _indexability_formatter,
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

        structured = payload.schema
        blocks = list(structured.blocks)
        if not blocks and structured.fallback_raw:
            blocks = [{"@raw": raw, "_extracted_via": "json-ld-raw"} for raw in structured.fallback_raw]

        summary = structured.summary
        syntax_labels = {
            "json-ld": "JSON-LD",
            "json-ld-raw": "JSON-LD raw",
            "microdata": "Microdata",
            "microformat": "Microformat",
            "opengraph": "OpenGraph",
            "rdfa": "RDFa",
        }
        syntax_text = ", ".join(
            f"{syntax_labels.get(name, name)} {count}"
            for name, count in sorted(summary.by_syntax.items())
            if count
        )
        type_text = ", ".join(
            f"{schema_type} {count}" for schema_type, count in sorted(summary.by_type.items()) if count
        )
        total_items = summary.total or len(blocks)
        summary_rows = [
            ["Total items", str(total_items)],
            ["Syntax", syntax_text or "-"],
            ["Types", type_text or "-"],
        ]
        if summary.errors:
            summary_rows.append(["Errors", "\n".join(summary.errors)])

        _write_sheet(
            workbook,
            "Structured summary",
            ["Metric", "Value"],
            summary_rows,
        )

        detail_rows: List[List[str]] = []
        for idx, item in enumerate(blocks, start=1):
            if isinstance(item, dict):
                raw_snapshot = json.dumps({key: value for key, value in item.items() if key != "_schema_errors"}, ensure_ascii=False)
                error_text = "; ".join(str(err).strip() for err in item.get("_schema_errors", []) if str(err).strip())
                detail_rows.append(
                    [
                        str(idx),
                        str(item.get("_extracted_via", "")),
                        _schema_type_label(item.get("@type")),
                        error_text or "-",
                        raw_snapshot,
                    ]
                )
            elif isinstance(item, list):
                detail_rows.append(
                    [
                        str(idx),
                        "list",
                        "",
                        "-",
                        json.dumps(item, ensure_ascii=False),
                    ]
                )
            else:
                detail_rows.append([str(idx), "", "", "-", str(item)])

        if not detail_rows:
            detail_rows = [["-", "-", "-", "-", "-"]]

        _write_sheet(
            workbook,
            "Structured data",
            ["#", "Source", "Type", "Errors", "Raw"],
            detail_rows,
        )

        content_quality_rows = build_content_quality_rows(payload.content_quality)

        def _content_quality_formatter(row_idx: int, col_idx: int, value: str):
            if col_idx != 1 or row_idx >= len(content_quality_rows):
                return None
            key = content_quality_rows[row_idx][0].lower()
            val = str(content_quality_rows[row_idx][1] or "")
            lower_val = val.lower()
            if key == "page language":
                return formats.warn if lower_val == "not declared" else None
            if key == "title present":
                return formats.good if lower_val == "yes" else formats.bad
            if key == "meta description present":
                return formats.good if lower_val == "yes" else formats.warn
            if key == "h1 count":
                if val == "1":
                    return formats.good
                if val == "0":
                    return formats.bad
                return formats.warn
            if key == "h2-h6 count":
                return formats.warn if val == "0" else None
            if key == "title / h1 alignment":
                if lower_val in {"aligned", "exact match"}:
                    return formats.good
                if lower_val == "different":
                    return formats.warn
                if lower_val == "missing":
                    return formats.bad
            if key == "intro paragraph":
                return formats.good if lower_val == "present" else formats.warn
            if key == "thin-content risk":
                if lower_val == "low":
                    return formats.good
                if lower_val == "medium":
                    return formats.warn
                if lower_val == "high":
                    return formats.bad
            if key == "heading structure":
                if lower_val == "good":
                    return formats.good
                if lower_val in {"multiple h1s", "no subheadings"}:
                    return formats.warn
                if lower_val == "missing h1":
                    return formats.bad
            if key == "overall verdict":
                if lower_val == "strong":
                    return formats.good
                if lower_val == "needs work":
                    return formats.warn
                if lower_val == "weak":
                    return formats.bad
            return None

        _write_sheet(
            workbook,
            "Content quality",
            ["Check", "Value"],
            content_quality_rows,
            _content_quality_formatter,
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
