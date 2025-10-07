from __future__ import annotations

from dataclasses import dataclass
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


def _normalize_schema(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if _is_iterable_of_iterables(value):
        return list(value)
    return []


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
    schema: List[Any]
    canonical: CanonicalInfo
    redirect: RedirectInfo
    robots: Dict[str, List[Tuple[str, str]]]
    meta_robots: str
    hreflang: List[List[str]]
    ai_crawl: List[List[str]]
    serp: SerpPreview
    serp_audit: SerpAudit
    keywords: List[List[str]]

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
            schema=_normalize_schema(data["schema"]),
            canonical=CanonicalInfo.from_raw(canonical_raw),
            redirect=RedirectInfo.from_raw(redirect_raw),
            robots=_normalize_robots(data["robots"]),
            meta_robots=str(data.get("meta_robots", "")),
            hreflang=_normalize_rows(data["hreflang"], label="hreflang"),
            ai_crawl=_normalize_rows(data["ai_crawl"], label="ai_crawl"),
            serp=SerpPreview.from_raw(serp_raw),
            serp_audit=SerpAudit.from_raw(serp_audit_raw),
            keywords=_normalize_rows(data["keywords"], label="keywords"),
        )

    def to_mapping(self) -> Dict[str, Any]:
        return {
            "meta": [row[:] for row in self.meta],
            "headers": [row[:] for row in self.headers],
            "images": [row[:] for row in self.images],
            "links": [row[:] for row in self.links],
            "schema": list(self.schema),
            "canonical": self.canonical.to_dict(),
            "redirect": self.redirect.to_dict(),
            "robots": {agent: [list(pair) for pair in directives] for agent, directives in self.robots.items()},
            "meta_robots": self.meta_robots,
            "hreflang": [row[:] for row in self.hreflang],
            "ai_crawl": [row[:] for row in self.ai_crawl],
            "serp": self.serp.to_dict(),
            "serp_audit": self.serp_audit.to_dict(),
            "keywords": [row[:] for row in self.keywords],
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
    "CrawlPayload",
]
