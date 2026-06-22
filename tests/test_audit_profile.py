"""v2.0 PR-12 (H4) — AuditProfile gating + per-origin discovery.

Profiles gate ONLY extra HTTP requests, rendering, and integrations. These tests
pin the locked semantics:

- the policy matrix (which gates each profile applies);
- per-profile request budgets — counted at the seam-routed probe primitives —
  so LIGHTWEIGHT issues no per-link/canonical/redirect/hreflang/social/resource/
  integration requests, STANDARD adds bounded link/canonical/redirect only, and
  DEEP does everything;
- local parsing (SEO, structure, E-E-A-T, schema, meta) stays on in EVERY profile;
- site-wide discovery is fetched once per origin, not per page.

All deterministic + offline: the page fetch and every network probe are stubbed.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import replace

import pytest

from silentfrog import discovery_files, parsers_meta, perf_metrics, seo_crawler
from silentfrog.crawl_http import _ProbeResponse
from silentfrog.crawl_options import AuditProfile, CrawlOptions, ProfilePolicy
from silentfrog.discovery_files import DiscoveryPayload, discovery_scope, fetch_discovery_files
from silentfrog.http_client import HttpResponse
from silentfrog.robots_simulator import parse_robots

_LINKS = "".join(f'<a href="https://e.com/p{i}">L{i}</a>' for i in range(30))
_SYNTHETIC_HTML = (
    "<html><head><title>Example Title</title>"
    '<meta name="description" content="A useful description of the page.">'
    '<link rel="canonical" href="https://e.com/other">'
    '<link rel="alternate" hreflang="en" href="https://e.com/en">'
    '<link rel="alternate" hreflang="de" href="https://e.com/de">'
    '<meta property="og:image" content="https://e.com/card.png">'
    '<link rel="stylesheet" href="https://e.com/site.css">'
    '<script src="https://e.com/app.js"></script></head>'
    f"<body><h1>Heading</h1><p>Body content for parsing.</p>{_LINKS}"
    '<img src="https://e.com/pic.png" alt="Pic"></body></html>'
)


def _opts(profile: AuditProfile) -> CrawlOptions:
    return replace(CrawlOptions.default(), profile=profile)


def _install_counting_probes(monkeypatch) -> Counter:
    """Stub the page fetch + every network probe, counting each by category."""
    counts: Counter = Counter()

    async def fake_fetch(url, timeout, crawl_options):
        return HttpResponse(body=_SYNTHETIC_HTML, status=200, url=url, headers={}, ttfb_ms=1, total_ms=1), None

    async def fake_parse_robots(url, timeout=5):
        return parse_robots("")

    async def fake_link_status(session, url, timeout, options):
        counts["link"] += 1
        return 200

    async def fake_trace(url, timeout=8, options=None):
        counts["redirect"] += 1
        return [url], "200", 0, False

    async def fake_probe(session, url, timeout, options, *, allow_redirects):
        counts["probe"] += 1  # canonical + hreflang both route through here
        return _ProbeResponse(200, {})

    async def fake_img(url, timeout=5):
        counts["social"] += 1
        return 10, 10, 100, "image/png", ""

    async def fake_resources(targets):
        if targets:
            counts["resource"] += 1
        return {}, {}

    async def fake_discovery(base_url, robots_map=None, timeout=8, crawl_options=None):
        counts["discovery"] += 1
        return DiscoveryPayload.empty()

    monkeypatch.setattr(seo_crawler, "_fetch_analysis_response", fake_fetch)
    monkeypatch.setattr(seo_crawler, "_parse_robots", fake_parse_robots)
    monkeypatch.setattr(seo_crawler, "_link_status", fake_link_status)
    monkeypatch.setattr(seo_crawler, "_trace_redirects", fake_trace)
    monkeypatch.setattr(seo_crawler, "fetch_discovery_files", fake_discovery)
    monkeypatch.setattr(parsers_meta, "_polite_probe_response", fake_probe)
    monkeypatch.setattr(parsers_meta, "_fetch_image_details", fake_img)
    monkeypatch.setattr(perf_metrics, "_measure_remote_resources", fake_resources)
    return counts


def test_profile_policy_matrix() -> None:
    light = ProfilePolicy.for_profile(AuditProfile.LIGHTWEIGHT)
    std = ProfilePolicy.for_profile(AuditProfile.STANDARD)
    deep = ProfilePolicy.for_profile(AuditProfile.DEEP)

    # LIGHTWEIGHT: every network gate off.
    assert not any(
        [
            light.probe_link_status,
            light.probe_canonical,
            light.trace_redirects,
            light.probe_hreflang,
            light.download_social,
            light.probe_resources,
            light.render,
            light.run_integrations,
        ]
    )
    # STANDARD: bounded link/canonical/redirect + integrations; no hreflang-probe,
    # social, resources, or render.
    assert std.probe_link_status and std.link_probe_cap > 0
    assert std.probe_canonical and std.trace_redirects and std.run_integrations
    assert not std.probe_hreflang and not std.download_social and not std.probe_resources and not std.render
    # DEEP: everything on, link probing unbounded.
    assert deep.link_probe_cap == 0
    assert all([deep.probe_hreflang, deep.download_social, deep.probe_resources, deep.render, deep.run_integrations])


def test_audit_profile_from_value() -> None:
    assert AuditProfile.from_value("deep") is AuditProfile.DEEP
    assert AuditProfile.from_value("LIGHTWEIGHT") is AuditProfile.LIGHTWEIGHT
    assert AuditProfile.from_value(AuditProfile.STANDARD) is AuditProfile.STANDARD
    assert AuditProfile.from_value("nonsense") is AuditProfile.STANDARD  # safe default


@pytest.mark.parametrize(
    "profile,expected",
    [
        (AuditProfile.LIGHTWEIGHT, {"link": 0, "redirect": 0, "probe": 0, "social": 0, "resource": 0, "discovery": 1}),
        (AuditProfile.STANDARD, {"link": 25, "redirect": 1, "probe": 1, "social": 0, "resource": 0, "discovery": 1}),
        (AuditProfile.DEEP, {"link": 30, "redirect": 1, "probe": 3, "social": 2, "resource": 1, "discovery": 1}),
    ],
)
@pytest.mark.asyncio
async def test_per_profile_request_budget(monkeypatch, profile, expected) -> None:
    # STANDARD's probe count is canonical-only (1); DEEP adds the two hreflang
    # probes (3). STANDARD caps link probing at 25 of the 30 links; DEEP probes all.
    counts = _install_counting_probes(monkeypatch)
    await seo_crawler.analyse("https://e.com/p", options=_opts(profile))
    for key, value in expected.items():
        assert counts[key] == value, (profile, key, dict(counts))


@pytest.mark.parametrize("profile", list(AuditProfile))
@pytest.mark.asyncio
async def test_local_parse_present_in_every_profile(monkeypatch, profile) -> None:
    # Local parsing is never gated: meta + SEO + structure + E-E-A-T + schema are
    # produced even in LIGHTWEIGHT (which skips all network probes).
    _install_counting_probes(monkeypatch)
    payload = await seo_crawler.analyse("https://e.com/p", options=_opts(profile))
    assert payload.meta  # title/description parsed
    assert isinstance(payload.seo_basics, dict) and payload.seo_basics
    assert isinstance(payload.structure, dict)
    assert isinstance(payload.eeat, dict)
    assert payload.schema is not None  # schema extraction ran (local, never gated)


@pytest.mark.asyncio
async def test_lightweight_skips_probes_observable_in_payload(monkeypatch) -> None:
    # Beyond counts: the gating shows in the payload. LIGHTWEIGHT leaves the
    # canonical status empty (tag parsed, not probed) and hreflang status "-"
    # (parse-only); DEEP probes both.
    _install_counting_probes(monkeypatch)
    light = await seo_crawler.analyse("https://e.com/p", options=_opts(AuditProfile.LIGHTWEIGHT))
    deep = await seo_crawler.analyse("https://e.com/p", options=_opts(AuditProfile.DEEP))
    assert light.canonical.status == ""  # not probed
    assert deep.canonical.status == "200"  # probed
    assert all(row[2] == "-" for row in light.hreflang)  # parse-only status
    assert all(row[2] == "200" for row in deep.hreflang)  # probed status


@pytest.mark.asyncio
async def test_discovery_fetched_once_per_origin_within_scope(monkeypatch) -> None:
    calls: Counter = Counter()

    async def fake_uncached(site_root, robots_map, timeout, crawl_options):
        calls[site_root] += 1
        await asyncio.sleep(0)  # let a concurrent same-origin caller interleave
        return DiscoveryPayload.empty()

    monkeypatch.setattr(discovery_files, "_fetch_discovery_uncached", fake_uncached)

    with discovery_scope():
        await asyncio.gather(
            fetch_discovery_files("https://e.com/page1"),
            fetch_discovery_files("https://e.com/page2"),  # same origin
            fetch_discovery_files("https://other.com/x"),
        )
    assert calls["https://e.com/"] == 1  # once per origin despite two pages + concurrency
    assert calls["https://other.com/"] == 1


@pytest.mark.asyncio
async def test_discovery_not_cached_without_scope(monkeypatch) -> None:
    calls: Counter = Counter()

    async def fake_uncached(site_root, robots_map, timeout, crawl_options):
        calls[site_root] += 1
        return DiscoveryPayload.empty()

    monkeypatch.setattr(discovery_files, "_fetch_discovery_uncached", fake_uncached)

    await fetch_discovery_files("https://e.com/page1")
    await fetch_discovery_files("https://e.com/page2")
    assert calls["https://e.com/"] == 2  # no active scope → fetched per call (single-page audits)


@pytest.mark.asyncio
async def test_discovery_degrades_to_empty_on_session_error(monkeypatch) -> None:
    # The module contract is "never raises": a session/connector construction
    # failure must degrade the whole origin to an empty payload, not propagate.
    def boom(*args, **kwargs):
        raise RuntimeError("session boom")

    monkeypatch.setattr(discovery_files, "open_crawl_session", boom)
    result = await discovery_files._fetch_discovery_uncached("https://e.com/", None, 8, None)
    assert result == DiscoveryPayload.empty()


@pytest.mark.asyncio
async def test_discovery_cache_does_not_poison_origin_on_failure(monkeypatch) -> None:
    # If a fetch fails under an active scope, the cache must degrade to empty for
    # that origin — never store the exception and re-raise it for every later page.
    async def raising_fetch(site_root, robots_map, timeout, crawl_options):
        raise RuntimeError("boom")

    monkeypatch.setattr(discovery_files, "_fetch_discovery_uncached", raising_fetch)
    with discovery_scope():
        first = await fetch_discovery_files("https://e.com/p1")
        second = await fetch_discovery_files("https://e.com/p2")  # same origin, must not re-raise
    assert first == DiscoveryPayload.empty()
    assert second == DiscoveryPayload.empty()
