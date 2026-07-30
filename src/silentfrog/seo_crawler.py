"""
Async SEO crawler orchestrator: wires HTTP helpers, parsers, schema, performance,
and keyword extraction into the public `analyse` / `analyse_images` API.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, cast
from urllib.parse import urljoin, urlparse

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
    _headers_from_options,
    _host_key,
    _image_info,
    _link_status,
    _parse_robots,
    _throttle_host,
    _trace_redirects,
)
from .crawl_options import CrawlOptions, ProfilePolicy
from .crawl_types import PAYLOAD_SCHEMA_VERSION, CrawlPayload
from .crawler_utils import _hr_size
from .custom_extraction import extract as extract_custom
from .discovery_files import fetch_discovery_files
from .eeat_signals import extract_eeat_signals
from .fetchers import FetchOptions, FetchRequest, FetchStrategy
from .http_client import HttpResponse
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
    extract_pseudo_links,
)
from .perf_metrics import _collect_performance_metrics
from .render_diff import compute_render_diff, render_with_playwright
from .robots_simulator import RobotsRules
from .schema_extractor import _extract_schema_all
from .seo_basics import extract_seo_basics
from .structure_signals import extract_structure_signals
from .tech_stack import detect_tech
from .transport import allow_private_network, insecure_tls, open_crawl_session

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
) -> tuple[Any, RobotsRules | None]:
    host_key = _host_key(url)
    robots_snapshot: RobotsRules | None = None
    async with _throttle_host(host_key, crawl_options):
        if crawl_options.respect_crawl_delay:
            robots_snapshot = await _parse_robots(url, timeout=timeout)
        delay_seconds = robots_snapshot.crawl_delay(crawl_options.user_agent) if robots_snapshot else 0.0
        active_delay = delay_seconds if (crawl_options.gentle_mode and crawl_options.respect_crawl_delay) else 0.0
        crawl_http._HOST_DELAYS[host_key] = active_delay  # adjust host delay used by link-status helper
        if active_delay > 0:
            await asyncio.sleep(active_delay)
        headers = _headers_from_options(crawl_options)
        attempts = 2 if crawl_options.gentle_mode else 1
        resp: Any = None
        for attempt in range(attempts):
            resp = await _strategy_fetch(url, timeout, headers, crawl_options)
            should_retry = resp.status in _BACKOFF_STATUSES and attempt < attempts - 1
            if not should_retry:
                break
            await asyncio.sleep(_BACKOFF_DELAY)
        assert resp is not None
        if resp.status == 0 and not resp.body:
            raise RuntimeError(_fetch_failure_message(url))
    return resp, robots_snapshot


def _stealth_enabled(crawl_options: CrawlOptions) -> bool:
    if crawl_options.use_stealth:
        return True
    return os.environ.get("SILENTFROG_STEALTH_ENABLE", "").strip().lower() in {"1", "true", "yes", "on"}


async def _strategy_fetch(
    url: str,
    timeout: int,
    headers: dict[str, str],
    crawl_options: CrawlOptions,
) -> HttpResponse:
    """Fetch via the v2.0 fetcher strategy and adapt back to HttpResponse.

    With stealth off (default) this is exactly the aiohttp base path —
    identical behaviour to the previous direct ``fetch_page`` call.
    """
    strategy = FetchStrategy(FetchOptions(use_stealth=_stealth_enabled(crawl_options)))
    result = await strategy.fetch(FetchRequest(url=url, timeout=timeout, headers=headers))
    return HttpResponse(
        body=result.body,
        status=result.status,
        url=result.final_url,
        headers=result.headers,
        ttfb_ms=result.ttfb_ms,
        total_ms=result.total_ms,
    )


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
    policy: ProfilePolicy,
) -> list[list[str]]:
    # Links are always extracted (local; the frontier needs them). H4 gates only
    # the HTTP status probing: off in LIGHTWEIGHT, bounded in STANDARD, full in DEEP.
    links_rows = _extract_links(page_url, soup)
    if not policy.probe_link_status:
        return links_rows
    to_probe = links_rows if policy.link_probe_cap == 0 else links_rows[: policy.link_probe_cap]
    headers = _headers_from_options(crawl_options)
    async with open_crawl_session(headers=headers) as session:
        coroutines = [_link_status(session, row[0], timeout, crawl_options) for row in to_probe]
        statuses = await asyncio.gather(*coroutines, return_exceptions=True)
    _update_link_statuses(to_probe, statuses)
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
    policy: ProfilePolicy,
) -> dict[str, Any]:
    plain_text = _extract_plain_text(soup)
    meta_rows = _extract_meta(soup)
    header_rows = _extract_headers(soup)
    image_rows = _extract_images(response.url, soup)
    link_rows = await _resolve_link_rows(response.url, soup, timeout, crawl_options, policy)

    canonical_url, is_self, many_canon, canon_status = await _check_canonical(
        response.url,
        soup,
        timeout=timeout,
        crawl_options=crawl_options,
        probe=policy.probe_canonical,
    )
    hops, final_status, hop_count, is_loop = await _redirect_chain(
        request_url, response, timeout, crawl_options, policy
    )
    hreflang_rows = await _extract_hreflang(
        response.url,
        soup,
        timeout=timeout,
        crawl_options=crawl_options,
        probe=policy.probe_hreflang,
    )
    meta_robots = _meta_robots_value(response.headers, soup)
    robots_rules = robots_snapshot or await _parse_robots(request_url, timeout=timeout)
    robots_map = robots_rules.directive_map()
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
        "ai_crawl": _ai_crawl_matrix(robots_rules, meta_robots, response.url),
        "serp": serp_snippet,
        "serp_audit": _title_audit(serp_snippet["title"], header_rows),
        "keywords": _extract_keywords(soup, plain_text),
        "content_quality": extract_content_quality(soup),
        "social": await _extract_social_cards(
            response.url, soup, timeout=timeout, download_images=policy.download_social
        ),
        "discovery": discovery.to_dict(),
    }


async def _redirect_chain(
    request_url: str,
    response: Any,
    timeout: int,
    crawl_options: CrawlOptions,
    policy: ProfilePolicy,
) -> tuple[list[str], str, int, bool]:
    """Trace the redirect chain (extra HTTP) only when the profile allows it;
    otherwise report the page's own status with no hops (H4)."""
    if policy.trace_redirects:
        return await _trace_redirects(request_url, timeout=timeout, options=crawl_options)
    return [request_url], str(response.status), 0, False


async def _collect_render_diff_and_vitals(
    response: Any, crawl_options: CrawlOptions, policy: ProfilePolicy
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Single Playwright launch produces both SSR parity AND CWV.

    Returns ``(render_payload, vitals_payload)``. Both are ``{}`` when the SSR
    parity flag is off OR the profile does not render (H4 gates rendering to
    DEEP), so the rest of the analyse pipeline sees the same defaults M4
    documented.
    """
    if not crawl_options.ssr_parity_check or not policy.render:
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


def merge_rendered_links(page_url: str, raw_rows: list[list[str]], rendered_html: str) -> list[list[str]]:
    """Union raw-HTML link rows with links found only in the JS-rendered DOM (M8).

    Pure + deterministic: rendered rows for URLs already present are dropped, so
    the spider follows SPA routes without double-counting. Rendered-only rows are
    unprobed (status left as ``_extract_links`` emits) — the frontier reads the
    URL column, and the Links tab shows them as not-probed."""
    if not (rendered_html or "").strip():
        return raw_rows
    rendered_rows = _extract_links(page_url, BeautifulSoup(rendered_html, "html.parser"))
    seen = {row[0] for row in raw_rows if row}
    extra: list[list[str]] = []
    for row in rendered_rows:
        if not row or row[0] in seen:
            continue
        seen.add(row[0])  # dedup rendered-only rows against EACH OTHER too
        extra.append(row)
    return raw_rows + extra


async def _augment_links_with_rendered_dom(
    url: str, raw_rows: list[list[str]], crawl_options: CrawlOptions, policy: ProfilePolicy
) -> list[list[str]]:
    """M8 — render the page and merge its DOM links so the spider can follow
    JS-injected routes. Off unless ``render_js`` is set and the profile renders;
    a render failure degrades to the raw rows (never raises)."""
    if not crawl_options.render_js or not policy.render:
        return raw_rows
    rendered = await asyncio.to_thread(render_with_playwright, url, 15, False)
    if rendered is None or rendered.error or not rendered.rendered_html:
        return raw_rows
    return merge_rendered_links(url, raw_rows, rendered.rendered_html)


async def _collect_bot_renders(response: Any, crawl_options: CrawlOptions, policy: ProfilePolicy) -> dict[str, Any]:
    """v2.0 V10 — per-bot SSR renders through the shared pool. Off by default;
    ``{}`` (unmeasured) when the flag is off or the profile does not render."""
    if not crawl_options.bot_render or not policy.render:
        return {}
    from .bot_render import render_for_bots

    return await render_for_bots(response.url, response.body)


async def _collect_accessibility(response: Any, crawl_options: CrawlOptions, policy: ProfilePolicy) -> dict[str, Any]:
    """v3 G4 Stage 1 — axe-core WCAG scan through the shared render pool. Off
    by default; ``{}`` (unmeasured) when the flag is off or the profile does
    not render (same gating shape as ``_collect_bot_renders``)."""
    from .accessibility_audit import collect_accessibility

    return await collect_accessibility(response.url, crawl_options, policy)


async def analyse(url: str, timeout: int = 10, options: CrawlOptions | None = None) -> CrawlPayload:
    """Audit one URL. TLS is verified and SSRF is guarded by default; a crawl
    that opted into ``allow_insecure_tls`` / ``allow_private_network`` relaxes
    that posture for this scope only (H7)."""
    crawl_options = options or CrawlOptions.default()
    with (
        insecure_tls(enabled=crawl_options.allow_insecure_tls),
        allow_private_network(enabled=crawl_options.allow_private_network),
    ):
        return await _analyse(url, timeout, crawl_options)


async def _analyse(url: str, timeout: int, crawl_options: CrawlOptions) -> CrawlPayload:
    policy = ProfilePolicy.for_profile(crawl_options.profile)
    response, robots_snapshot = await _fetch_analysis_response(url, timeout, crawl_options)
    soup = BeautifulSoup(response.body, "html.parser")
    structured_data = _extract_schema_all(response.body, response.url)
    performance_metrics = await _collect_performance_metrics(response, soup, probe_resources=policy.probe_resources)
    section_payload = await _collect_analysis_sections(
        url,
        response,
        soup,
        timeout,
        crawl_options,
        robots_snapshot,
        policy,
    )
    section_payload["links"] = await _augment_links_with_rendered_dom(
        response.url, section_payload.get("links", []), crawl_options, policy
    )

    eeat = extract_eeat_signals(soup, structured_data, response.url)
    structure = extract_structure_signals(soup, response.url)
    pseudo_links = extract_pseudo_links(soup)
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
    render_payload, vitals_payload = await _collect_render_diff_and_vitals(response, crawl_options, policy)
    bot_render_payload = await _collect_bot_renders(response, crawl_options, policy)
    accessibility_payload = await _collect_accessibility(response, crawl_options, policy)
    crux_payload, ai_citations_payload, google_metrics, semrush_metrics, ai_sov_metrics = await _collect_integrations(
        response.url, policy
    )
    # Rich-result eligibility is schema-derived locally on every profile; only its
    # optional GSC upgrade is an integration (H4 keeps local parse always on).
    rich_results = await _collect_rich_results(structured_data, response.url, probe_gsc=policy.run_integrations)
    raw_payload = {
        "payload_schema_version": PAYLOAD_SCHEMA_VERSION,
        "requested_url": url,
        "final_url": response.url,
        "schema": structured_data,
        "rich_results": rich_results,
        "performance": performance_metrics,
        **section_payload,
        "eeat": eeat.to_dict(),
        "structure": structure.to_dict(),
        "pseudo_links": pseudo_links,
        "citation_content": citation_content.to_dict(),
        "citation_advanced": citation_advanced.to_dict(),
        "seo_basics": seo_basics.to_dict(),
        "render": render_payload,
        "bot_render": bot_render_payload,
        "accessibility": accessibility_payload,
        "perf_vitals": vitals_payload,
        "perf_crux": crux_payload,
        "ai_citations": ai_citations_payload,
        "custom_extraction": extract_custom(response.body, crawl_options.custom_extraction),
        "tech_stack": _collect_tech_stack(response, soup, crawl_options),
        # Model inference blocks; keep the crawl loop responsive (V10 render precedent).
        "topic_embeddings": await asyncio.to_thread(_collect_topic_embeddings, soup, crawl_options),
        "brand_mentions": await _collect_brand_mentions(response.url, soup, policy),
        "semrush": semrush_metrics,
        "ai_sov": ai_sov_metrics,
        **google_metrics,
    }
    raw_payload["ai_visibility"] = build_ai_visibility_payload(raw_payload).to_dict()
    return CrawlPayload.from_raw(raw_payload)


async def _collect_integrations(
    url: str, policy: ProfilePolicy
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """External integrations (CrUX / AI citations / GSC+GA4 / Semrush / AI SOV).
    H4 gates them off entirely in LIGHTWEIGHT; STANDARD/DEEP attempt them, each
    still self-gated by its own enable flag. Returns (crux, ai_citations,
    google, semrush, ai_sov)."""
    if not policy.run_integrations:
        return {}, {}, {}, {}, {}
    return (
        await _collect_crux(url),
        await _collect_ai_citations(url),
        await _collect_google_metrics(url),
        await _collect_semrush(url),
        await _collect_ai_sov(url),
    )


def _collect_topic_embeddings(soup: BeautifulSoup, crawl_options: CrawlOptions) -> dict[str, Any]:
    """v2.0 V20 — local embedding coherence, off by default. Local-only compute,
    so no profile gate; the flag (plus the [embeddings] extra) is the consent."""
    if not crawl_options.topic_embeddings:
        return {}
    from .embeddings import topic_coherence

    title_tag = soup.title
    title = (title_tag.string or "").strip() if title_tag else ""
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""
    paragraphs = [tag.get_text(separator=" ", strip=True) for tag in soup.find_all("p")]
    return topic_coherence(title, paragraphs).to_dict()


async def _collect_brand_mentions(url: str, soup: BeautifulSoup, policy: ProfilePolicy) -> dict[str, Any]:
    """v2.0 V20 — brand-mention counts + local series. Gated like every
    integration: H4 profile switch AND its own env enable knob."""
    if not policy.run_integrations:
        return {}
    from .brand_mentions import fetch_brand_mentions

    og_tag = soup.find("meta", attrs={"property": "og:site_name"})
    og_site_name = str(og_tag.get("content", "")) if og_tag else ""
    payload = await fetch_brand_mentions(url, og_site_name=og_site_name)
    return payload.to_dict()


async def _collect_ai_sov(url: str) -> dict[str, Any]:
    """v3 G3 Stage 1 — BYO-key AI-engine share-of-voice sampling (ChatGPT /
    Perplexity / Gemini), gated on SILENTFROG_AI_SOV_ENABLE + at least one
    per-engine key (keyring or env). Returns {} (unmeasured) on a stock
    audit. Never raises."""
    from .brand_mentions import derive_brand
    from .integrations.ai_engines import fetch_share_of_voice

    host = urlparse(url or "").netloc.split(":")[0]
    brand = derive_brand(url)
    if not host or not brand:
        return {}
    try:
        report = await fetch_share_of_voice(host, brand)
    except Exception:  # noqa: BLE001 — integration failure degrades silently
        return {}
    return report.to_dict()


def _collect_tech_stack(response: Any, soup: BeautifulSoup, crawl_options: CrawlOptions) -> dict[str, Any]:
    """v2.0 V15 — optional Wappalyzer-style detection, off by default."""
    if not crawl_options.tech_stack_detection:
        return {}
    scripts = [str(tag.get("src")) for tag in soup.find_all("script", src=True)]
    generator_tag = soup.find("meta", attrs={"name": "generator"})
    generator = str(generator_tag.get("content", "")) if generator_tag else ""
    headers = dict(response.headers) if isinstance(getattr(response, "headers", None), dict) else {}
    return detect_tech(response.body, headers, scripts, generator).to_dict()


async def _collect_google_metrics(url: str) -> dict[str, Any]:
    """v2.0 V7 — GSC + GA4 metrics, gated on SILENTFROG_GOOGLE_ENABLE +
    a connected account. Returns {} (unmeasured) on a stock audit."""
    from .integrations.google.connection import from_env

    connection = from_env()
    if connection is None:
        return {}
    try:
        return await asyncio.to_thread(connection.metrics_for, url)
    except Exception:  # noqa: BLE001 — integration failure degrades silently
        return {}


def _semrush_enabled() -> bool:
    return os.environ.get("SILENTFROG_SEMRUSH_ENABLE", "").strip().lower() in {"1", "true", "yes", "on"}


def _semrush_max_calls() -> int:
    try:
        return int(os.environ.get("SILENTFROG_SEMRUSH_MAX_CALLS", "100").strip() or "100")
    except ValueError:
        return 100


def _registrable_domain(url: str) -> str:
    """Registrable domain (eTLD+1) of the URL host, so a whole-site crawl
    caches one Semrush overview per domain rather than per URL."""
    import tldextract

    extracted = tldextract.extract(url)
    return str(extracted.top_domain_under_public_suffix or "").lower()


async def _collect_semrush(url: str) -> dict[str, Any]:
    """v2.0 V17 — Semrush authority metrics, gated on
    SILENTFROG_SEMRUSH_ENABLE + an API key (keyring or env). Returns {}
    (unmeasured) on a stock audit. Cached per registrable domain so the
    daily call budget covers ~1-2 calls per domain. Never raises."""
    if not _semrush_enabled():
        return {}
    from .integrations.semrush.client import fetch_domain_overview, resolve_api_key

    api_key = resolve_api_key()
    if not api_key:
        return {}
    domain = _registrable_domain(url)
    if not domain:
        return {}
    try:
        metrics = await fetch_domain_overview(domain, api_key, _semrush_max_calls())
    except Exception:  # noqa: BLE001 — integration failure degrades silently
        return {}
    return metrics.to_dict()


async def _collect_rich_results(structured_data: dict[str, Any], url: str, *, probe_gsc: bool = True) -> dict[str, Any]:
    """v2.0 V14 — rich-result eligibility. Schema-derived on every audit
    (free, no network); upgraded to Google's verdict when a GSC site is
    connected AND ``probe_gsc`` is set (H4 gates the GSC call). Never raises."""
    from .integrations.google.rich_results import derive_from_schema, from_url_inspection

    report = derive_from_schema(structured_data)
    if not probe_gsc:
        return report.to_dict()
    inspection = await _gsc_inspection(url)
    if inspection:
        gsc_report = from_url_inspection(inspection)
        if gsc_report.measured:
            report = gsc_report
    return report.to_dict()


async def _gsc_inspection(url: str) -> dict[str, Any]:
    """Optional GSC URL Inspection call, gated like the other Google
    integrations. Returns {} unless a GSC site is connected."""
    from .integrations.google.connection import from_env

    connection = from_env()
    if connection is None:
        return {}
    try:
        return await asyncio.to_thread(connection.inspect_rich_results, url)
    except Exception:  # noqa: BLE001 — integration failure degrades silently
        return {}


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
    async with open_crawl_session() as sess:
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
    "merge_rendered_links",
]
