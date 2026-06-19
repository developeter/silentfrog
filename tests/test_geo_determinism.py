"""H0 GEO determinism regression.

Guarantees that PR-1's lossless ``CrawlPayload`` serialization must deliver,
pinned so they cannot silently regress:

1. Each of the 12 AI-Visibility source groups affects the audit — clearing
   ANY ONE of them changes the recomputed checks (per-group sensitivity), so a
   per-group drop cannot pass unnoticed. (An empty-group fixture, or clearing
   all 12 at once, would NOT prove per-group coverage.)
2. The stored ``AiVisibilityPayload`` survives a real SQLite store round-trip,
   and a fresh recompute from the reloaded groups is structurally identical to
   one from the original groups (no drift) — not just the score.
3. ``recompute_with_lighthouse`` returns the structurally identical mapping on
   the original and the store-reloaded payload.
4. The page-URL priority is ``final_url -> requested_url -> legacy url``.
"""

from __future__ import annotations

from typing import Any

import pytest

from silentfrog.ai_citations import AiCitationsPayload
from silentfrog.ai_visibility import _resolve_page_url, build_ai_visibility_payload, recompute_with_lighthouse
from silentfrog.citation_advanced import AdvancedCitationPayload
from silentfrog.citation_readiness_content import CitationContentPayload
from silentfrog.crawl_store import CrawlStore, StoredAudit
from silentfrog.crawl_types import PAYLOAD_SCHEMA_VERSION, CrawlPayload
from silentfrog.discovery_files import DiscoveryPayload
from silentfrog.eeat_signals import EeatPayload
from silentfrog.integrations.google.types import Ga4Metrics, GscMetrics
from silentfrog.perf_crux import CruxData
from silentfrog.perf_vitals import WebVitals
from silentfrog.seo_basics import SeoBasicsPayload
from silentfrog.structure_signals import StructurePayload

_H0_GROUPS = (
    "discovery",
    "eeat",
    "structure",
    "citation_content",
    "citation_advanced",
    "seo_basics",
    "render",
    "perf_vitals",
    "perf_crux",
    "ai_citations",
    "gsc",
    "ga4",
)

# All-90s, measured -> emits a "lighthouse_perf_above_90" check (see V14).
_LIGHTHOUSE_SCORES: dict[str, Any] = {
    "performance": 95,
    "accessibility": 95,
    "seo": 95,
    "best_practices": 95,
    "measured": True,
}


def _populated_h0_groups() -> dict[str, Any]:
    """Producer-shaped, JSON-native, score-affecting data for the H0 groups.

    Built from the real signal payload types (so the shapes match what
    ``seo_crawler.analyse`` persists). Perf/render carry threshold-breaching
    values so the recomputed score is provably below 100, which makes the
    "clearing the groups changes the score" sensitivity check meaningful.
    """
    return {
        "discovery": DiscoveryPayload.from_raw(
            {
                "llms_txt": {"url": "https://e.com/llms.txt", "status": 200, "present": True, "source": "fetch"},
                "llms_full_txt": {
                    "url": "https://e.com/llms-full.txt",
                    "status": 200,
                    "present": True,
                    "source": "fetch",
                },
                "well_known_ai_json": {
                    "url": "https://e.com/.well-known/ai.json",
                    "status": 200,
                    "present": True,
                    "source": "fetch",
                },
                "sitemap": {
                    "url": "https://e.com/sitemap.xml",
                    "status": 200,
                    "present": True,
                    "source": "robots-sitemap",
                },
            }
        ).to_dict(),
        "eeat": EeatPayload(
            byline="Jane Doe",
            publish_date="2026-01-01",
            update_date="2026-06-01",
            days_since_update=10,
            author_bio_url="https://e.com/about",
            same_as=("https://linkedin.com/in/jane",),
            external_citations=("https://nih.gov/x",),
        ).to_dict(),
        "structure": StructurePayload(
            semantic_container_counts={"article": 1, "section": 2, "main": 1, "nav": 1, "header": 1, "footer": 1},
            internal_link_count=8,
            total_link_count=12,
            images_with_alt=5,
            images_total=5,
        ).to_dict(),
        "citation_content": CitationContentPayload(
            question_headings=("What is RAG?",),
            definitions=("RAG is a technique.",),
            stats_density=1.5,
            stats_count=6,
            word_count=400,
            language="en",
        ).to_dict(),
        "citation_advanced": AdvancedCitationPayload.from_raw(
            {
                "quotations": {"count": 2, "with_attribution": 1, "sample": "Quote - A. Smith"},
                "readability": {"score": 72.0, "language": "en", "formula": "Flesch Reading Ease"},
                "vocab_ttr": 0.62,
                "keyword_warning": False,
                "authoritative_tone_ratio": 0.012,
                "word_count": 400,
            }
        ).to_dict(),
        "seo_basics": SeoBasicsPayload(
            viewport_present=True,
            viewport_content="width=device-width, initial-scale=1",
            descriptive_url=True,
            url_path="/guide/ai-visibility",
        ).to_dict(),
        # RenderDiff has no to_dict(); the stored group is the raw dict that
        # ai_visibility._render_diff_from_raw accepts. "critical" => -10 score.
        "render": {
            "status": "critical",
            "missing_headings": ["Pricing", "FAQ"],
            "missing_main_text_chars": 800,
            "missing_links": 7,
            "reason": "Rendered HTML is empty",
        },
        # Threshold-breaching lab + field vitals => criticals (score lever).
        "perf_vitals": WebVitals(
            lcp_ms=5000.0, inp_ms=600.0, cls=0.4, fcp_ms=4000.0, tbt_ms=900.0, speed_index_ms=7000.0
        ).to_dict(),
        "perf_crux": CruxData(
            lcp_p75_ms=5000.0, inp_p75_ms=600.0, cls_p75=0.4, has_field_data=True, reason=""
        ).to_dict(),
        # Optional integrations — populated as MEASURED so they are exercised
        # too and a per-group drop of any of them is detectable (an empty group
        # would make its drop a silent no-op).
        "ai_citations": AiCitationsPayload(
            brave_indexed=True,
            brave_summary_mentions=3,
            common_crawl_references=2,
            perplexity_likely_indexed=True,
            measured=True,
        ).to_dict(),
        "gsc": GscMetrics(
            impressions=1200, clicks=80, ctr=0.066, position=8.5, top_queries=("example query",), measured=True
        ).to_dict(),
        "ga4": Ga4Metrics(
            pageviews=900, avg_engagement_seconds=45.0, bounce_rate=0.42, conversions=12, measured=True
        ).to_dict(),
    }


def _audited_raw() -> dict[str, Any]:
    """A complete raw payload with AI Visibility computed from POPULATED source
    groups, mirroring what ``seo_crawler.analyse()`` produces before storage."""
    raw: dict[str, Any] = {
        "payload_schema_version": PAYLOAD_SCHEMA_VERSION,
        "requested_url": "https://e.com/p",
        "final_url": "https://e.com/p",
        "meta": [["title", "Example Title"], ["description", "An example page description for the audit."]],
        "headers": [["h1", "Example"]],
        "images": [],
        "links": [],
        "schema": {
            "summary": {"total": 0, "by_syntax": {}, "by_type": {}, "errors": []},
            "blocks": [],
            "fallback_raw": [],
        },
        "canonical": {"target": "https://e.com/p", "self": True, "multiple": False, "status": "200"},
        "redirect": {"chain": ["https://e.com/p"], "hops": 0, "final_status": "200", "loop": False},
        "robots": {"*": [("Allow", "/")]},
        "meta_robots": "index, follow",
        "hreflang": [],
        "ai_crawl": [["GPTBot", "gptbot", "Yes", "-", "-", "Allowed", "No explicit AI restrictions detected"]],
        "serp": {},
        "serp_audit": {},
        "keywords": [{"term": "example", "length": 1, "frequency": 2, "density": 2.5}],
        "content_quality": {"verdict": "Strong", "word_count": 600},
        "social": {},
        **_populated_h0_groups(),
    }
    raw["ai_visibility"] = build_ai_visibility_payload(raw).to_dict()
    return raw


def _audited_payload() -> CrawlPayload:
    return CrawlPayload.from_raw(_audited_raw())


def _store_roundtrip(payload: CrawlPayload) -> CrawlPayload:
    store = CrawlStore(":memory:")
    try:
        run_id = store.start_run("e.com", "https://e.com/", "list")
        store.save_audit(run_id, StoredAudit(url=payload.final_url, payload=payload.to_mapping()))
        store.flush()
        loaded = store.load_payload(run_id, payload.final_url)
        assert loaded is not None
        return CrawlPayload.from_raw(loaded)
    finally:
        store.close()


def test_each_h0_group_affects_recomputed_checks() -> None:
    # PER-GROUP sensitivity guard: EACH of the 12 source groups must affect the
    # audit. Clearing any ONE group (the pre-H0 lossy-reload condition for that
    # group) must change the recomputed checks — so a per-group drop cannot pass
    # unnoticed. Clearing all 12 at once, or an all-empty fixture, would NOT
    # prove per-group coverage. (Score is only moved by perf/render/eeat; the
    # myth-flagged groups change check status, hence we assert on checks.)
    payload = _audited_payload()
    populated = build_ai_visibility_payload(payload.to_mapping())
    assert populated.summary.score < 100  # breaching perf/render lowered it

    base = payload.to_mapping()
    for group in _H0_GROUPS:
        cleared = dict(base)
        cleared[group] = {}
        recomputed = build_ai_visibility_payload(cleared)
        assert recomputed.checks != populated.checks, f"clearing {group!r} did not change the recomputed checks"


def test_ai_visibility_identical_across_store_roundtrip() -> None:
    # Pins store-round-trip FIDELITY (persist -> reload reproduces the same
    # payload), not cross-producer agreement — both sides derive from one raw.
    payload = _audited_payload()
    original = payload.ai_visibility

    reloaded = _store_roundtrip(payload)
    # The stored AiVisibilityPayload (summary + every check) survives the real
    # zlib+JSON store round-trip unchanged...
    assert reloaded.ai_visibility == original
    # ...and a fresh recompute from the reloaded groups equals a fresh recompute
    # from the original groups — no drift. (Both sides freshly computed: comparing
    # the fresh recompute against the stored `original` would spuriously differ
    # because AiVisibilityCheck.from_raw folds the "info" status into "good".)
    assert build_ai_visibility_payload(reloaded) == build_ai_visibility_payload(payload)


def test_lighthouse_recompute_structurally_identical_after_store_reload() -> None:
    payload = _audited_payload()

    on_original = recompute_with_lighthouse(payload, _LIGHTHOUSE_SCORES)
    on_reloaded = recompute_with_lighthouse(_store_roundtrip(payload), _LIGHTHOUSE_SCORES)

    # The COMPLETE returned mapping is structurally identical (every key),
    # whether or not a store round-trip happened in between.
    assert on_reloaded == on_original

    # Sentinels prove the POPULATED group data fed the recompute, not defaults.
    # Unconditional checks (always emitted) are asserted by their data-specific
    # STATUS; gated checks (emitted only when their group is measured/added) are
    # asserted by presence, which is itself the signal.
    status_by_key = {c["key"]: c["status"] for c in on_original["ai_visibility"]["checks"]}
    assert status_by_key["access_llms_txt"] == "good"  # discovery present
    assert status_by_key["eeat_author_byline"] == "good"  # eeat byline present
    assert status_by_key["perf_lcp"] == "critical"  # perf_vitals breaching
    assert status_by_key["perf_crux_lcp"] == "critical"  # perf_crux breaching
    assert status_by_key["access_ssr_parity"] == "critical"  # render critical
    gated = {
        "ai_citations_perplexity",
        "gsc_impressions_present",
        "ga4_engagement_above_median",
        "lighthouse_perf_above_90",
    }
    assert gated <= status_by_key.keys()


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"final_url": "https://f/", "requested_url": "https://r/", "url": "https://u/"}, "https://f/"),
        ({"requested_url": "https://r/", "url": "https://u/"}, "https://r/"),
        ({"url": "https://u/"}, "https://u/"),
        ({"final_url": "", "requested_url": "https://r/"}, "https://r/"),
        ({}, ""),
    ],
    ids=["final_wins", "requested_over_legacy", "legacy_url", "empty_final_falls_through", "none"],
)
def test_page_url_priority(data: dict[str, object], expected: str) -> None:
    assert _resolve_page_url(data) == expected
