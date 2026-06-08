"""Sitemap-level GEO Score aggregation (v1.1 N4b).

Load a sitemap.xml, audit every URL in parallel, present the GEO
Score distribution as a single report. Screaming Frog does sitemap
crawls but doesn't expose a GEO Score histogram; this is the
competitive moat per docs/geo_roadmap.md v1.1 §0.

Zero new runtime deps — uses the existing aiohttp + the existing
``analyse()`` pipeline.
"""

from __future__ import annotations

import asyncio
import statistics
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

import aiohttp
from aiohttp import ClientTimeout

from .crawl_options import CrawlOptions
from .crawl_types import CrawlPayload

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_DEFAULT_CONCURRENCY = 8
_DEFAULT_FETCH_TIMEOUT = 15


@dataclass(frozen=True)
class UrlScore:
    url: str
    score: int
    verdict: str
    top_warning: str
    error: str = ""


@dataclass(frozen=True)
class SitemapGeoReport:
    sitemap_url: str
    count: int
    measured_count: int
    p50_score: float
    p75_score: float
    p95_score: float
    min_score: int
    max_score: int
    per_area_means: dict[str, float] = field(default_factory=dict)
    worst_urls: tuple[UrlScore, ...] = ()
    error_urls: tuple[UrlScore, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "sitemap_url": self.sitemap_url,
            "count": self.count,
            "measured_count": self.measured_count,
            "p50_score": self.p50_score,
            "p75_score": self.p75_score,
            "p95_score": self.p95_score,
            "min_score": self.min_score,
            "max_score": self.max_score,
            "per_area_means": dict(self.per_area_means),
            "worst_urls": [
                {
                    "url": u.url,
                    "score": u.score,
                    "verdict": u.verdict,
                    "top_warning": u.top_warning,
                }
                for u in self.worst_urls
            ],
            "error_urls": [{"url": u.url, "error": u.error} for u in self.error_urls],
        }


def parse_sitemap(xml_text: str) -> list[str]:
    """Extract URL locations from sitemap.xml (or sitemap index).

    Handles the common case: ``<urlset>/<url>/<loc>`` and the
    sitemap-index case ``<sitemapindex>/<sitemap>/<loc>``. For the
    index, callers must recursively re-fetch each child sitemap.

    Returns ``[]`` on malformed XML; never raises.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    urls: list[str] = []
    for url_elem in root.findall(f"{_SITEMAP_NS}url"):
        loc = url_elem.find(f"{_SITEMAP_NS}loc")
        if loc is not None and loc.text:
            urls.append(loc.text.strip())
    # Index path
    for sm_elem in root.findall(f"{_SITEMAP_NS}sitemap"):
        loc = sm_elem.find(f"{_SITEMAP_NS}loc")
        if loc is not None and loc.text:
            urls.append(loc.text.strip())
    return urls


async def fetch_sitemap(
    sitemap_url: str,
    session: aiohttp.ClientSession | None = None,
    timeout_seconds: int = _DEFAULT_FETCH_TIMEOUT,
) -> str:
    """Download the sitemap XML body. Returns empty string on failure."""
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    try:
        async with session.get(sitemap_url, timeout=ClientTimeout(total=timeout_seconds)) as response:
            if response.status >= 400:
                return ""
            return await response.text(errors="ignore")
    except Exception:
        return ""
    finally:
        if own_session and session is not None:
            await session.close()


def _url_score_from_payload(url: str, payload: CrawlPayload) -> UrlScore:
    summary = payload.ai_visibility.summary
    top_warning = ""
    for check in payload.ai_visibility.checks:
        if check.status == "warning":
            top_warning = check.check
            break
    return UrlScore(
        url=url,
        score=summary.score,
        verdict=summary.verdict,
        top_warning=top_warning,
    )


def _per_area_means(scores: list[UrlScore], payloads: dict[str, CrawlPayload]) -> dict[str, float]:
    """Compute the mean count of warning+critical checks per area."""
    if not scores:
        return {}
    sums: dict[str, list[int]] = {}
    for entry in scores:
        payload = payloads.get(entry.url)
        if payload is None:
            continue
        per_area_counts: dict[str, int] = {}
        for check in payload.ai_visibility.checks:
            if check.status in {"warning", "critical"}:
                per_area_counts[check.area] = per_area_counts.get(check.area, 0) + 1
        for area, count in per_area_counts.items():
            sums.setdefault(area, []).append(count)
    return {area: round(sum(counts) / len(counts), 2) for area, counts in sums.items()}


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values_sorted = sorted(values)
    idx = max(0, min(len(values_sorted) - 1, int(round(q * (len(values_sorted) - 1)))))
    return float(values_sorted[idx])


def _build_report(
    sitemap_url: str,
    scores: list[UrlScore],
    payloads: dict[str, CrawlPayload],
    errors: list[UrlScore],
) -> SitemapGeoReport:
    measured = [s for s in scores if not s.error]
    score_values = [float(s.score) for s in measured]
    if not score_values:
        return SitemapGeoReport(
            sitemap_url=sitemap_url,
            count=len(scores) + len(errors),
            measured_count=0,
            p50_score=0.0,
            p75_score=0.0,
            p95_score=0.0,
            min_score=0,
            max_score=0,
            per_area_means={},
            worst_urls=(),
            error_urls=tuple(errors),
        )
    sorted_by_score = sorted(measured, key=lambda u: u.score)
    return SitemapGeoReport(
        sitemap_url=sitemap_url,
        count=len(scores) + len(errors),
        measured_count=len(measured),
        p50_score=round(statistics.median(score_values), 1),
        p75_score=round(_percentile(score_values, 0.75), 1),
        p95_score=round(_percentile(score_values, 0.95), 1),
        min_score=int(min(score_values)),
        max_score=int(max(score_values)),
        per_area_means=_per_area_means(measured, payloads),
        worst_urls=tuple(sorted_by_score[:10]),
        error_urls=tuple(errors),
    )


async def aggregate_sitemap(
    sitemap_url: str,
    analyser: Callable[[str], Awaitable[CrawlPayload]],
    options: CrawlOptions | None = None,
    max_concurrency: int = _DEFAULT_CONCURRENCY,
    session: aiohttp.ClientSession | None = None,
) -> SitemapGeoReport:
    """Aggregate GEO Score across every URL in a sitemap.

    ``analyser`` is injected so tests can stub the slow ``analyse``
    function. In production, callers pass ``seo_crawler.analyse``
    directly.
    """
    _ = options  # accepted for forward-compat; analyser already carries CrawlOptions
    xml_text = await fetch_sitemap(sitemap_url, session=session)
    urls = parse_sitemap(xml_text)
    if not urls:
        return SitemapGeoReport(
            sitemap_url=sitemap_url,
            count=0,
            measured_count=0,
            p50_score=0.0,
            p75_score=0.0,
            p95_score=0.0,
            min_score=0,
            max_score=0,
        )

    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _audit_one(url: str) -> tuple[str, CrawlPayload | None, str]:
        async with semaphore:
            try:
                payload = await analyser(url)
                return url, payload, ""
            except Exception as exc:
                return url, None, f"{type(exc).__name__}: {exc}"

    results = await asyncio.gather(*[_audit_one(url) for url in urls])
    scores: list[UrlScore] = []
    payloads: dict[str, CrawlPayload] = {}
    errors: list[UrlScore] = []
    for url, payload, err in results:
        if payload is None:
            errors.append(UrlScore(url=url, score=0, verdict="", top_warning="", error=err))
            continue
        score = _url_score_from_payload(url, payload)
        scores.append(score)
        payloads[url] = payload
    return _build_report(sitemap_url, scores, payloads, errors)


__all__ = [
    "SitemapGeoReport",
    "UrlScore",
    "aggregate_sitemap",
    "fetch_sitemap",
    "parse_sitemap",
]
