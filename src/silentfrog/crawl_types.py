from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Tuple


def _is_iterable_of_iterables(value: Any) -> bool:
    return isinstance(value, Iterable) and not isinstance(value, (str, bytes))


def _normalize_rows(value: Any, *, label: str) -> List[List[str]]:
    if not _is_iterable_of_iterables(value):
        raise ValueError(f"{label} must be an iterable of rows")
    rows: List[List[str]] = []
    for row in value:
        if not _is_iterable_of_iterables(row):
            raise ValueError(f"{label} rows must be iterable")
        rows.append([str(cell) for cell in row])
    return rows


def _ensure_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    raise ValueError(f"{label} must be a mapping")


def _normalize_robots(value: Any) -> Dict[str, List[Tuple[str, str]]]:
    if not isinstance(value, Mapping):
        return {}
    normalized: Dict[str, List[Tuple[str, str]]] = {}
    for agent, directives in value.items():
        bucket: List[Tuple[str, str]] = []
        if _is_iterable_of_iterables(directives):
            for directive in directives:
                if isinstance(directive, (tuple, list)) and len(directive) >= 2:
                    bucket.append((str(directive[0]), str(directive[1])))
        normalized[str(agent)] = bucket
    return normalized


@dataclass(frozen=True)
class PerformanceMetrics:
    nav_ttfb_ms: float
    nav_total_ms: float
    transfer_size: int
    status: int
    resource_summary: Dict[str, Dict[str, int]]
    opportunities: List[str]
    top_offenders: List["PerformanceOffender"]
    scripts: "PerformanceScripts"
    opportunity_details: List["PerformanceOpportunity"]

    @classmethod
    def empty(cls) -> "PerformanceMetrics":
        return cls(
            nav_ttfb_ms=0.0,
            nav_total_ms=0.0,
            transfer_size=0,
            status=0,
            resource_summary={},
            opportunities=[],
            top_offenders=[],
            scripts=PerformanceScripts.empty(),
            opportunity_details=[],
        )

    @classmethod
    def from_raw(cls, value: Any) -> "PerformanceMetrics":
        if not isinstance(value, Mapping):
            return cls.empty()

        def _to_float(val: Any) -> float:
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0

        def _to_int(val: Any) -> int:
            try:
                if isinstance(val, bool):
                    return 0
                return int(val)
            except (TypeError, ValueError):
                return 0

        summary_raw = value.get('resource_summary')
        summary: Dict[str, Dict[str, int]] = {}
        if isinstance(summary_raw, Mapping):
            for key, item in summary_raw.items():
                if isinstance(item, Mapping):
                    summary[str(key)] = {
                        'count': _to_int(item.get('count', 0)),
                        'bytes': _to_int(item.get('bytes', 0)),
                    }
        opp_raw = value.get('opportunities', [])
        opp: List[str] = []
        if isinstance(opp_raw, Iterable) and not isinstance(opp_raw, (str, bytes)):
            for entry in opp_raw:
                text = str(entry).strip()
                if text:
                    opp.append(text)

        offender_raw = value.get("top_offenders", [])
        offenders: List[PerformanceOffender] = []
        if isinstance(offender_raw, Iterable):
            for item in offender_raw:
                if isinstance(item, Mapping):
                    offenders.append(PerformanceOffender.from_raw(item))

        scripts = PerformanceScripts.from_raw(value.get("scripts"))

        opportunity_details_raw = value.get("opportunity_details", [])
        opportunity_details: List[PerformanceOpportunity] = []
        if isinstance(opportunity_details_raw, Iterable):
            for item in opportunity_details_raw:
                if isinstance(item, Mapping):
                    opportunity_details.append(PerformanceOpportunity.from_raw(item))

        return cls(
            nav_ttfb_ms=_to_float(value.get('nav_ttfb_ms', 0.0)),
            nav_total_ms=_to_float(value.get('nav_total_ms', 0.0)),
            transfer_size=_to_int(value.get('transfer_size', 0)),
            status=_to_int(value.get('status', 0)),
            resource_summary=summary,
            opportunities=opp,
            top_offenders=offenders,
            scripts=scripts,
            opportunity_details=opportunity_details,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'nav_ttfb_ms': self.nav_ttfb_ms,
            'nav_total_ms': self.nav_total_ms,
            'transfer_size': self.transfer_size,
            'status': self.status,
            'resource_summary': {k: dict(v) for k, v in self.resource_summary.items()},
            'opportunities': list(self.opportunities),
            'top_offenders': [entry.to_dict() for entry in self.top_offenders],
            'scripts': self.scripts.to_dict(),
            'opportunity_details': [item.to_dict() for item in self.opportunity_details],
        }


@dataclass(frozen=True)
class PerformanceScripts:
    blocking_count: int
    blocking_bytes: int
    async_count: int
    async_bytes: int

    @classmethod
    def empty(cls) -> "PerformanceScripts":
        return cls(0, 0, 0, 0)

    @classmethod
    def from_raw(cls, value: Any) -> "PerformanceScripts":
        if not isinstance(value, Mapping):
            return cls.empty()

        def _part(key: str) -> Dict[str, int]:
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

    def to_dict(self) -> Dict[str, Dict[str, int]]:
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
    def from_raw(cls, value: Mapping[str, Any]) -> "PerformanceOffender":
        resource_type = str(value.get("type", "")).strip()
        url = str(value.get("url", "")).strip()
        try:
            size = int(value.get("bytes", 0))
        except (TypeError, ValueError):
            size = 0
        blocking = bool(value.get("blocking", False))
        return cls(resource_type=resource_type, url=url, bytes=max(size, 0), blocking=blocking)

    def to_dict(self) -> Dict[str, Any]:
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
    def from_raw(cls, value: Mapping[str, Any]) -> "PerformanceOpportunity":
        message = str(value.get("message", "")).strip()
        severity = str(value.get("severity", "")).strip().lower()
        return cls(message=message, severity=severity or "info")

    def to_dict(self) -> Dict[str, str]:
        return {"message": self.message, "severity": self.severity}


@dataclass(frozen=True)
class StructuredDataSummary:
    total: int
    by_syntax: Dict[str, int]
    by_type: Dict[str, int]
    errors: List[str]

    @staticmethod
    def _as_int_dict(value: Any) -> Dict[str, int]:
        if not isinstance(value, Mapping):
            return {}
        result: Dict[str, int] = {}
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
        errors: List[str] = []
        if isinstance(errors_raw, Iterable) and not isinstance(errors_raw, (str, bytes)):
            for item in errors_raw:
                text = str(item).strip()
                if text:
                    errors.append(text)
        return cls(total=total, by_syntax=by_syntax, by_type=by_type, errors=errors)

    def with_errors(self, extra: Iterable[str]) -> StructuredDataSummary:
        merged: List[str] = list(self.errors)
        seen = {err for err in merged}
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "by_syntax": dict(self.by_syntax),
            "by_type": dict(self.by_type),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class StructuredDataPayload:
    blocks: List[Any]
    summary: StructuredDataSummary
    fallback_raw: List[str]

    @classmethod
    def empty(cls) -> StructuredDataPayload:
        return cls(blocks=[], summary=StructuredDataSummary.empty(), fallback_raw=[])

    @staticmethod
    def _coerce_blocks(value: Any) -> List[Any]:
        if isinstance(value, list):
            return list(value)
        if _is_iterable_of_iterables(value):
            return list(value)
        return []

    @staticmethod
    def _coerce_fallback(raw: Any) -> List[str]:
        if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
            return []
        fallback: List[str] = []
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
            extra_errors_source = value.get("issues", [])
            extra_errors: Iterable[str] = (
                extra_errors_source
                if isinstance(extra_errors_source, Iterable) and not isinstance(extra_errors_source, (str, bytes))
                else []
            )
            summary = summary.with_errors(extra_errors)
            fallback_raw = cls._coerce_fallback(value.get("fallback_raw"))
            return cls(blocks=blocks, summary=summary, fallback_raw=fallback_raw)
        if isinstance(value, list):
            summary_raw: Mapping[str, Any] | None = None
            extra_errors: List[str] = []
            blocks: List[Any] = []
            fallback: List[str] = []
            for item in value:
                if isinstance(item, Mapping) and "_schema_summary" in item and summary_raw is None:
                    raw = item.get("_schema_summary", {})
                    summary_raw = raw if isinstance(raw, Mapping) else {}
                    continue
                if isinstance(item, Mapping) and "_schema_issues" in item:
                    for issue in item.get("_schema_issues") or []:
                        text = str(issue).strip()
                        if text:
                            extra_errors.append(text)
                    continue
                if isinstance(item, list):
                    if item:
                        text = str(item[0]).strip()
                        if text:
                            fallback.append(text)
                    continue
                blocks.append(item)
            summary = StructuredDataSummary.from_raw(summary_raw or {})
            summary = summary.with_errors(extra_errors)
            return cls(blocks=blocks, summary=summary, fallback_raw=fallback)
        return cls.empty()

    def to_mapping(self) -> Dict[str, Any]:
        return {
            "blocks": list(self.blocks),
            "summary": self.summary.to_dict(),
            "fallback_raw": list(self.fallback_raw),
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

    def to_dict(self) -> Dict[str, Any]:
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "self": self.is_self,
            "multiple": self.multiple,
            "status": self.status,
        }


@dataclass(frozen=True)
class RedirectInfo:
    chain: List[str]
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

    def to_dict(self) -> Dict[str, Any]:
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

    def to_dict(self) -> Dict[str, Any]:
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

    def to_dict(self) -> Dict[str, Any]:
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
class CrawlPayload:
    meta: List[List[str]]
    headers: List[List[str]]
    images: List[List[str]]
    links: List[List[str]]
    schema: StructuredDataPayload
    canonical: CanonicalInfo
    redirect: RedirectInfo
    robots: Dict[str, List[Tuple[str, str]]]
    meta_robots: str
    hreflang: List[List[str]]
    ai_crawl: List[List[str]]
    serp: SerpPreview
    serp_audit: SerpAudit
    keywords: List[KeywordEntry]
    performance: PerformanceMetrics = field(default_factory=PerformanceMetrics.empty)

    @classmethod
    def from_raw(cls, data: Mapping[str, Any]) -> CrawlPayload:
        required = {
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
        missing = sorted(required - set(data.keys()))
        if missing:
            raise ValueError(f"Missing crawl keys: {', '.join(missing)}")

        canonical_raw = _ensure_mapping(data["canonical"], "canonical")
        redirect_raw = _ensure_mapping(data["redirect"], "redirect")
        serp_raw = _ensure_mapping(data["serp"], "serp")
        serp_audit_raw = _ensure_mapping(data["serp_audit"], "serp_audit")

        return cls(
            meta=_normalize_rows(data["meta"], label="meta"),
            headers=_normalize_rows(data["headers"], label="headers"),
            images=_normalize_rows(data["images"], label="images"),
            links=_normalize_rows(data["links"], label="links"),
            schema=StructuredDataPayload.from_raw(data["schema"]),
            canonical=CanonicalInfo.from_raw(canonical_raw),
            redirect=RedirectInfo.from_raw(redirect_raw),
            robots=_normalize_robots(data["robots"]),
            meta_robots=str(data.get("meta_robots", "")),
            hreflang=_normalize_rows(data["hreflang"], label="hreflang"),
            ai_crawl=_normalize_rows(data["ai_crawl"], label="ai_crawl"),
            serp=SerpPreview.from_raw(serp_raw),
            serp_audit=SerpAudit.from_raw(serp_audit_raw),
            keywords=[KeywordEntry.from_raw(item) for item in data.get("keywords", []) if isinstance(item, Mapping)],
            performance=PerformanceMetrics.from_raw(data.get("performance", {})),
        )

    def to_mapping(self) -> Dict[str, Any]:
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
            "performance": self.performance.to_dict(),
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
    "StructuredDataPayload",
    "StructuredDataSummary",
    "KeywordEntry",
    "PerformanceOffender",
    "PerformanceOpportunity",
    "PerformanceScripts",
    "PerformanceMetrics",
    "CrawlPayload",
]
