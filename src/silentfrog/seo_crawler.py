"""
Async SEO crawler orchestrator: wires HTTP helpers, parsers, schema, performance,
and keyword extraction into the public `analyse` / `analyse_images` API.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, cast
from urllib.parse import urljoin

import aiohttp  # type: ignore[import]  # aiohttp stubs missing
from bs4 import BeautifulSoup, Comment

import silentfrog.crawl_http as crawl_http

from .ai_citations import fetch_ai_citations
from .ai_visibility import build_ai_visibility_payload
from .citation_advanced import extract_citation_advanced_signals
from .citation_readiness_content import extract_citation_content_signals
from .content_quality import extract_content_quality
from .crawl_http import (
    _BACKOFF_DELAY,
    _BACKOFF_STATUSES,
    _crawl_delay_for,
    _headers_from_options,
    _host_key,
    _image_info,
    _link_status,
    _parse_robots,
    _throttle_host,
    _trace_redirects,
)
from .crawl_options import CrawlOptions
from .crawl_types import CrawlPayload
from .crawler_utils import _hr_size
from .discovery_files import fetch_discovery_files
from .eeat_signals import extract_eeat_signals
from .http_client import fetch_page
from .keywords import _extract_keywords
from .parsers_meta import (
    _ai_crawl_matrix,
    _check_canonical,
    _extract_headers,
    _extract_hreflang,
    _extract_images,
    _extract_links,
    _extract_meta,
    _extract_social_cards,
    _make_serp_snippet,
    _meta_robots_value,
    _serp_preview,
    _title_audit,
    _update_link_statuses,
)
from .perf_metrics import _collect_performance_metrics
from .render_diff import compute_render_diff, render_with_playwright
from .schema_extractor import _extract_schema_all
from .seo_basics import extract_seo_basics
from .structure_signals import extract_structure_signals

# re-export host delay map for tests
_HOST_DELAYS = crawl_http._HOST_DELAYS


def _fetch_failure_message(url: str) -> str:
    base = f"Unable to fetch {url}. Check the URL, network connectivity, and HTTPS/TLS certificate setup."
    if sys.platform == "darwin":
        return (
            f"{base}\n\n"
            "macOS note: if you installed Python from python.org, run the matching "
            "'Install Certificates.command' and retry. Silentfrog's installer path is "
            "currently tested with Python 3.12 on macOS."
        )
    return base


async def _fetch_analysis_response(
    url: str,
    timeout: int,
    crawl_options: CrawlOptions,
) -> tuple[Any, dict[str, list[tuple[str, str]]] | None]:
    host_key = _host_key(url)
    robots_snapshot: dict[str, list[tuple[str, str]]] | None = None
    async with _throttle_host(host_key, crawl_options):
        if crawl_options.respect_crawl_delay:
            robots_snapshot = await _parse_robots(url, timeout=timeout)
        delay_seconds = _crawl_delay_for(crawl_options, host_key, robots_snapshot or {})
        active_delay = delay_seconds if (crawl_options.gentle_mode and crawl_options.respect_crawl_delay) else 0.0
        crawl_http._HOST_DELAYS[host_key] = active_delay  # adjust host delay used by link-status helper
        if active_delay > 0:
            await asyncio.sleep(active_delay)
        headers = _headers_from_options(crawl_options)
        attempts = 2 if crawl_options.gentle_mode else 1
        resp: Any = None
        for attempt in range(attempts):
            resp = await fetch_page(url, timeout, headers=headers)
            should_retry = resp.status in _BACKOFF_STATUSES and attempt < attempts - 1
            if not should_retry:
                break
            await asyncio.sleep(_BACKOFF_DELAY)
        assert resp is not None
        if resp.status == 0 and not resp.body:
            raise RuntimeError(_fetch_failure_message(url))
    return resp, robots_snapshot


def _extract_plain_text(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(["script", "style"]):
        tag.extract()
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()
    return soup.get_text(separator=" ", strip=True)


async def _resolve_link_rows(
    page_url: str,
    soup: BeautifulSoup,
    timeout: int,
    crawl_options: CrawlOptions,
) -> list[list[str]]:
    links_rows = _extract_links(page_url, soup)
    connector = aiohttp.TCPConnector(ssl=False)
    headers = _headers_from_options(crawl_options)
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        coroutines = [_link_status(session, row[0], timeout, crawl_options) for row in links_rows]
        statuses = await asyncio.gather(*coroutines, return_exceptions=True)
    _update_link_statuses(links_rows, statuses)
    return links_rows


def _canonical_section(
    canonical_url: str,
    is_self: bool,
    many_canon: bool,
    canon_status: str,
) -> dict[str, Any]:
    return {
        "target": canonical_url,
        "self": is_self,
        "multiple": many_canon,
        "status": canon_status,
    }


def _redirect_section(
    hops: list[str],
    final_status: str,
    hop_count: int,
    is_loop: bool,
) -> dict[str, Any]:
    return {
        "hops": hop_count,
        "chain": hops,
        "final_status": final_status,
        "loop": is_loop,
    }


async def _collect_analysis_sections(
    request_url: str,
    response: Any,
    soup: BeautifulSoup,
    timeout: int,
    crawl_options: CrawlOptions,
    robots_snapshot: dict[str, list[tuple[str, str]]] | None,
) -> dict[str, Any]:
    plain_text = _extract_plain_text(soup)
    meta_rows = _extract_meta(soup)
    header_rows = _extract_headers(soup)
    image_rows = _extract_images(response.url, soup)
    link_rows = await _resolve_link_rows(response.url, soup, timeout, crawl_options)

    canonical_url, is_self, many_canon, canon_status = await _check_canonical(
        response.url,
        soup,
        timeout=timeout,
        crawl_options=crawl_options,
    )
    hops, final_status, hop_count, is_loop = await _trace_redirects(
        request_url,
        timeout=timeout,
        options=crawl_options,
    )
    hreflang_rows = await _extract_hreflang(
        response.url,
        soup,
        timeout=timeout,
        crawl_options=crawl_options,
    )
    meta_robots = _meta_robots_value(response.headers, soup)
    robots_map = robots_snapshot or await _parse_robots(request_url, timeout=timeout)
    serp_snippet = await _make_serp_snippet(soup, response.url)
    discovery = await fetch_discovery_files(
        response.url,
        robots_map=robots_map,
        timeout=timeout,
        crawl_options=crawl_options,
    )

    return {
        "meta": meta_rows,
        "headers": header_rows,
        "images": image_rows,
        "links": link_rows,
        "canonical": _canonical_section(canonical_url, is_self, many_canon, canon_status),
        "redirect": _redirect_section(hops, final_status, hop_count, is_loop),
        "robots": robots_map,
        "meta_robots": meta_robots,
        "hreflang": hreflang_rows,
        "ai_crawl": _ai_crawl_matrix(robots_map, meta_robots, response.url),
        "serp": serp_snippet,
        "serp_audit": _title_audit(serp_snippet["title"], header_rows),
        "keywords": _extract_keywords(soup, plain_text),
        "content_quality": extract_content_quality(soup),
        "social": await _extract_social_cards(response.url, soup, timeout=timeout),
        "discovery": discovery.to_dict(),
    }


async def _collect_render_diff_and_vitals(
    response: Any, crawl_options: CrawlOptions
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Single Playwright launch produces both SSR parity AND CWV.

    Returns ``(render_payload, vitals_payload)``. Both are ``{}`` when
    the SSR parity flag is off so the rest of the analyse pipeline
    sees the same defaults M4 documented.
    """
    if not crawl_options.ssr_parity_check:
        return {}, {}
    rendered = await asyncio.to_thread(render_with_playwright, response.url, 15, True)
    if rendered is None:
        return (
            {"status": "not_measured", "reason": "Playwright not installed"},
            {"reason": "Playwright not installed"},
        )
    if rendered.error:
        return (
            {"status": "warning", "reason": f"Render failed: {rendered.error}"},
            {"reason": f"Render failed: {rendered.error}"},
        )
    diff = compute_render_diff(response.body, rendered.rendered_html)
    render_payload = {
        "status": diff.status,
        "missing_headings": list(diff.missing_headings),
        "missing_main_text_chars": diff.missing_main_text_chars,
        "missing_links": diff.missing_links,
        "reason": diff.reason,
    }
    vitals_payload = rendered.vitals_payload or {}
    return render_payload, vitals_payload


async def analyse(url: str, timeout: int = 10, options: CrawlOptions | None = None) -> CrawlPayload:
    crawl_options = options or CrawlOptions.default()
    response, robots_snapshot = await _fetch_analysis_response(url, timeout, crawl_options)
    soup = BeautifulSoup(response.body, "html.parser")
    structured_data = _extract_schema_all(response.body, response.url)
    performance_metrics = await _collect_performance_metrics(response, soup)
    section_payload = await _collect_analysis_sections(
        url,
        response,
        soup,
        timeout,
        crawl_options,
        robots_snapshot,
    )

    eeat = extract_eeat_signals(soup, structured_data, response.url)
    structure = extract_structure_signals(soup, response.url)
    quality_payload = section_payload.get("content_quality", {})
    language_hint = str(quality_payload.get("language", "")) if isinstance(quality_payload, dict) else ""
    citation_content = extract_citation_content_signals(soup, language_hint)
    plain_text = _extract_plain_text(soup)
    top_keyword_density = _top_keyword_density(section_payload.get("keywords"))
    citation_advanced = extract_citation_advanced_signals(
        soup,
        plain_text,
        language_hint,
        top_keyword_density=top_keyword_density,
    )
    seo_basics = extract_seo_basics(soup, response.url)
    render_payload, vitals_payload = await _collect_render_diff_and_vitals(response, crawl_options)
    crux_payload = await _collect_crux(response.url)
    ai_citations_payload = await _collect_ai_citations(response.url)
    raw_payload = {
        "schema": structured_data,
        "performance": performance_metrics,
        **section_payload,
        "eeat": eeat.to_dict(),
        "structure": structure.to_dict(),
        "citation_content": citation_content.to_dict(),
        "citation_advanced": citation_advanced.to_dict(),
        "seo_basics": seo_basics.to_dict(),
        "render": render_payload,
        "perf_vitals": vitals_payload,
        "perf_crux": crux_payload,
        "ai_citations": ai_citations_payload,
    }
    raw_payload["ai_visibility"] = build_ai_visibility_payload(raw_payload).to_dict()
    return CrawlPayload.from_raw(raw_payload)


async def _collect_ai_citations(url: str) -> dict[str, Any]:
    """Optional cross-engine citation tracking.

    Gated on ``SILENTFROG_AI_CITATIONS_ENABLE`` so a stock audit never
    leaves Silentfrog. When enabled, the Brave path additionally
    requires ``SILENTFROG_BRAVE_API_KEY``; Common Crawl runs without
    a key.
    """
    api_key = os.environ.get("SILENTFROG_BRAVE_API_KEY", "").strip() or None
    payload = await fetch_ai_citations(url, brave_api_key=api_key)
    return payload.to_dict()


def _top_keyword_density(keywords: Any) -> float | None:
    """Pull the highest density from the keyword pipeline output.

    The keyword extractor returns a list of dicts; each carries a
    ``density`` field. Returns ``None`` when no keywords are present.
    """
    if not isinstance(keywords, list):
        return None
    densities: list[float] = []
    for entry in keywords:
        if not isinstance(entry, dict):
            continue
        try:
            densities.append(float(entry.get("density", 0)))
        except (TypeError, ValueError):
            continue
    return max(densities) if densities else None


async def _collect_crux(url: str) -> dict[str, Any]:
    """Pull CrUX field data when the env knob enables it.

    Disabled by default so a stock single-page audit doesn't depend
    on PSI being reachable. Set ``SILENTFROG_PSI_ENABLE=1`` to fetch
    CrUX in the background; optional ``SILENTFROG_PSI_API_KEY`` lifts
    the anonymous rate limit.
    """
    import os

    if os.environ.get("SILENTFROG_PSI_ENABLE", "").strip().lower() not in {"1", "true", "yes"}:
        return {}
    api_key = os.environ.get("SILENTFROG_PSI_API_KEY", "").strip() or None
    try:
        from .perf_crux import fetch_crux
    except ImportError:
        return {"reason": "perf_crux module unavailable"}
    crux = await fetch_crux(url, api_key=api_key)
    return crux.to_dict()


async def analyse_images(base: str, rows: list[list[str]], timeout: int = 10) -> list[list[str]]:
    conn = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=conn) as sess:
        coros = [_image_info(sess, urljoin(base, row[0]), timeout) for row in rows]
        out = await asyncio.gather(*coros, return_exceptions=True)

    result: list[list[str]] = []
    for o in out:
        if isinstance(o, Exception):
            msg = str(o)
            url = msg.split(" ", 1)[0] if "http" in msg else "Errore"
            result.append([url, "", "", "", "-", ""])
        else:
            url, w, h, size_b, ctype, cache = cast(tuple[str, int, int, int, str, str], o)
            result.append([url, str(w), str(h), _hr_size(size_b), ctype, cache or ""])

    return result


__all__ = [
    "analyse",
    "analyse_images",
    "_extract_meta",
    "_extract_headers",
    "_extract_images",
    "_extract_links",
    "_serp_preview",
    "_make_serp_snippet",
    "_title_audit",
    "_extract_keywords",
    "_extract_schema_all",
    "_ai_crawl_matrix",
]
