from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

from .crawl_mode import CrawlMode
from .crawl_options import CrawlOptions
from .crawl_types import CrawlPayload
from .image_diagnostics import DIAGNOSTIC_COL
from .indexability import build_indexability_rows

DEFAULT_SITE_CRAWL_LIMIT = 500
SITE_CRAWL_HEADERS = [
    "URL",
    "Status",
    "Redirect status",
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
SITE_CRAWL_TABLE_HEADERS = [
    "URL",
    "Status",
    "Indexability",
    "Title",
    "Meta desc",
    "Canonical",
    "H1",
    "Words",
    "Img issues",
    "Link issues",
    "Schema",
    "Hreflang",
    "Issues",
]
SITE_CRAWL_TABLE_TOOLTIPS = [
    "Requested URL from the crawl input or sitemap selection.",
    "HTTP status from the main page fetch.",
    "Final indexability verdict for this URL.",
    "Page title text.",
    "Meta description presence and length state.",
    "Canonical state: self, different, missing, or multiple.",
    "H1 state: missing, OK, or multiple.",
    "Detected body word count.",
    "Number of image rows with diagnostics.",
    "Number of links returning fetch, client, or server errors.",
    "Detected structured data block count.",
    "Detected hreflang alternate count.",
    "Most important issue signals for quick scanning.",
]
_WAF_STATUSES = {"403", "429"}
_LINK_STATUS_COL = 4


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
class SpiderConfig:
    """v2.0 V3 spider tuning, grouped so SiteCrawlConfig / from_text stay
    free of boolean-flag soup."""

    mode: CrawlMode = CrawlMode.HYBRID
    max_depth: int = 10
    max_urls: int = 100_000
    respect_robots: bool = True
    politeness_delay_ms: int = 200
    follow_subdomains: bool = False
    crawl_concurrency: int = 4


def _auto_mode(url_list: tuple[str, ...], sitemap_url: str) -> CrawlMode:
    """Pick a sensible default mode from the inputs the user supplied.

    An explicit URL list means "audit exactly these" (LIST). A sitemap
    means "crawl that sitemap" (SITEMAP). Pointing only at a base URL
    means "crawl the whole site" — HYBRID (sitemap ∪ spider).
    """
    if url_list:
        return CrawlMode.LIST
    if sitemap_url.strip():
        return CrawlMode.SITEMAP
    return CrawlMode.HYBRID


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
    spider: SpiderConfig = field(default_factory=SpiderConfig)

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
        spider: SpiderConfig | None = None,
    ) -> SiteCrawlConfig:
        url_list = tuple(normalize_site_url(url) for url in _split_lines(url_list_text))
        sitemap_clean = normalize_site_url(sitemap_url) if sitemap_url.strip() else ""
        resolved_spider = spider or SpiderConfig(mode=_auto_mode(url_list, sitemap_clean))
        return cls(
            base_url=normalize_site_url(base_url),
            sitemap_url=sitemap_clean,
            include_patterns=tuple(_split_lines(include_text)),
            exclude_patterns=tuple(_split_lines(exclude_text)),
            url_list=url_list,
            # v2.0 V3: store-backed crawls scale to ~1M URLs.
            limit=max(1, min(1_000_000, int(limit))),
            crawl_options=crawl_options or CrawlOptions.from_ui(gentle_mode=True, max_parallel=2),
            spider=resolved_spider,
        )

    @property
    def base_host(self) -> str:
        return urlparse(self.base_url).netloc.lower()


@dataclass(frozen=True)
class SiteCrawlResult:
    url: str
    status: str
    redirect_status: str
    final_url: str
    title: str
    description_state: str
    canonical_state: str
    indexability: str
    hreflang_count: int
    schema_count: int
    image_issue_count: int
    h1_state: str
    word_count: int
    link_issue_count: int
    performance_verdict: str
    ai_visibility_verdict: str
    # v2.0 V8: numeric GEO Score kept as a lightweight field so crawl diffs
    # can compare scores even after the payload is stripped (V3.2).
    geo_score: int = 0
    error: str = ""
    payload: CrawlPayload | None = None

    @classmethod
    def from_payload(cls, url: str, payload: CrawlPayload) -> SiteCrawlResult:
        return cls(
            url=url,
            status=_payload_status(payload),
            redirect_status=_payload_redirect_status(payload),
            final_url=_payload_final_url(payload, url),
            title=_meta_value(payload, "title"),
            description_state=_description_state(_meta_value(payload, "description")),
            canonical_state=_canonical_state(payload),
            indexability=_indexability_verdict(payload),
            hreflang_count=len(payload.hreflang),
            schema_count=payload.schema.summary.total,
            image_issue_count=_image_issue_count(payload.images),
            h1_state=_h1_state(payload),
            word_count=max(0, payload.content_quality.word_count),
            link_issue_count=_link_issue_count(payload.links),
            performance_verdict=payload.performance.summary.verdict or "-",
            ai_visibility_verdict=payload.ai_visibility.summary.verdict or "-",
            geo_score=payload.ai_visibility.summary.score,
            payload=payload,
        )

    @classmethod
    def failed(cls, url: str, error: str) -> SiteCrawlResult:
        return cls(
            url=url,
            status="error",
            redirect_status="",
            final_url="",
            title="",
            description_state="",
            canonical_state="",
            indexability="Failed",
            hreflang_count=0,
            schema_count=0,
            image_issue_count=0,
            h1_state="",
            word_count=0,
            link_issue_count=0,
            performance_verdict="-",
            ai_visibility_verdict="-",
            error=error,
        )

    @classmethod
    def skipped(cls, url: str, reason: str) -> SiteCrawlResult:
        return cls(
            url=url,
            status="skipped",
            redirect_status="",
            final_url="",
            title="",
            description_state="",
            canonical_state="",
            indexability="Skipped",
            hreflang_count=0,
            schema_count=0,
            image_issue_count=0,
            h1_state="",
            word_count=0,
            link_issue_count=0,
            performance_verdict="-",
            ai_visibility_verdict="-",
            error=reason,
        )

    def row(self) -> list[object]:
        return [
            self.url,
            self.status,
            self.redirect_status,
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

    def table_row(self) -> list[object]:
        return [
            self.url,
            self.status,
            self.indexability,
            self.title,
            self.description_state,
            self.canonical_state,
            self.h1_state,
            self.word_count,
            self.image_issue_count,
            self.link_issue_count,
            self.schema_count,
            self.hreflang_count,
            self.issue_summary(),
        ]

    def issue_summary(self) -> str:
        if self.error:
            return self.error
        issues = _issue_summary_items(self)
        return "; ".join(issues[:3]) if issues else "-"

    @property
    def has_waf_signal(self) -> bool:
        statuses = {self.status, self.redirect_status}
        return bool(statuses & _WAF_STATUSES) or any(code in self.error for code in _WAF_STATUSES)


@dataclass(frozen=True)
class SiteCrawlReport:
    results: tuple[SiteCrawlResult, ...]
    discovered_count: int
    crawled_count: int
    skipped_count: int
    failed_count: int
    warning: str = ""
    # v2.0 V3.2: the store run this crawl streamed to, so the GUI can
    # load full payloads on demand for results whose in-memory payload
    # was stripped to bound RAM at ~1M URLs.
    run_id: str = ""

    @classmethod
    def from_results(
        cls,
        results: Iterable[SiteCrawlResult],
        discovered_count: int,
        run_id: str = "",
    ) -> SiteCrawlReport:
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
            run_id=run_id,
        )


def _payload_status(payload: CrawlPayload) -> str:
    status = str(payload.performance.status or "").strip()
    return status or _payload_redirect_status(payload) or "0"


def _payload_redirect_status(payload: CrawlPayload) -> str:
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


def _h1_state(payload: CrawlPayload) -> str:
    h1_count = sum(1 for row in payload.headers if row and str(row[0]).strip().lower() == "h1")
    if h1_count == 0:
        return "Missing"
    if h1_count == 1:
        return "OK"
    return f"Multiple ({h1_count})"


def _link_issue_count(rows: Iterable[Iterable[object]]) -> int:
    count = 0
    for row in rows:
        values = list(row)
        if len(values) <= _LINK_STATUS_COL:
            continue
        status = _status_code(values[_LINK_STATUS_COL])
        if status == 0 or status >= 400:
            count += 1
    return count


def _status_code(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _issue_summary_items(result: SiteCrawlResult) -> list[str]:
    issues: list[str] = []
    if result.status in {"error", "skipped"}:
        issues.append(result.status.title())
    if result.indexability not in {"", "-", "Indexable"}:
        issues.append(result.indexability)
    if not result.title:
        issues.append("Missing title")
    if result.description_state not in {"", "OK"}:
        issues.append(f"Meta desc: {result.description_state}")
    if result.canonical_state not in {"", "Self"}:
        issues.append(f"Canonical: {result.canonical_state}")
    if result.h1_state not in {"", "OK"}:
        issues.append(f"H1: {result.h1_state}")
    if result.image_issue_count:
        issues.append(f"{result.image_issue_count} image issues")
    if result.link_issue_count:
        issues.append(f"{result.link_issue_count} link issues")
    return issues


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
    "SITE_CRAWL_TABLE_HEADERS",
    "SITE_CRAWL_TABLE_TOOLTIPS",
    "SiteCrawlConfig",
    "SiteCrawlReport",
    "SiteCrawlResult",
    "SpiderConfig",
    "normalize_site_url",
]
