from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse
from xml.etree import ElementTree

from .crawl_http import _headers_from_options
from .http_client import fetch_page
from .seo_crawler import analyse
from .site_crawl_types import (
    SiteCrawlConfig,
    SiteCrawlReport,
    SiteCrawlResult,
    normalize_site_url,
)

ProgressCallback = Callable[[dict[str, Any]], None]
_MAX_SITEMAP_DEPTH = 3
_COMMON_SITEMAP_PATHS = ("sitemap.xml", "sitemap_index.xml", "sitemap-index.xml")


@dataclass(frozen=True)
class _SitemapItems:
    urls: tuple[str, ...]
    sitemaps: tuple[str, ...]


async def resolve_site_urls(config: SiteCrawlConfig, timeout: int = 15) -> list[str]:
    candidates: list[str] = []
    candidates.extend(config.url_list)
    if config.sitemap_url:
        candidates.extend(await _sitemap_urls(config.sitemap_url, config, timeout))
        return _filter_urls(candidates, config)
    if candidates:
        return _filter_urls(candidates, config)
    sitemap_candidates = await _auto_sitemap_urls(config, timeout)
    filtered = _filter_urls(sitemap_candidates, config)
    if filtered:
        return filtered
    return _filter_urls([config.base_url], config)


async def crawl_site(
    config: SiteCrawlConfig,
    timeout: int = 15,
    on_event: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> SiteCrawlReport:
    urls = await resolve_site_urls(config, timeout)
    _emit(on_event, "discovered", discovered=len(urls), total=len(urls))
    results: list[SiteCrawlResult] = []
    queue: asyncio.Queue[tuple[int, str] | None] = asyncio.Queue()
    for item in enumerate(urls):
        queue.put_nowait(item)
    worker_count = max(1, min(4, config.crawl_options.max_concurrent_per_host))
    for _ in range(worker_count):
        queue.put_nowait(None)
    await asyncio.gather(
        *[
            _crawl_worker(queue, config, timeout, results, on_event, cancel_event)
            for _ in range(worker_count)
        ]
    )
    ordered = sorted(results, key=lambda result: urls.index(result.url) if result.url in urls else len(urls))
    return SiteCrawlReport.from_results(ordered, discovered_count=len(urls))


async def _crawl_worker(
    queue: asyncio.Queue[tuple[int, str] | None],
    config: SiteCrawlConfig,
    timeout: int,
    results: list[SiteCrawlResult],
    on_event: ProgressCallback | None,
    cancel_event: threading.Event | None,
) -> None:
    while True:
        item = await queue.get()
        if item is None:
            return
        _, url = item
        result = await _crawl_one(url, config, timeout, on_event, cancel_event)
        results.append(result)
        _emit(on_event, "row", result=result, completed=len(results))


async def _crawl_one(
    url: str,
    config: SiteCrawlConfig,
    timeout: int,
    on_event: ProgressCallback | None,
    cancel_event: threading.Event | None,
) -> SiteCrawlResult:
    if cancel_event and cancel_event.is_set():
        return SiteCrawlResult.skipped(url, "Cancelled")
    _emit(on_event, "running", url=url)
    try:
        payload = await analyse(url, timeout=timeout, options=config.crawl_options)
    except Exception as exc:  # noqa: BLE001
        return SiteCrawlResult.failed(url, str(exc))
    return SiteCrawlResult.from_payload(url, payload)


async def _sitemap_urls(url: str, config: SiteCrawlConfig, timeout: int) -> list[str]:
    seen: set[str] = set()
    pages: list[str] = []
    pending: list[tuple[str, int]] = [(url, 0)]
    while pending:
        current, depth = pending.pop(0)
        if current in seen or depth > _MAX_SITEMAP_DEPTH:
            continue
        seen.add(current)
        items = await _fetch_sitemap(current, config, timeout)
        pages.extend(items.urls)
        pending.extend((child, depth + 1) for child in items.sitemaps)
    return pages


async def _auto_sitemap_urls(config: SiteCrawlConfig, timeout: int) -> list[str]:
    page_urls: list[str] = []
    for sitemap_url in await _discover_sitemap_urls(config, timeout):
        page_urls.extend(await _sitemap_urls(sitemap_url, config, timeout))
    return page_urls


async def _discover_sitemap_urls(config: SiteCrawlConfig, timeout: int) -> list[str]:
    candidates = await _robots_sitemap_urls(config, timeout)
    candidates.extend(_common_sitemap_urls(config))
    return list(dict.fromkeys(url for url in candidates if _valid_http_url(url)))


async def _robots_sitemap_urls(config: SiteCrawlConfig, timeout: int) -> list[str]:
    response = await fetch_page(_site_url(config, "robots.txt"), timeout=timeout, headers=_headers_from_options(config.crawl_options))
    if response.status >= 400 or not response.body:
        return []
    return _robots_sitemap_directives(response.body)


def _robots_sitemap_directives(text: str) -> list[str]:
    urls: list[str] = []
    for line in text.splitlines():
        sitemap_url = _normalize_sitemap_directive(line)
        if sitemap_url:
            urls.append(sitemap_url)
    return urls


def _common_sitemap_urls(config: SiteCrawlConfig) -> list[str]:
    return [_site_url(config, path) for path in _COMMON_SITEMAP_PATHS]


def _site_url(config: SiteCrawlConfig, path: str) -> str:
    parsed = urlparse(config.base_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/{path.lstrip('/')}"


def _normalize_sitemap_directive(line: str) -> str:
    value = line.split("#", 1)[0].strip()
    if not value.lower().startswith("sitemap:"):
        return ""
    return normalize_site_url(value.split(":", 1)[1].strip())


async def _fetch_sitemap(url: str, config: SiteCrawlConfig, timeout: int) -> _SitemapItems:
    response = await fetch_page(url, timeout=timeout, headers=_headers_from_options(config.crawl_options))
    if response.status >= 400 or not response.body:
        return _SitemapItems(urls=(), sitemaps=())
    return _parse_sitemap(response.body)


def _parse_sitemap(xml_text: str) -> _SitemapItems:
    try:
        root = ElementTree.fromstring(xml_text.encode("utf-8"))
    except ElementTree.ParseError:
        return _SitemapItems(urls=(), sitemaps=())
    if _local_name(root.tag) == "sitemapindex":
        return _SitemapItems(urls=(), sitemaps=tuple(_direct_loc_children(root, "sitemap")))
    if _local_name(root.tag) == "urlset":
        return _SitemapItems(urls=tuple(_direct_loc_children(root, "url")), sitemaps=())
    return _SitemapItems(urls=(), sitemaps=())


def _direct_loc_children(root: ElementTree.Element, parent_name: str) -> list[str]:
    urls: list[str] = []
    for child in root:
        if _local_name(child.tag) != parent_name:
            continue
        loc = _child_text(child, "loc")
        if loc:
            urls.append(normalize_site_url(loc))
    return urls


def _child_text(element: ElementTree.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _filter_urls(urls: list[str], config: SiteCrawlConfig) -> list[str]:
    normalized = [normalize_site_url(url) for url in urls if _valid_http_url(url)]
    scoped = [url for url in normalized if _same_host_allowed(url, config)]
    included = [url for url in scoped if _included(url, config.include_patterns)]
    filtered = [url for url in included if not _excluded(url, config.exclude_patterns)]
    return list(dict.fromkeys(filtered))[: config.limit]


def _valid_http_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _same_host_allowed(url: str, config: SiteCrawlConfig) -> bool:
    if not config.same_host_only:
        return True
    return urlparse(url).netloc.lower() == config.base_host


def _included(url: str, patterns: tuple[str, ...]) -> bool:
    return not patterns or any(_pattern_matches(url, pattern) for pattern in patterns)


def _excluded(url: str, patterns: tuple[str, ...]) -> bool:
    return any(_pattern_matches(url, pattern) for pattern in patterns)


def _pattern_matches(url: str, pattern: str) -> bool:
    parsed = urlparse(url)
    text = pattern.strip()
    if text.startswith("/"):
        return parsed.path.startswith(text)
    return text.lower() in url.lower()


def _emit(callback: ProgressCallback | None, event: str, **payload: Any) -> None:
    if callback is None:
        return
    callback({"event": event, **payload})


__all__ = ["crawl_site", "resolve_site_urls"]
