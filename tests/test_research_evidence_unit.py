"""Evidence taxonomy registry (H6 / PR-14).

Pins the machine-checkable contract introduced by PR-14:

1. The new ``evidence_class`` / ``evidence_source_ids`` survive an
   ``AiVisibilityCheck`` round-trip.
2. ``docs/RESEARCH_CITATIONS.md`` and ``research_evidence.EVIDENCE_SOURCES`` are
   in exact lockstep (no drift in either direction).
3. ``CHECK_EVIDENCE`` uses only valid classes/source IDs and every sourced class
   resolves at least one source.
4. Every emittable check key is classified, and a comprehensive real audit emits
   only classified checks.
5. Enrichment is status-neutral (never mutates the verdict-bearing fields).

The comprehensive fixture and the helpers here are reused by the PR-15 guard.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from silentfrog.ai_visibility import (
    _AI_VISIBILITY_CHECK_TOOLTIPS,
    ai_visibility_check_tooltip,
    build_ai_visibility_checks,
)
from silentfrog.crawl_types import AiVisibilityCheck
from silentfrog.research_evidence import (
    CHECK_EVIDENCE,
    EVIDENCE_CLASSES,
    EVIDENCE_HEURISTIC,
    EVIDENCE_RESEARCH,
    EVIDENCE_SOURCES,
    SOURCED_CLASSES,
    attach_evidence,
)

# An "effect-size" claim = a signed percentage (+30%, -10%), a multiplier
# (3.2x / 3.2×), or an "up to N%" magnitude. Bare threshold percentages
# ("4%", "2% CTR", "70%"), score bands ("≥ 60", "90+"), and section refs
# ("§1.5 x-default") are NOT effect sizes and must not trip the guard — hence the
# ascii "x" multiplier must be attached to the digits (no intervening space).
_EFFECT_SIZE_RE = re.compile(
    r"[+\-−]\s?\d+(?:\.\d+)?\s?%"  # signed percentage
    r"|\d+(?:\.\d+)?\s?×"  # unicode multiplier
    r"|\d+(?:\.\d+)?x\b"  # ascii multiplier, attached
    r"|up to\s?~?\d+(?:\.\d+)?\s?%",  # "up to ~40%"
    re.IGNORECASE,
)

_DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "RESEARCH_CITATIONS.md"
_SOURCE_HEADING_RE = re.compile(r"^### `([A-Z0-9-]+)`", re.MULTILINE)


def comprehensive_audit_raw() -> dict[str, Any]:
    """A measured-everything payload that exercises every AI Visibility builder
    (core + optional integrations), so the produced check set is complete."""
    return {
        "payload_schema_version": 2,
        "requested_url": "https://e.com/p",
        "final_url": "https://e.com/p",
        "meta": [["title", "Example Page Title", "18"]],
        "headers": [["h1", "Example Page Title"]],
        "images": [],
        "links": [],
        "schema": {
            "summary": {"total": 1, "by_syntax": {"json-ld": 1}, "by_type": {"Product": 1}, "errors": []},
            "eligibility": [
                {
                    "type": "Product",
                    "detected": True,
                    "count": 1,
                    "eligibility": "Eligible",
                    "missing_fields": [],
                    "warnings": [],
                },
            ],
            "blocks": [],
            "fallback_raw": [],
        },
        "canonical": {"target": "https://e.com/p", "self": True, "multiple": False, "status": "200"},
        "redirect": {"chain": ["https://e.com/p"], "hops": 0, "final_status": "200", "loop": False},
        "robots": {"*": [["Allow", "/"]]},
        "meta_robots": "index, follow",
        "hreflang": [["en", "https://e.com/p", "alternate", "yes", "yes"]],
        "ai_crawl": [["GPTBot", "gptbot", "Yes", "-", "-", "Allowed", "ok"]],
        "serp": {},
        "serp_audit": {},
        "keywords": [{"term": "example", "length": 1, "frequency": 2, "density": 2.5}],
        "content_quality": {
            "verdict": "Strong",
            "word_count": 600,
            "language": "English (en-US)",
            "paragraph_count": 6,
            "substantial_paragraph_count": 4,
            "average_words_per_paragraph": 24.5,
            "title_present": True,
            "meta_description_present": True,
            "h1_count": 1,
            "h2_h6_count": 3,
            "title_h1_alignment": "Aligned",
            "intro_paragraph": "Present",
            "thin_content_risk": "Low",
            "heading_structure": "Good",
        },
        "social": {
            "open_graph": {"title": "Example Page Title", "description": "desc"},
            "twitter": {"title": "Example Page Title", "description": "desc"},
        },
        "discovery": {
            "llms_txt": {"present": True, "status": 200},
            "llms_full_txt": {"present": True, "status": 200},
            "well_known_ai_json": {"present": True, "status": 200},
            "sitemap": {"present": True, "status": 200},
        },
        "eeat": {
            "byline": "Jane Doe",
            "publish_date": "2026-01-01",
            "update_date": "2026-06-01",
            "days_since_update": 10,
            "author_bio_url": "https://e.com/about",
            "same_as": ["https://x.com/j"],
            "external_citations": ["https://nih.gov/x"],
        },
        "structure": {
            "semantic_container_counts": {"article": 1, "main": 1},
            "internal_link_count": 8,
            "total_link_count": 12,
            "images_with_alt": 5,
            "images_total": 5,
        },
        "citation_content": {
            "question_headings": ["What is RAG?"],
            "definitions": ["RAG is a technique."],
            "stats_density": 1.5,
            "stats_count": 6,
            "word_count": 400,
            "language": "en",
        },
        "citation_advanced": {
            "quotations": {"count": 2, "with_attribution": 1, "sample": "q - A"},
            "readability": {"score": 72.0, "language": "en", "formula": "Flesch Reading Ease"},
            "vocab_ttr": 0.62,
            "keyword_warning": False,
            "authoritative_tone_ratio": 0.012,
            "word_count": 400,
        },
        "seo_basics": {
            "viewport_present": True,
            "viewport_content": "width=device-width, initial-scale=1",
            "descriptive_url": True,
            "url_path": "/guide/x",
        },
        "render": {
            "status": "good",
            "missing_headings": [],
            "missing_main_text_chars": 0,
            "missing_links": 0,
            "reason": "",
        },
        "bot_render": {
            "measured": True,
            "reason": "",
            "bots": {
                "gptbot": {
                    "status": "good",
                    "missing_headings": [],
                    "missing_main_text_chars": 0,
                    "missing_links": 0,
                    "reason": "",
                },
            },
        },
        "perf_vitals": {
            "lcp_ms": 2000.0,
            "inp_ms": 100.0,
            "cls": 0.05,
            "fcp_ms": 1500.0,
            "tbt_ms": 100.0,
            "speed_index_ms": 3000.0,
        },
        "perf_crux": {"lcp_p75_ms": 2000.0, "inp_p75_ms": 100.0, "cls_p75": 0.05, "has_field_data": True, "reason": ""},
        "ai_citations": {
            "brave_indexed": True,
            "brave_summary_mentions": 3,
            "common_crawl_references": 2,
            "perplexity_likely_indexed": True,
            "measured": True,
        },
        "gsc": {
            "impressions": 1200,
            "clicks": 80,
            "ctr": 0.066,
            "position": 8.5,
            "top_queries": ["q"],
            "measured": True,
        },
        "ga4": {
            "pageviews": 900,
            "avg_engagement_seconds": 45.0,
            "bounce_rate": 0.42,
            "conversions": 12,
            "measured": True,
        },
        "lighthouse": {"performance": 95, "accessibility": 95, "seo": 95, "best_practices": 95, "measured": True},
        "rich_results": {
            "eligible_types": ["Product"],
            "ineligible_types": [],
            "warnings": ["x"],
            "source": "schema",
            "measured": True,
        },
        "semrush": {
            "domain_authority": 40,
            "organic_keywords": 100,
            "organic_traffic": 5000,
            "backlinks_total": 200,
            "referring_domains": 50,
            "top_organic_keywords": ["k"],
            "paid_keywords": 5,
            "paid_traffic": 10,
            "measured": True,
        },
    }


def _doc_source_ids() -> set[str]:
    return set(_SOURCE_HEADING_RE.findall(_DOC_PATH.read_text(encoding="utf-8")))


def test_evidence_fields_round_trip() -> None:
    check = AiVisibilityCheck(
        area="Performance",
        check="Largest Contentful Paint",
        status="good",
        details="LCP 2.0s",
        recommendation="Preload the LCP image.",
        key="perf_lcp",
        evidence_class="official_standard",
        evidence_source_ids=("GOOGLE-CWV",),
    )
    restored = AiVisibilityCheck.from_raw(check.to_dict())
    assert restored == check
    assert restored.evidence_source_ids == ("GOOGLE-CWV",)


def test_doc_and_registry_in_lockstep() -> None:
    assert _doc_source_ids() == set(EVIDENCE_SOURCES), (
        "RESEARCH_CITATIONS.md and research_evidence.EVIDENCE_SOURCES drifted"
    )


def test_check_evidence_map_is_valid() -> None:
    for key, (evidence_class, source_ids) in CHECK_EVIDENCE.items():
        assert evidence_class in EVIDENCE_CLASSES, f"{key}: bad class {evidence_class!r}"
        for source_id in source_ids:
            assert source_id in EVIDENCE_SOURCES, f"{key}: unknown source {source_id!r}"
        if evidence_class in SOURCED_CLASSES:
            assert source_ids, f"{key}: sourced class {evidence_class!r} must cite a source"


def test_every_emittable_check_is_classified() -> None:
    # The tooltip dict is the canonical key registry; pin the evidence map to it
    # so a new check cannot ship unclassified.
    assert set(CHECK_EVIDENCE) == set(_AI_VISIBILITY_CHECK_TOOLTIPS)
    # And a real comprehensive audit emits only classified checks.
    checks = build_ai_visibility_checks(comprehensive_audit_raw())
    for check in checks:
        assert check.key in CHECK_EVIDENCE, f"unclassified check key: {check.key}"
        assert check.evidence_class, f"{check.key}: empty evidence_class on built check"


def test_enrichment_is_status_neutral() -> None:
    plain = AiVisibilityCheck(
        area="Citation readiness",
        check="x",
        status="warning",
        details="d",
        recommendation="r",
        key="citation_quotations",
    )
    stamped = attach_evidence(plain)
    # Verdict-bearing and copy fields are untouched; only evidence is added.
    assert (stamped.area, stamped.check, stamped.status, stamped.details, stamped.recommendation, stamped.key) == (
        plain.area,
        plain.check,
        plain.status,
        plain.details,
        plain.recommendation,
        plain.key,
    )
    assert stamped.evidence_class == "research"
    assert stamped.evidence_source_ids == ("GEO-AGGARWAL-2024",)


# --- PR-15 focused guard: effect sizes cited; sourced claims resolve ---------


def _built_checks() -> list[AiVisibilityCheck]:
    return build_ai_visibility_checks(comprehensive_audit_raw())


def test_all_built_check_sources_resolve() -> None:
    # Every sourced claim on a real built check resolves to a registered ID.
    for check in _built_checks():
        for source_id in check.evidence_source_ids:
            assert source_id in EVIDENCE_SOURCES, f"{check.key}: unresolved source {source_id!r}"
        if check.evidence_class in SOURCED_CLASSES:
            assert check.evidence_source_ids, f"{check.key}: sourced check cites no source"


def test_effect_sizes_only_in_cited_research_checks() -> None:
    # Any user-facing effect size (recommendation, details, or tooltip) must
    # belong to a research-classed check that resolves a research source.
    research_sources = {sid for sid, s in EVIDENCE_SOURCES.items() if s.evidence_class == EVIDENCE_RESEARCH}
    for check in _built_checks():
        text = " ".join((check.recommendation, check.details, ai_visibility_check_tooltip(check.key)))
        match = _EFFECT_SIZE_RE.search(text)
        if not match:
            continue
        assert check.evidence_class == EVIDENCE_RESEARCH, (
            f"{check.key}: effect size {match.group()!r} in a non-research check ({check.evidence_class})"
        )
        assert set(check.evidence_source_ids) & research_sources, (
            f"{check.key}: effect size {match.group()!r} without a resolvable research source"
        )


def test_heuristic_threshold_checks_are_labelled_heuristic() -> None:
    # The numeric-threshold GEO/engagement checks are Silentfrog heuristics, not
    # external standards or research effect sizes.
    for key in (
        "citation_readability",
        "citation_vocabulary_diversity",
        "citation_no_keyword_stuffing",
        "citation_authoritative_tone",
        "gsc_ctr_above_average",
        "ga4_engagement_above_median",
        "ga4_bounce_below_threshold",
    ):
        assert CHECK_EVIDENCE[key][0] == EVIDENCE_HEURISTIC, key


def test_doc_records_h4_operational_thresholds() -> None:
    text = _DOC_PATH.read_text(encoding="utf-8")
    assert "50,000" in text  # auto-suggest LIGHTWEIGHT threshold
    assert "25 links/page" in text  # STANDARD link-probe cap
