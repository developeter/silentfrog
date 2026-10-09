"""Row shapes for the tech-stack (V15) and custom-extraction (V6) results.

Qt-free so the on-screen tab and both Excel exporters share one reading of the
payload groups. ``None`` / ``[]`` means "the feature was not enabled for this
page"; an enabled-but-empty result is distinguishable (``by_category`` is
present but empty, extraction rules are present with empty values).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .tech_stack import TechStackPayload

NO_MATCH = "(no match)"
TECH_SECTION = "Tech stack"
EXTRACTION_SECTION = "Custom extraction"
SHEET_HEADERS = ["Section", "Name", "Value"]


def tech_rows(tech_stack: object) -> list[list[str]] | None:
    """[[category, "A, B"], ...]; ``None`` when detection was not enabled."""
    if not isinstance(tech_stack, Mapping) or "by_category" not in tech_stack:
        return None
    by_category = TechStackPayload.from_raw(dict(tech_stack)).by_category
    return [[category, ", ".join(names)] for category, names in sorted(by_category.items()) if names]


def extraction_rows(extracted: object) -> list[list[str]]:
    """[[rule, value], ...]; empty when no rule ran."""
    if not isinstance(extracted, Mapping):
        return []
    return [[str(name), str(value) or NO_MATCH] for name, value in extracted.items()]


def sheet_rows(tech_stack: Any, extracted: Any) -> list[list[str]]:
    """Flat [section, name, value] rows for the Excel sheets (no placeholder
    rows: a page with nothing enabled contributes nothing)."""
    rows = [[TECH_SECTION, *row] for row in tech_rows(tech_stack) or []]
    rows.extend([EXTRACTION_SECTION, *row] for row in extraction_rows(extracted))
    return rows
