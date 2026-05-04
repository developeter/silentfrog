from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse, urlunparse

from .crawl_options import CrawlOptions
from .crawl_types import CrawlPayload
from .image_diagnostics import DIAGNOSTIC_COL
from .indexability import build_indexability_rows

DEFAULT_SITE_CRAWL_LIMIT = 500
SITE_CRAWL_HEADERS = [
    "URL",
    "Status",
    "Final URL",
    "Title",
    "Description",
    "Canonical",
    "Indexability",
    "Hreflang",
    "Schema",
    "Image issues",
    "Performance",
    "AI Visibility",
    "Error",
]
_WAF_STATUSES = {"403", "429"}


def _split_lines(text: str) -> list[str]:
    parts = text.replace(",", "\n").splitlines()
    return [part.strip() for part in parts if part.strip()]


def normalize_site_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()
    normalized = parsed._replace(fragment="")
    path = normalized.path or "/"
    return urlunparse(normalized._replace(path=path))


@dataclass(frozen=True)
class SiteCrawlConfig:
    base_url: str
    sitemap_url: str
    include_patterns: tuple[str, ...]
    exclude_patterns: tuple[str, ...]
    url_list: tuple[str, ...]
    limit: int
    crawl_options: CrawlOptions
    same_host_only: bool = True

    @classmethod
    def from_text(
        cls,
        *,
        base_url: str,
        sitemap_url: str = "",
        include_text: str = "",
        exclude_text: str = "",
        url_list_text: str = "",
        limit: int = DEFAULT_SITE_CRAWL_LIMIT,
        crawl_options: CrawlOptions | None = None,
    ) -> "SiteCrawlConfig":
        return cls(
            base_url=normalize_site_url(base_url),
            sitemap_url=normalize_site_url(sitemap_url) if sitemap_url.strip() else "",
            include_patterns=tuple(_split_lines(include_text)),
            exclude_patterns=tuple(_split_lines(exclude_text)),
            url_list=tuple(normalize_site_url(url) for url in _split_lines(url_list_text)),
            limit=max(1, min(10000, int(limit))),
            crawl_options=crawl_options or CrawlOptions.from_ui(gentle_mode=True, max_parallel=2),
        )

    @property
    def base_host(self) -> str:
        return urlparse(self.base_url).netloc.lower()


@dataclass(frozen=True)
class SiteCrawlResult:
    url: str
    status: str
    final_url: str
    title: str
    description_state: str
    canonical_state: str
    indexability: str
    hreflang_count: int
    schema_count: int
    image_issue_count: int
    performance_verdict: str
    ai_visibility_verdict: str
    error: str = ""
    payload: CrawlPayload | None = None

    @classmethod
    def from_payload(cls, url: str, payload: CrawlPayload) -> "SiteCrawlResult":
        return cls(
            url=url,
            status=_payload_status(payload),
            final_url=_payload_final_url(payload, url),
            title=_meta_value(payload, "title"),
            description_state=_description_state(_meta_value(payload, "description")),
            canonical_state=_canonical_state(payload),
            indexability=_indexability_verdict(payload),
            hreflang_count=len(payload.hreflang),
            schema_count=payload.schema.summary.total,
            image_issue_count=_image_issue_count(payload.images),
            performance_verdict=payload.performance.summary.verdict or "-",
            ai_visibility_verdict=payload.ai_visibility.summary.verdict or "-",
            payload=payload,
        )

    @classmethod
    def failed(cls, url: str, error: str) -> "SiteCrawlResult":
        return cls(
            url=url,
            status="error",
            final_url="",
            title="",
            description_state="",
            canonical_state="",
            indexability="Failed",
            hreflang_count=0,
            schema_count=0,
            image_issue_count=0,
            performance_verdict="-",
            ai_visibility_verdict="-",
            error=error,
        )

    @classmethod
    def skipped(cls, url: str, reason: str) -> "SiteCrawlResult":
        return cls(
            url=url,
            status="skipped",
            final_url="",
            title="",
            description_state="",
            canonical_state="",
            indexability="Skipped",
            hreflang_count=0,
            schema_count=0,
            image_issue_count=0,
            performance_verdict="-",
            ai_visibility_verdict="-",
            error=reason,
        )

    def row(self) -> list[object]:
        return [
            self.url,
            self.status,
            self.final_url,
            self.title,
            self.description_state,
            self.canonical_state,
            self.indexability,
            self.hreflang_count,
            self.schema_count,
            self.image_issue_count,
            self.performance_verdict,
            self.ai_visibility_verdict,
            self.error,
        ]

    @property
    def has_waf_signal(self) -> bool:
        return self.status in _WAF_STATUSES or any(code in self.error for code in _WAF_STATUSES)


@dataclass(frozen=True)
class SiteCrawlReport:
    results: tuple[SiteCrawlResult, ...]
    discovered_count: int
    crawled_count: int
    skipped_count: int
    failed_count: int
    warning: str = ""

    @classmethod
    def from_results(cls, results: Iterable[SiteCrawlResult], discovered_count: int) -> "SiteCrawlReport":
        rows = tuple(results)
        failed = sum(1 for result in rows if result.status == "error")
        skipped = sum(1 for result in rows if result.status == "skipped")
        warning = _waf_warning(rows)
        return cls(
            results=rows,
            discovered_count=discovered_count,
            crawled_count=len(rows) - skipped,
            skipped_count=skipped,
            failed_count=failed,
            warning=warning,
        )


def _payload_status(payload: CrawlPayload) -> str:
    status = str(payload.redirect.final_status or "").strip()
    return status or "0"


def _payload_final_url(payload: CrawlPayload, fallback: str) -> str:
    return payload.redirect.chain[-1] if payload.redirect.chain else fallback


def _meta_value(payload: CrawlPayload, name: str) -> str:
    expected = name.lower()
    for row in payload.meta:
        if len(row) > 1 and str(row[0]).strip().lower() == expected:
            return str(row[1]).strip()
    return ""


def _description_state(description: str) -> str:
    if not description:
        return "Missing"
    length = len(description)
    if length < 70:
        return "Short"
    if length > 160:
        return "Long"
    return "OK"


def _canonical_state(payload: CrawlPayload) -> str:
    if payload.canonical.multiple:
        return "Multiple"
    if not payload.canonical.target:
        return "Missing"
    return "Self" if payload.canonical.is_self else "Different"


def _indexability_verdict(payload: CrawlPayload) -> str:
    rows = build_indexability_rows(
        payload.redirect.to_dict(),
        payload.canonical.to_dict(),
        payload.meta_robots,
        payload.robots,
    )
    for row in rows:
        if len(row) > 1 and str(row[0]).strip().lower() == "overall verdict":
            return str(row[1]).strip()
    return "-"


def _image_issue_count(rows: Iterable[Iterable[object]]) -> int:
    count = 0
    for row in rows:
        values = list(row)
        diagnostic = values[DIAGNOSTIC_COL] if len(values) > DIAGNOSTIC_COL else ""
        if str(diagnostic).strip():
            count += 1
    return count


def _waf_warning(results: Iterable[SiteCrawlResult]) -> str:
    signals = sum(1 for result in results if result.has_waf_signal)
    if signals < 3:
        return ""
    return (
        "Several URLs returned 403/429-like responses. Slow the crawl, add approved "
        "headers/cookies, or ask the site owner to allowlist the crawler."
    )


__all__ = [
    "DEFAULT_SITE_CRAWL_LIMIT",
    "SITE_CRAWL_HEADERS",
    "SiteCrawlConfig",
    "SiteCrawlReport",
    "SiteCrawlResult",
    "normalize_site_url",
]
