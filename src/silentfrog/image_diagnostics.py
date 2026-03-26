from __future__ import annotations

from typing import Iterable, Sequence

IMAGE_HEADERS = [
    "Src",
    "Alt",
    "Title",
    "Type",
    "W",
    "H",
    "Size",
    "Cache TTL",
    "Loading",
    "Fetch priority",
    "Declared W",
    "Declared H",
    "Responsive",
    "Sizes",
    "Format hint",
    "Diagnostic",
]

SRC_COL = 0
ALT_COL = 1
TITLE_COL = 2
TYPE_COL = 3
ACTUAL_WIDTH_COL = 4
ACTUAL_HEIGHT_COL = 5
SIZE_COL = 6
CACHE_COL = 7
LOADING_COL = 8
FETCH_PRIORITY_COL = 9
DECLARED_WIDTH_COL = 10
DECLARED_HEIGHT_COL = 11
RESPONSIVE_COL = 12
SIZES_COL = 13
FORMAT_HINT_COL = 14
DIAGNOSTIC_COL = 15

_LEGACY_ROW_LENGTH = 10
_ROW_LENGTH = len(IMAGE_HEADERS)
_NEXT_GEN_MIMES = {"image/avif", "image/webp"}
_LEGACY_FORMAT_HINTS = {
    "image/jpeg": "Consider WebP or AVIF",
    "image/jpg": "Consider WebP or AVIF",
    "image/png": "Consider WebP or AVIF",
    "image/gif": "Consider video or WebP",
    "image/bmp": "Consider WebP or AVIF",
}


def _text(value: object) -> str:
    return str(value).strip()


def _to_int(value: object) -> int:
    try:
        return int(_text(value))
    except (TypeError, ValueError):
        return 0


def _has_analysis_data(row: Sequence[str]) -> bool:
    return any(_text(row[index]) for index in (ACTUAL_WIDTH_COL, ACTUAL_HEIGHT_COL, SIZE_COL, CACHE_COL))


def format_hint_for_mime(mime: object) -> str:
    normalized = _text(mime).lower()
    if not normalized or normalized == "-":
        return ""
    if normalized in _NEXT_GEN_MIMES:
        return "Next-gen format"
    return _LEGACY_FORMAT_HINTS.get(normalized, "")


def responsive_label(candidate_count: int) -> str:
    if candidate_count <= 0:
        return ""
    suffix = "candidate" if candidate_count == 1 else "candidates"
    return f"{candidate_count} {suffix}"


def diagnostic_text(row: Sequence[str]) -> str:
    declared_width = _to_int(row[DECLARED_WIDTH_COL])
    declared_height = _to_int(row[DECLARED_HEIGHT_COL])
    actual_width = _to_int(row[ACTUAL_WIDTH_COL])
    actual_height = _to_int(row[ACTUAL_HEIGHT_COL])
    sizes = _text(row[SIZES_COL])
    responsive = _text(row[RESPONSIVE_COL]).lower()
    format_hint = _text(row[FORMAT_HINT_COL])
    analysed = _has_analysis_data(row)

    notes: list[str] = []
    if not declared_width or not declared_height:
        notes.append("Missing width/height attributes")
    if analysed and not _text(row[CACHE_COL]):
        notes.append("No cache TTL exposed")
    if format_hint and format_hint != "Next-gen format":
        notes.append(format_hint)
    if declared_width and declared_height and actual_width and actual_height:
        too_wide = actual_width >= declared_width * 2
        too_tall = actual_height >= declared_height * 2
        if too_wide or too_tall:
            notes.append("Source much larger than declared slot")
    if responsive not in {"", "1 candidate"} and not sizes:
        notes.append("Responsive candidates without sizes")
    return "; ".join(notes) or "OK"


def _normalize_legacy_row(values: Sequence[object]) -> list[str]:
    padded = [_text(cell) for cell in values]
    padded = (padded + [""] * _LEGACY_ROW_LENGTH)[:_LEGACY_ROW_LENGTH]
    src, alt, title, mime, width, height, size, cache, loading, fetch_priority = padded
    analysed = bool(size or cache)
    declared_width = "" if analysed else width
    declared_height = "" if analysed else height
    actual_width = width if analysed else ""
    actual_height = height if analysed else ""
    row = [
        src,
        alt,
        title,
        mime,
        actual_width,
        actual_height,
        size,
        cache,
        loading,
        fetch_priority,
        declared_width,
        declared_height,
        "",
        "",
        format_hint_for_mime(mime),
        "",
    ]
    row[DIAGNOSTIC_COL] = diagnostic_text(row)
    return row


def normalize_image_row(row: Sequence[object]) -> list[str]:
    values = [_text(cell) for cell in row]
    if len(values) < _ROW_LENGTH:
        return _normalize_legacy_row(values)
    normalized = (values + [""] * _ROW_LENGTH)[:_ROW_LENGTH]
    normalized[RESPONSIVE_COL] = _text(normalized[RESPONSIVE_COL])
    if normalized[RESPONSIVE_COL].isdigit():
        normalized[RESPONSIVE_COL] = responsive_label(int(normalized[RESPONSIVE_COL]))
    if not normalized[FORMAT_HINT_COL]:
        normalized[FORMAT_HINT_COL] = format_hint_for_mime(normalized[TYPE_COL])
    normalized[DIAGNOSTIC_COL] = diagnostic_text(normalized)
    return normalized


def merge_image_row(current: Sequence[object], update: Sequence[object]) -> list[str]:
    row = normalize_image_row(current)
    values = [_text(cell) for cell in update]
    if len(values) < 6:
        return row
    _, actual_width, actual_height, size, mime, cache = (values + [""] * 6)[:6]
    row[TYPE_COL] = mime or row[TYPE_COL]
    row[ACTUAL_WIDTH_COL] = actual_width or row[ACTUAL_WIDTH_COL]
    row[ACTUAL_HEIGHT_COL] = actual_height or row[ACTUAL_HEIGHT_COL]
    row[SIZE_COL] = size or row[SIZE_COL]
    row[CACHE_COL] = cache or row[CACHE_COL]
    row[FORMAT_HINT_COL] = format_hint_for_mime(row[TYPE_COL])
    row[DIAGNOSTIC_COL] = diagnostic_text(row)
    return row


def normalize_image_rows(rows: Iterable[Sequence[object]]) -> list[list[str]]:
    return [normalize_image_row(row) for row in rows]
