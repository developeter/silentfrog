from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .image_diagnostics import normalize_image_rows


def _is_iterable_of_iterables(value: Any) -> bool:
    return isinstance(value, Iterable) and not isinstance(value, (str, bytes))


def _normalize_rows(value: Any, *, label: str) -> list[list[str]]:
    if not _is_iterable_of_iterables(value):
        raise ValueError(f"{label} must be an iterable of rows")
    rows: list[list[str]] = []
    for row in value:
        if not _is_iterable_of_iterables(row):
            raise ValueError(f"{label} rows must be iterable")
        rows.append([str(cell) for cell in row])
    return rows


def _ensure_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    raise ValueError(f"{label} must be a mapping")


def _normalize_robots(value: Any) -> dict[str, list[tuple[str, str]]]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, list[tuple[str, str]]] = {}
    for agent, directives in value.items():
        bucket: list[tuple[str, str]] = []
        if _is_iterable_of_iterables(directives):
            for directive in directives:
                if isinstance(directive, (tuple, list)) and len(directive) >= 2:
                    bucket.append((str(directive[0]), str(directive[1])))
        normalized[str(agent)] = bucket
    return normalized


def _parse_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalize_ai_visibility_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    mapping = {
        "ok": "good",
        "pass": "good",
        "good": "good",
        "info": "good",
        "warn": "warning",
        "warning": "warning",
        "needs work": "warning",
        "bad": "critical",
        "risk": "critical",
        "critical": "critical",
        "blocked": "critical",
    }
    return mapping.get(normalized, "warning")


_REQUIRED_CRAWL_KEYS = {
    "meta",
    "headers",
    "images",
    "links",
    "schema",
    "canonical",
    "redirect",
    "robots",
    "meta_robots",
    "hreflang",
    "ai_crawl",
    "serp",
    "serp_audit",
    "keywords",
}


def _require_crawl_keys(data: Mapping[str, Any]) -> None:
    missing = sorted(_REQUIRED_CRAWL_KEYS - set(data.keys()))
    if missing:
        raise ValueError(f"Missing crawl keys: {', '.join(missing)}")


def _rows_section(data: Mapping[str, Any], key: str) -> list[list[str]]:
    return _normalize_rows(data[key], label=key)


def _mapping_section(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _ensure_mapping(data[key], key)


def _optional_mapping_section(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    raw = data.get(key, {})
    if not isinstance(raw, Mapping):
        return {}
    return _ensure_mapping(raw, key)


def _string_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _keyword_entries(raw: Any) -> list[KeywordEntry]:
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        return []
    return [KeywordEntry.from_raw(item) for item in raw if isinstance(item, Mapping)]


def _mapping_items(raw: Any) -> list[Mapping[str, Any]]:
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _string_items(raw: Any) -> list[str]:
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        return []
    values: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            values.append(text)
    return values


@dataclass(frozen=True)
class PerformanceMetrics:
    nav_ttfb_ms: float
    nav_total_ms: float
    transfer_size: int
    status: int
    resource_summary: dict[str, dict[str, int]]
    resource_breakdown: list[PerformanceResourceBreakdown]
    summary: PerformanceSummary
    issues: list[PerformanceIssue]
    opportunities: list[str]
    top_offenders: list[PerformanceOffender]
    scripts: PerformanceScripts
    opportunity_details: list[PerformanceOpportunity]

    @staticmethod
    def _resource_breakdown_from_summary(
        summary: Mapping[str, dict[str, int]], transfer_size: int
    ) -> list[PerformanceResourceBreakdown]:
        rows = [PerformanceResourceBreakdown(resource_type="html", count=1, bytes=max(transfer_size, 0))]
        for name in ("css", "js", "img", "font", "other"):
            item = summary.get(name, {})
            rows.append(
                PerformanceResourceBreakdown(
                    resource_type=name,
                    count=max(int(item.get("count", 0)), 0),
                    bytes=max(int(item.get("bytes", 0)), 0),
                )
            )
        return rows

    @staticmethod
    def _summary_from_legacy(
        summary: Mapping[str, dict[str, int]],
        transfer_size: int,
        issues: Iterable[PerformanceIssue],
        opportunity_details: Iterable[PerformanceOpportunity],
    ) -> PerformanceSummary:
        total_resource_bytes = sum(max(int(item.get("bytes", 0)), 0) for item in summary.values())
        total_resource_count = sum(max(int(item.get("count", 0)), 0) for item in summary.values())
        severities = [issue.severity for issue in issues]
        if not severities:
            severities = [item.severity for item in opportunity_details]
        critical_count = sum(1 for severity in severities if severity == "critical")
        warning_count = sum(1 for severity in severities if severity == "warning")
        info_count = sum(1 for severity in severities if severity == "info")
        verdict = "Good"
        if critical_count > 0:
            verdict = "High performance risk"
        elif warning_count > 0:
            verdict = "Needs work"
        return PerformanceSummary(
            transfer_size=max(transfer_size, 0),
            total_resource_bytes=total_resource_bytes,
            total_page_bytes=max(transfer_size, 0) + total_resource_bytes,
            total_resource_count=total_resource_count,
            third_party_bytes=0,
            third_party_count=0,
            critical_issue_count=critical_count,
            warning_issue_count=warning_count,
            info_issue_count=info_count,
            verdict=verdict,
        )

    @classmethod
    def empty(cls) -> PerformanceMetrics:
        return cls(
            nav_ttfb_ms=0.0,
            nav_total_ms=0.0,
            transfer_size=0,
            status=0,
            resource_summary={},
            resource_breakdown=[],
            summary=PerformanceSummary.empty(),
            issues=[],
            opportunities=[],
            top_offenders=[],
            scripts=PerformanceScripts.empty(),
            opportunity_details=[],
        )

    @staticmethod
    def _resource_summary(raw: Any) -> dict[str, dict[str, int]]:
        if not isinstance(raw, Mapping):
            return {}
        summary: dict[str, dict[str, int]] = {}
        for key, item in raw.items():
            if not isinstance(item, Mapping):
                continue
            summary[str(key)] = {
                "count": _to_int(item.get("count", 0)),
                "bytes": _to_int(item.get("bytes", 0)),
            }
        return summary

    @staticmethod
    def _model_list(raw: Any, factory):
        return [factory(item) for item in _mapping_items(raw)]

    @classmethod
    def from_raw(cls, value: Any) -> PerformanceMetrics:
        if not isinstance(value, Mapping):
            return cls.empty()

        summary = cls._resource_summary(value.get("resource_summary"))
        opp = _string_items(value.get("opportunities", []))
        offenders = cls._model_list(value.get("top_offenders", []), PerformanceOffender.from_raw)
        scripts = PerformanceScripts.from_raw(value.get("scripts"))
        breakdown = cls._model_list(value.get("resource_breakdown", []), PerformanceResourceBreakdown.from_raw)
        issues = cls._model_list(value.get("issues", []), PerformanceIssue.from_raw)
        opportunity_details = cls._model_list(
            value.get("opportunity_details", []),
            PerformanceOpportunity.from_raw,
        )

        transfer_size = _to_int(value.get("transfer_size", 0))
        if not breakdown:
            breakdown = cls._resource_breakdown_from_summary(summary, transfer_size)
        summary_model = PerformanceSummary.from_raw(value.get("summary"))
        if summary_model == PerformanceSummary.empty() and (summary or transfer_size):
            summary_model = cls._summary_from_legacy(summary, transfer_size, issues, opportunity_details)

        return cls(
            nav_ttfb_ms=_to_float(value.get("nav_ttfb_ms", 0.0)),
            nav_total_ms=_to_float(value.get("nav_total_ms", 0.0)),
            transfer_size=transfer_size,
            status=_to_int(value.get("status", 0)),
            resource_summary=summary,
            resource_breakdown=breakdown,
            summary=summary_model,
            issues=issues,
            opportunities=opp,
            top_offenders=offenders,
            scripts=scripts,
            opportunity_details=opportunity_details,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "nav_ttfb_ms": self.nav_ttfb_ms,
            "nav_total_ms": self.nav_total_ms,
            "transfer_size": self.transfer_size,
            "status": self.status,
            "resource_summary": {k: dict(v) for k, v in self.resource_summary.items()},
            "resource_breakdown": [entry.to_dict() for entry in self.resource_breakdown],
            "summary": self.summary.to_dict(),
            "issues": [item.to_dict() for item in self.issues],
            "opportunities": list(self.opportunities),
            "top_offenders": [entry.to_dict() for entry in self.top_offenders],
            "scripts": self.scripts.to_dict(),
            "opportunity_details": [item.to_dict() for item in self.opportunity_details],
        }


@dataclass(frozen=True)
class PerformanceResourceBreakdown:
    resource_type: str
    count: int
    bytes: int

    @classmethod
    def from_raw(cls, value: Mapping[str, Any]) -> PerformanceResourceBreakdown:
        try:
            count = int(value.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        try:
            size = int(value.get("bytes", 0))
        except (TypeError, ValueError):
            size = 0
        return cls(
            resource_type=str(value.get("type", "")).strip(),
            count=max(count, 0),
            bytes=max(size, 0),
        )

    def to_dict(self) -> dict[str, int | str]:
        return {"type": self.resource_type, "count": self.count, "bytes": self.bytes}


@dataclass(frozen=True)
class PerformanceSummary:
    transfer_size: int
    total_resource_bytes: int
    total_page_bytes: int
    total_resource_count: int
    third_party_bytes: int
    third_party_count: int
    critical_issue_count: int
    warning_issue_count: int
    info_issue_count: int
    verdict: str

    @classmethod
    def empty(cls) -> PerformanceSummary:
        return cls(0, 0, 0, 0, 0, 0, 0, 0, 0, "")

    @classmethod
    def from_raw(cls, value: Any) -> PerformanceSummary:
        if not isinstance(value, Mapping):
            return cls.empty()

        def _to_int(raw: Any) -> int:
            try:
                return max(int(raw), 0)
            except (TypeError, ValueError):
                return 0

        return cls(
            transfer_size=_to_int(value.get("transfer_size", 0)),
            total_resource_bytes=_to_int(value.get("total_resource_bytes", 0)),
            total_page_bytes=_to_int(value.get("total_page_bytes", 0)),
            total_resource_count=_to_int(value.get("total_resource_count", 0)),
            third_party_bytes=_to_int(value.get("third_party_bytes", 0)),
            third_party_count=_to_int(value.get("third_party_count", 0)),
            critical_issue_count=_to_int(value.get("critical_issue_count", 0)),
            warning_issue_count=_to_int(value.get("warning_issue_count", 0)),
            info_issue_count=_to_int(value.get("info_issue_count", 0)),
            verdict=str(value.get("verdict", "")).strip(),
        )

    def to_dict(self) -> dict[str, int | str]:
        return {
            "transfer_size": self.transfer_size,
            "total_resource_bytes": self.total_resource_bytes,
            "total_page_bytes": self.total_page_bytes,
            "total_resource_count": self.total_resource_count,
            "third_party_bytes": self.third_party_bytes,
            "third_party_count": self.third_party_count,
            "critical_issue_count": self.critical_issue_count,
            "warning_issue_count": self.warning_issue_count,
            "info_issue_count": self.info_issue_count,
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class PerformanceIssue:
    key: str
    severity: str
    message: str
    evidence: str
    recommendation: str

    @classmethod
    def from_raw(cls, value: Mapping[str, Any]) -> PerformanceIssue:
        return cls(
            key=str(value.get("key", "")).strip(),
            severity=str(value.get("severity", "info")).strip().lower() or "info",
            message=str(value.get("message", "")).strip(),
            evidence=str(value.get("evidence", "")).strip(),
            recommendation=str(value.get("recommendation", "")).strip(),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True)
class PerformanceScripts:
    blocking_count: int
    blocking_bytes: int
    async_count: int
    async_bytes: int

    @classmethod
    def empty(cls) -> PerformanceScripts:
        return cls(0, 0, 0, 0)

    @classmethod
    def from_raw(cls, value: Any) -> PerformanceScripts:
        if not isinstance(value, Mapping):
            return cls.empty()

        def _part(key: str) -> dict[str, int]:
            raw = value.get(key, {})
            if isinstance(raw, Mapping):
                count = raw.get("count", 0)
                bytes_val = raw.get("bytes", 0)
            else:
                count = 0
                bytes_val = 0
            try:
                count_int = int(count)
            except (TypeError, ValueError):
                count_int = 0
            try:
                bytes_int = int(bytes_val)
            except (TypeError, ValueError):
                bytes_int = 0
            return {"count": max(count_int, 0), "bytes": max(bytes_int, 0)}

        blocking = _part("blocking")
        async_part = _part("async")
        return cls(
            blocking_count=blocking["count"],
            blocking_bytes=blocking["bytes"],
            async_count=async_part["count"],
            async_bytes=async_part["bytes"],
        )

    def to_dict(self) -> dict[str, dict[str, int]]:
        return {
            "blocking": {"count": self.blocking_count, "bytes": self.blocking_bytes},
            "async": {"count": self.async_count, "bytes": self.async_bytes},
        }


@dataclass(frozen=True)
class PerformanceOffender:
    resource_type: str
    url: str
    bytes: int
    blocking: bool = False

    @classmethod
    def from_raw(cls, value: Mapping[str, Any]) -> PerformanceOffender:
        resource_type = str(value.get("type", "")).strip()
        url = str(value.get("url", "")).strip()
        try:
            size = int(value.get("bytes", 0))
        except (TypeError, ValueError):
            size = 0
        blocking = bool(value.get("blocking", False))
        return cls(resource_type=resource_type, url=url, bytes=max(size, 0), blocking=blocking)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.resource_type,
            "url": self.url,
            "bytes": self.bytes,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class PerformanceOpportunity:
    message: str
    severity: str

    @classmethod
    def from_raw(cls, value: Mapping[str, Any]) -> PerformanceOpportunity:
        message = str(value.get("message", "")).strip()
        severity = str(value.get("severity", "")).strip().lower()
        return cls(message=message, severity=severity or "info")

    def to_dict(self) -> dict[str, str]:
        return {"message": self.message, "severity": self.severity}


@dataclass(frozen=True)
class StructuredDataSummary:
    total: int
    by_syntax: dict[str, int]
    by_type: dict[str, int]
    errors: list[str]

    @staticmethod
    def _as_int_dict(value: Any) -> dict[str, int]:
        if not isinstance(value, Mapping):
            return {}
        result: dict[str, int] = {}
        for key, raw in value.items():
            try:
                result[str(key)] = int(raw)
            except (TypeError, ValueError):
                continue
        return result

    @classmethod
    def empty(cls) -> StructuredDataSummary:
        return cls(total=0, by_syntax={}, by_type={}, errors=[])

    @classmethod
    def from_raw(cls, value: Any) -> StructuredDataSummary:
        if not isinstance(value, Mapping):
            return cls.empty()
        try:
            total = int(value.get("total", 0))
        except (TypeError, ValueError):
            total = 0
        by_syntax = cls._as_int_dict(value.get("by_syntax"))
        by_type = cls._as_int_dict(value.get("by_type"))
        errors_raw = value.get("errors", [])
        errors: list[str] = []
        if isinstance(errors_raw, Iterable) and not isinstance(errors_raw, (str, bytes)):
            for item in errors_raw:
                text = str(item).strip()
                if text:
                    errors.append(text)
        return cls(total=total, by_syntax=by_syntax, by_type=by_type, errors=errors)

    def with_errors(self, extra: Iterable[str]) -> StructuredDataSummary:
        merged: list[str] = list(self.errors)
        seen = set(merged)
        for item in extra:
            text = str(item).strip()
            if not text or text in seen:
                continue
            merged.append(text)
            seen.add(text)
        if merged == self.errors:
            return self
        return StructuredDataSummary(
            total=self.total,
            by_syntax=dict(self.by_syntax),
            by_type=dict(self.by_type),
            errors=merged,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "by_syntax": dict(self.by_syntax),
            "by_type": dict(self.by_type),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class StructuredDataEligibility:
    schema_type: str
    detected: bool
    count: int
    eligibility: str
    missing_fields: list[str]
    warnings: list[str]

    @classmethod
    def from_raw(cls, value: Any) -> StructuredDataEligibility:
        if not isinstance(value, Mapping):
            return cls(
                schema_type="",
                detected=False,
                count=0,
                eligibility="Not detected",
                missing_fields=[],
                warnings=[],
            )
        try:
            count = int(value.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        missing_raw = value.get("missing_fields", [])
        missing_fields: list[str] = []
        if isinstance(missing_raw, Iterable) and not isinstance(missing_raw, (str, bytes)):
            missing_fields = [str(item).strip() for item in missing_raw if str(item).strip()]
        warnings_raw = value.get("warnings", [])
        warnings: list[str] = []
        if isinstance(warnings_raw, Iterable) and not isinstance(warnings_raw, (str, bytes)):
            warnings = [str(item).strip() for item in warnings_raw if str(item).strip()]
        return cls(
            schema_type=str(value.get("type", "")).strip(),
            detected=bool(value.get("detected", False)),
            count=max(count, 0),
            eligibility=str(value.get("eligibility", "Not detected")).strip() or "Not detected",
            missing_fields=missing_fields,
            warnings=warnings,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.schema_type,
            "detected": self.detected,
            "count": self.count,
            "eligibility": self.eligibility,
            "missing_fields": list(self.missing_fields),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class StructuredDataPayload:
    blocks: list[Any]
    summary: StructuredDataSummary
    fallback_raw: list[str]
    eligibility: list[StructuredDataEligibility] = field(default_factory=list)

    @classmethod
    def empty(cls) -> StructuredDataPayload:
        return cls(blocks=[], summary=StructuredDataSummary.empty(), fallback_raw=[], eligibility=[])

    @staticmethod
    def _coerce_blocks(value: Any) -> list[Any]:
        if isinstance(value, list):
            return list(value)
        if _is_iterable_of_iterables(value):
            return list(value)
        return []

    @staticmethod
    def _coerce_fallback(raw: Any) -> list[str]:
        if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
            return []
        fallback: list[str] = []
        for item in raw:
            text = str(item).strip()
            if text:
                fallback.append(text)
        return fallback

    @classmethod
    def from_raw(cls, value: Any) -> StructuredDataPayload:
        if isinstance(value, StructuredDataPayload):
            return value
        if isinstance(value, Mapping):
            summary = StructuredDataSummary.from_raw(value.get("summary", {}))
            blocks = cls._coerce_blocks(value.get("blocks"))
            issues_raw = value.get("issues", [])
            issues_iter: Iterable[str] = (
                issues_raw if isinstance(issues_raw, Iterable) and not isinstance(issues_raw, (str, bytes)) else []
            )
            summary = summary.with_errors(issues_iter)
            fallback_raw = cls._coerce_fallback(value.get("fallback_raw"))
            eligibility_raw = value.get("eligibility", [])
            eligibility: list[StructuredDataEligibility] = []
            if isinstance(eligibility_raw, Iterable) and not isinstance(eligibility_raw, (str, bytes)):
                eligibility = [
                    StructuredDataEligibility.from_raw(item) for item in eligibility_raw if isinstance(item, Mapping)
                ]
            return cls(blocks=blocks, summary=summary, fallback_raw=fallback_raw, eligibility=eligibility)
        if isinstance(value, list):
            summary_raw: Mapping[str, Any] | None = None
            issues_list: list[str] = []
            blocks: list[Any] = []
            fallback: list[str] = []
            for item in value:
                if isinstance(item, Mapping) and "_schema_summary" in item and summary_raw is None:
                    raw = item.get("_schema_summary", {})
                    summary_raw = raw if isinstance(raw, Mapping) else {}
                    continue
                if isinstance(item, Mapping) and "_schema_issues" in item:
                    for issue in item.get("_schema_issues") or []:
                        text = str(issue).strip()
                        if text:
                            issues_list.append(text)
                    continue
                if isinstance(item, list):
                    if item:
                        text = str(item[0]).strip()
                        if text:
                            fallback.append(text)
                    continue
                blocks.append(item)
            summary = StructuredDataSummary.from_raw(summary_raw or {})
            summary = summary.with_errors(issues_list)
            return cls(blocks=blocks, summary=summary, fallback_raw=fallback, eligibility=[])
        return cls.empty()

    def to_mapping(self) -> dict[str, Any]:
        return {
            "blocks": list(self.blocks),
            "summary": self.summary.to_dict(),
            "fallback_raw": list(self.fallback_raw),
            "eligibility": [item.to_dict() for item in self.eligibility],
            "issues": list(self.summary.errors),
        }


@dataclass(frozen=True)
class KeywordEntry:
    term: str
    length: int
    frequency: int
    density: float
    density_threshold: float
    density_warning: bool
    in_title: bool
    in_description: bool
    heading_count: int
    first_position: int | None

    @classmethod
    def from_raw(cls, value: Mapping[str, Any]) -> KeywordEntry:
        def _to_float(raw: Any, default: float = 0.0) -> float:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return default

        def _to_int(raw: Any, default: int = 0) -> int:
            try:
                if isinstance(raw, bool):
                    return default
                return int(raw)
            except (TypeError, ValueError):
                return default

        first_raw = value.get("first_position")
        first_position = None
        if isinstance(first_raw, (int, float)) and not isinstance(first_raw, bool):
            first_position = int(first_raw)
        else:
            try:
                first_position = int(str(first_raw))
            except (TypeError, ValueError):
                first_position = None

        return cls(
            term=str(value.get("term", "")),
            length=_to_int(value.get("length", 1), 1),
            frequency=_to_int(value.get("frequency", 0), 0),
            density=_to_float(value.get("density", 0.0)),
            density_threshold=_to_float(value.get("density_threshold", 4.0), 4.0),
            density_warning=bool(value.get("density_warning", False)),
            in_title=bool(value.get("in_title", False)),
            in_description=bool(value.get("in_description", False)),
            heading_count=_to_int(value.get("heading_count", 0), 0),
            first_position=first_position if first_position is not None and first_position >= 0 else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "term": self.term,
            "length": self.length,
            "frequency": self.frequency,
            "density": self.density,
            "density_threshold": self.density_threshold,
            "density_warning": self.density_warning,
            "in_title": self.in_title,
            "in_description": self.in_description,
            "heading_count": self.heading_count,
            "first_position": self.first_position if self.first_position is not None else -1,
        }

    def formatted_density(self) -> str:
        return f"{self.density:.2f}"


@dataclass(frozen=True)
class ContentQuality:
    language: str
    word_count: int
    paragraph_count: int
    substantial_paragraph_count: int
    average_words_per_paragraph: float
    title_present: bool
    meta_description_present: bool
    h1_count: int
    h2_h6_count: int
    title_h1_alignment: str
    intro_paragraph: str
    thin_content_risk: str
    heading_structure: str
    verdict: str

    @classmethod
    def empty(cls) -> ContentQuality:
        return cls(
            language="",
            word_count=0,
            paragraph_count=0,
            substantial_paragraph_count=0,
            average_words_per_paragraph=0.0,
            title_present=False,
            meta_description_present=False,
            h1_count=0,
            h2_h6_count=0,
            title_h1_alignment="",
            intro_paragraph="",
            thin_content_risk="",
            heading_structure="",
            verdict="",
        )

    @classmethod
    def from_raw(cls, value: Any) -> ContentQuality:
        if not isinstance(value, Mapping):
            return cls.empty()

        def _to_float(raw: Any) -> float:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return 0.0

        def _to_int(raw: Any) -> int:
            try:
                if isinstance(raw, bool):
                    return 0
                return int(raw)
            except (TypeError, ValueError):
                return 0

        return cls(
            language=str(value.get("language", "")),
            word_count=_to_int(value.get("word_count", 0)),
            paragraph_count=_to_int(value.get("paragraph_count", 0)),
            substantial_paragraph_count=_to_int(value.get("substantial_paragraph_count", 0)),
            average_words_per_paragraph=_to_float(value.get("average_words_per_paragraph", 0.0)),
            title_present=bool(value.get("title_present", False)),
            meta_description_present=bool(value.get("meta_description_present", False)),
            h1_count=_to_int(value.get("h1_count", 0)),
            h2_h6_count=_to_int(value.get("h2_h6_count", 0)),
            title_h1_alignment=str(value.get("title_h1_alignment", "")),
            intro_paragraph=str(value.get("intro_paragraph", "")),
            thin_content_risk=str(value.get("thin_content_risk", "")),
            heading_structure=str(value.get("heading_structure", "")),
            verdict=str(value.get("verdict", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "word_count": self.word_count,
            "paragraph_count": self.paragraph_count,
            "substantial_paragraph_count": self.substantial_paragraph_count,
            "average_words_per_paragraph": self.average_words_per_paragraph,
            "title_present": self.title_present,
            "meta_description_present": self.meta_description_present,
            "h1_count": self.h1_count,
            "h2_h6_count": self.h2_h6_count,
            "title_h1_alignment": self.title_h1_alignment,
            "intro_paragraph": self.intro_paragraph,
            "thin_content_risk": self.thin_content_risk,
            "heading_structure": self.heading_structure,
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class CanonicalInfo:
    target: str
    is_self: bool
    multiple: bool
    status: str

    @classmethod
    def from_raw(cls, value: Mapping[str, Any]) -> CanonicalInfo:
        return cls(
            target=str(value.get("target", "")),
            is_self=bool(value.get("self", False)),
            multiple=bool(value.get("multiple", False)),
            status=str(value.get("status", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "self": self.is_self,
            "multiple": self.multiple,
            "status": self.status,
        }


@dataclass(frozen=True)
class RedirectInfo:
    chain: list[str]
    hops: int
    final_status: str
    loop: bool

    @classmethod
    def from_raw(cls, value: Mapping[str, Any]) -> RedirectInfo:
        chain_raw = value.get("chain", [])
        chain = [str(item) for item in chain_raw] if _is_iterable_of_iterables(chain_raw) else []
        return cls(
            chain=chain,
            hops=int(value.get("hops", 0)),
            final_status=str(value.get("final_status", "")),
            loop=bool(value.get("loop", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "hops": self.hops,
            "chain": list(self.chain),
            "final_status": self.final_status,
            "loop": self.loop,
        }


@dataclass(frozen=True)
class SerpPreview:
    title: str
    description: str
    url: str
    site_name: str
    favicon: str
    breadcrumb: str

    @classmethod
    def from_raw(cls, value: Mapping[str, Any]) -> SerpPreview:
        return cls(
            title=str(value.get("title", "")),
            description=str(value.get("description", "")),
            url=str(value.get("url", "")),
            site_name=str(value.get("site_name", "")),
            favicon=str(value.get("favicon", "")),
            breadcrumb=str(value.get("breadcrumb", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "site_name": self.site_name,
            "favicon": self.favicon,
            "breadcrumb": self.breadcrumb,
        }


@dataclass(frozen=True)
class SerpAudit:
    too_long: str
    too_short: str
    px_over: str
    px_under: str
    equals_h1: str
    missing: str
    px_len: str
    char_len: str

    @classmethod
    def from_raw(cls, value: Mapping[str, Any]) -> SerpAudit:
        return cls(
            too_long=str(value.get("too_long", "")),
            too_short=str(value.get("too_short", "")),
            px_over=str(value.get("px_over", "")),
            px_under=str(value.get("px_under", "")),
            equals_h1=str(value.get("equals_h1", "")),
            missing=str(value.get("missing", "")),
            px_len=str(value.get("px_len", "")),
            char_len=str(value.get("char_len", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "too_long": self.too_long,
            "too_short": self.too_short,
            "px_over": self.px_over,
            "px_under": self.px_under,
            "equals_h1": self.equals_h1,
            "missing": self.missing,
            "px_len": self.px_len,
            "char_len": self.char_len,
        }


@dataclass(frozen=True)
class SocialCard:
    title: str
    description: str
    image: str
    image_data: str
    site_name: str
    url: str
    card: str
    image_width: int
    image_height: int
    image_bytes: int
    image_type: str
    issues: list[str]

    @classmethod
    def from_raw(cls, data: Mapping[str, Any]) -> SocialCard:
        return cls(
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            image=str(data.get("image", "")),
            image_data=str(data.get("image_data", "")),
            site_name=str(data.get("site_name", "")),
            url=str(data.get("url", "")),
            card=str(data.get("card", "")),
            image_width=_parse_int(data.get("image_width")) or 0,
            image_height=_parse_int(data.get("image_height")) or 0,
            image_bytes=_parse_int(data.get("image_bytes")) or 0,
            image_type=str(data.get("image_type", "")),
            issues=[str(item) for item in data.get("issues", []) if isinstance(item, (str, int))],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "image": self.image,
            "image_data": self.image_data,
            "site_name": self.site_name,
            "url": self.url,
            "card": self.card,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "image_bytes": self.image_bytes,
            "image_type": self.image_type,
            "issues": list(self.issues),
        }


@dataclass(frozen=True)
class SocialPayload:
    open_graph: SocialCard
    twitter: SocialCard

    @classmethod
    def empty(cls) -> SocialPayload:
        empty = SocialCard(
            title="",
            description="",
            image="",
            site_name="",
            url="",
            card="",
            image_width=0,
            image_height=0,
            image_bytes=0,
            image_type="",
            image_data="",
            issues=[],
        )
        return cls(open_graph=empty, twitter=empty)

    @classmethod
    def from_raw(cls, data: Mapping[str, Any]) -> SocialPayload:
        if not data:
            return cls.empty()
        og_raw = _ensure_mapping(data.get("open_graph", {}), "open_graph")
        tw_raw = _ensure_mapping(data.get("twitter", {}), "twitter")
        return cls(open_graph=SocialCard.from_raw(og_raw), twitter=SocialCard.from_raw(tw_raw))

    def to_dict(self) -> dict[str, Any]:
        return {"open_graph": self.open_graph.to_dict(), "twitter": self.twitter.to_dict()}


@dataclass(frozen=True)
class AiVisibilityCheck:
    area: str
    check: str
    status: str
    details: str
    recommendation: str
    key: str = ""

    @classmethod
    def from_raw(cls, value: Mapping[str, Any]) -> AiVisibilityCheck:
        return cls(
            area=str(value.get("area", "")).strip(),
            check=str(value.get("check", "")).strip(),
            status=_normalize_ai_visibility_status(value.get("status", "")),
            details=str(value.get("details", "")).strip(),
            recommendation=str(value.get("recommendation", "")).strip(),
            key=str(value.get("key", "")).strip(),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "area": self.area,
            "check": self.check,
            "status": self.status,
            "details": self.details,
            "recommendation": self.recommendation,
            "key": self.key,
        }


@dataclass(frozen=True)
class AiVisibilitySummary:
    verdict: str
    good_count: int
    warning_count: int
    critical_count: int
    score: int = 0

    @classmethod
    def empty(cls) -> AiVisibilitySummary:
        return cls(verdict="", good_count=0, warning_count=0, critical_count=0, score=0)

    @classmethod
    def from_raw(cls, value: Any) -> AiVisibilitySummary:
        if not isinstance(value, Mapping):
            return cls.empty()

        def _to_int(raw: Any) -> int:
            try:
                return max(int(raw), 0)
            except (TypeError, ValueError):
                return 0

        return cls(
            verdict=str(value.get("verdict", "")).strip(),
            good_count=_to_int(value.get("good_count", 0)),
            warning_count=_to_int(value.get("warning_count", 0)),
            critical_count=_to_int(value.get("critical_count", 0)),
            score=_clamp_score(value.get("score", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "good_count": self.good_count,
            "warning_count": self.warning_count,
            "critical_count": self.critical_count,
            "score": self.score,
        }


def _clamp_score(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, value))


@dataclass(frozen=True)
class AiVisibilityPayload:
    summary: AiVisibilitySummary
    checks: list[AiVisibilityCheck]

    @classmethod
    def empty(cls) -> AiVisibilityPayload:
        return cls(summary=AiVisibilitySummary.empty(), checks=[])

    @classmethod
    def from_raw(cls, value: Any) -> AiVisibilityPayload:
        if not isinstance(value, Mapping):
            return cls.empty()
        checks_raw = value.get("checks", [])
        checks = (
            [AiVisibilityCheck.from_raw(item) for item in checks_raw if isinstance(item, Mapping)]
            if isinstance(checks_raw, Iterable) and not isinstance(checks_raw, (str, bytes))
            else []
        )
        return cls(
            summary=AiVisibilitySummary.from_raw(value.get("summary", {})),
            checks=checks,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary.to_dict(),
            "checks": [item.to_dict() for item in self.checks],
        }


@dataclass(frozen=True)
class CrawlPayload:
    meta: list[list[str]]
    headers: list[list[str]]
    images: list[list[str]]
    links: list[list[str]]
    schema: StructuredDataPayload
    canonical: CanonicalInfo
    redirect: RedirectInfo
    robots: dict[str, list[tuple[str, str]]]
    meta_robots: str
    hreflang: list[list[str]]
    ai_crawl: list[list[str]]
    serp: SerpPreview
    serp_audit: SerpAudit
    keywords: list[KeywordEntry]
    content_quality: ContentQuality = field(default_factory=ContentQuality.empty)
    ai_visibility: AiVisibilityPayload = field(default_factory=AiVisibilityPayload.empty)
    performance: PerformanceMetrics = field(default_factory=PerformanceMetrics.empty)
    social: SocialPayload = field(default_factory=SocialPayload.empty)
    # v2.0 V6: {rule_name: extracted_value} from user-defined extraction rules.
    custom_extraction: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, data: Mapping[str, Any]) -> CrawlPayload:
        _require_crawl_keys(data)

        return cls(
            meta=_rows_section(data, "meta"),
            headers=_rows_section(data, "headers"),
            images=normalize_image_rows(_rows_section(data, "images")),
            links=_rows_section(data, "links"),
            schema=StructuredDataPayload.from_raw(data["schema"]),
            canonical=CanonicalInfo.from_raw(_mapping_section(data, "canonical")),
            redirect=RedirectInfo.from_raw(_mapping_section(data, "redirect")),
            robots=_normalize_robots(data["robots"]),
            meta_robots=str(data.get("meta_robots", "")),
            hreflang=_rows_section(data, "hreflang"),
            ai_crawl=_rows_section(data, "ai_crawl"),
            serp=SerpPreview.from_raw(_mapping_section(data, "serp")),
            serp_audit=SerpAudit.from_raw(_mapping_section(data, "serp_audit")),
            keywords=_keyword_entries(data.get("keywords", [])),
            content_quality=ContentQuality.from_raw(data.get("content_quality", {})),
            ai_visibility=AiVisibilityPayload.from_raw(data.get("ai_visibility", {})),
            performance=PerformanceMetrics.from_raw(data.get("performance", {})),
            social=SocialPayload.from_raw(_optional_mapping_section(data, "social")),
            custom_extraction=_string_map(data.get("custom_extraction")),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "meta": [row[:] for row in self.meta],
            "headers": [row[:] for row in self.headers],
            "images": [row[:] for row in self.images],
            "links": [row[:] for row in self.links],
            "schema": self.schema.to_mapping(),
            "canonical": self.canonical.to_dict(),
            "redirect": self.redirect.to_dict(),
            "robots": {agent: [list(pair) for pair in directives] for agent, directives in self.robots.items()},
            "meta_robots": self.meta_robots,
            "hreflang": [row[:] for row in self.hreflang],
            "ai_crawl": [row[:] for row in self.ai_crawl],
            "serp": self.serp.to_dict(),
            "serp_audit": self.serp_audit.to_dict(),
            "keywords": [entry.to_dict() for entry in self.keywords],
            "content_quality": self.content_quality.to_dict(),
            "ai_visibility": self.ai_visibility.to_dict(),
            "performance": self.performance.to_dict(),
            "social": self.social.to_dict(),
            "custom_extraction": dict(self.custom_extraction),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_mapping()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_mapping().get(key, default)


__all__ = [
    "CanonicalInfo",
    "RedirectInfo",
    "SerpPreview",
    "SerpAudit",
    "StructuredDataEligibility",
    "StructuredDataPayload",
    "StructuredDataSummary",
    "KeywordEntry",
    "ContentQuality",
    "AiVisibilityCheck",
    "AiVisibilitySummary",
    "AiVisibilityPayload",
    "PerformanceOffender",
    "PerformanceIssue",
    "PerformanceOpportunity",
    "PerformanceResourceBreakdown",
    "PerformanceSummary",
    "PerformanceScripts",
    "PerformanceMetrics",
    "CrawlPayload",
]
