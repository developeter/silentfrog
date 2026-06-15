"""Rich-result eligibility (v2.0 V14).

Google retired its public Rich Results Test API, so eligibility is
derived from the page's own structured data — the same per-type
validators that power the Structured Data tab — and, when a site is
connected to Search Console, upgraded with Google's real verdict via
the URL Inspection API.

Pure + tolerant: every entry point returns a ``RichResultsReport`` and
never raises. ``measured=False`` => the checks layer emits ``info`` and
never penalises the GEO Score (§1.5).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_ELIGIBLE = "Eligible"
_INCOMPLETE = "Incomplete"


@dataclass(frozen=True)
class RichResultsReport:
    eligible_types: tuple[str, ...] = ()
    ineligible_types: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    source: str = "schema"  # "schema" | "gsc"
    measured: bool = False

    @classmethod
    def from_dict(cls, value: Any) -> RichResultsReport:
        if not isinstance(value, Mapping):
            return cls()
        return cls(
            eligible_types=_str_tuple(value.get("eligible_types")),
            ineligible_types=_str_tuple(value.get("ineligible_types")),
            warnings=_str_tuple(value.get("warnings")),
            source=str(value.get("source", "schema")) or "schema",
            measured=bool(value.get("measured", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible_types": list(self.eligible_types),
            "ineligible_types": list(self.ineligible_types),
            "warnings": list(self.warnings),
            "source": self.source,
            "measured": self.measured,
        }


def _str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _eligibility_rows(schema_payload: Any) -> list[Any]:
    if not isinstance(schema_payload, Mapping):
        return []
    rows = schema_payload.get("eligibility")
    if isinstance(rows, list) and rows:
        return rows
    return _compute_eligibility(schema_payload)


def _compute_eligibility(schema_payload: Mapping[str, Any]) -> list[Any]:
    blocks = schema_payload.get("blocks")
    if not isinstance(blocks, list):
        return []
    dict_blocks = [block for block in blocks if isinstance(block, dict)]
    try:
        from ...schema_extractor import _schema_build_eligibility  # lazy; avoids a cycle

        return _schema_build_eligibility(dict_blocks)
    except Exception:
        return []


def _classify_row(row: Any, eligible: list[str], ineligible: list[str], warnings: list[str]) -> None:
    if not isinstance(row, Mapping):
        return
    bucket = {_ELIGIBLE: eligible, _INCOMPLETE: ineligible}.get(str(row.get("eligibility", "")))
    if bucket is None:  # "Not detected" — ignored
        return
    bucket.append(str(row.get("type", "")))
    warnings.extend(str(item) for item in row.get("warnings", []) if str(item).strip())


def derive_from_schema(schema_payload: Any) -> RichResultsReport:
    """Build the report from the page's own structured-data eligibility."""
    rows = _eligibility_rows(schema_payload)
    eligible: list[str] = []
    ineligible: list[str] = []
    warnings: list[str] = []
    for row in rows:
        _classify_row(row, eligible, ineligible, warnings)
    return RichResultsReport(
        eligible_types=tuple(eligible),
        ineligible_types=tuple(ineligible),
        warnings=tuple(warnings),
        source="schema",
        measured=bool(eligible or ineligible),
    )


def _inspection_rich_node(inspection_json: Any) -> Mapping[str, Any] | None:
    node: Any = inspection_json
    for key in ("inspectionResult", "richResultsResult"):
        node = node.get(key) if isinstance(node, Mapping) else None
    return node if isinstance(node, Mapping) else None


def _item_issues(entry: Any, rich_type: str) -> list[str]:
    issues = entry.get("issues") if isinstance(entry, Mapping) else None
    if not isinstance(issues, list):
        return []
    return [
        f"{rich_type}: {issue.get('issueMessage', '')}".strip()
        for issue in issues
        if isinstance(issue, Mapping) and str(issue.get("severity", "")).upper() == "ERROR"
    ]


def _collect_inspection_item(item: Any, eligible: list[str], warnings: list[str]) -> None:
    if not isinstance(item, Mapping):
        return
    rich_type = str(item.get("richResultType", "")).strip()
    if rich_type:
        eligible.append(rich_type)
    for entry in item.get("items", []) or []:
        warnings.extend(_item_issues(entry, rich_type))


def from_url_inspection(inspection_json: Any) -> RichResultsReport:
    """Parse a GSC URL Inspection response into the report (source=gsc)."""
    rich = _inspection_rich_node(inspection_json)
    detected = rich.get("detectedItems") if isinstance(rich, Mapping) else None
    items = detected if isinstance(detected, list) else []
    eligible: list[str] = []
    warnings: list[str] = []
    for item in items:
        _collect_inspection_item(item, eligible, warnings)
    return RichResultsReport(
        eligible_types=tuple(eligible),
        warnings=tuple(warnings),
        source="gsc",
        measured=bool(items),
    )


__all__ = ["RichResultsReport", "derive_from_schema", "from_url_inspection"]
