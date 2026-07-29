"""Evidence taxonomy for AI Visibility checks (v2.0 H6).

Every AI Visibility recommendation is classified by *how it is grounded* and,
when it cites an external claim, by *which source* backs it. This module is the
machine-checkable registry behind ``docs/RESEARCH_CITATIONS.md``:

- ``EVIDENCE_SOURCES`` — the stable source IDs (mirror of the doc). Every ID a
  check references must appear here, and the doc must document exactly this set
  (the H6 guard tests enforce both directions).
- ``CHECK_EVIDENCE`` — maps each check ``key`` to its ``(evidence_class, ids)``.
- ``attach_evidence`` — stamps a built ``AiVisibilityCheck`` with its evidence,
  applied centrally in ``ai_visibility.build_ai_visibility_checks``.

Metadata only: classification NEVER changes a check's status or the GEO score.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .crawl_types import AiVisibilityCheck

# --- Evidence classes -------------------------------------------------------
# Stable string values; persisted on the check and asserted by the guard tests.
EVIDENCE_OFFICIAL = "official_standard"  # cites a published spec / vendor doc
EVIDENCE_RESEARCH = "research"  # a measured effect size from a cited study
EVIDENCE_CORRELATION = "correlation"  # a reported/observed relationship, not causal
EVIDENCE_HEURISTIC = "silentfrog_heuristic"  # a Silentfrog editorial rule/threshold
EVIDENCE_SCORING = "silentfrog_scoring"  # product-specific scoring (e.g. _geo_score)
EVIDENCE_DESCRIPTIVE = "descriptive"  # a factual observation, no external claim

EVIDENCE_CLASSES = frozenset(
    {
        EVIDENCE_OFFICIAL,
        EVIDENCE_RESEARCH,
        EVIDENCE_CORRELATION,
        EVIDENCE_HEURISTIC,
        EVIDENCE_SCORING,
        EVIDENCE_DESCRIPTIVE,
    }
)

# Classes that make an external factual claim and therefore MUST resolve at
# least one source ID (the "sourced claim" set the H6 guard enforces).
SOURCED_CLASSES = frozenset({EVIDENCE_OFFICIAL, EVIDENCE_RESEARCH})


@dataclass(frozen=True)
class EvidenceSource:
    source_id: str
    title: str
    url: str
    evidence_class: str


# --- Source registry --------------------------------------------------------
# Keep in lockstep with docs/RESEARCH_CITATIONS.md (guard test asserts parity).
# Authoritative primary sources only — no invented citations.
_SOURCES: tuple[EvidenceSource, ...] = (
    EvidenceSource(
        "SCHEMA-ORG",
        "Schema.org vocabulary",
        "https://schema.org/",
        EVIDENCE_OFFICIAL,
    ),
    EvidenceSource(
        "GOOGLE-RICH-RESULTS",
        "Google Search Central — Structured data / rich results gallery",
        "https://developers.google.com/search/docs/appearance/structured-data/search-gallery",
        EVIDENCE_OFFICIAL,
    ),
    EvidenceSource(
        "GOOGLE-AI-FEATURES",
        "Google Search Central — AI features and your website",
        "https://developers.google.com/search/docs/appearance/ai-features",
        EVIDENCE_OFFICIAL,
    ),
    EvidenceSource(
        "GOOGLE-ROBOTS-META",
        "Google Search Central — Robots meta tag, data-nosnippet, and X-Robots-Tag",
        "https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag",
        EVIDENCE_OFFICIAL,
    ),
    EvidenceSource(
        "GOOGLE-CWV",
        "Google web.dev — Core Web Vitals and metric thresholds (LCP, INP, CLS)",
        "https://web.dev/articles/vitals",
        EVIDENCE_OFFICIAL,
    ),
    EvidenceSource(
        "LIGHTHOUSE",
        "Google Lighthouse — audit references and performance scoring",
        "https://developer.chrome.com/docs/lighthouse/overview",
        EVIDENCE_OFFICIAL,
    ),
    EvidenceSource(
        "RFC-9309",
        "RFC 9309 — Robots Exclusion Protocol",
        "https://www.rfc-editor.org/rfc/rfc9309.html",
        EVIDENCE_OFFICIAL,
    ),
    EvidenceSource(
        "GEO-AGGARWAL-2024",
        "Aggarwal et al., GEO: Generative Engine Optimization, KDD 2024 (arXiv:2311.09735)",
        "https://arxiv.org/abs/2311.09735",
        EVIDENCE_RESEARCH,
    ),
    EvidenceSource(
        "BRAVE-CLAUDE-TECHCRUNCH-2025",
        "TechCrunch (2025-03-21) — Anthropic appears to use Brave to power Claude web search",
        "https://techcrunch.com/2025/03/21/anthropic-appears-to-be-using-brave-to-power-web-searches-for-its-claude-chatbot/",
        EVIDENCE_CORRELATION,
    ),
    EvidenceSource(
        "BRAVE-SEARCH-API",
        "Brave Search API — independent web index",
        "https://brave.com/search/api/",
        EVIDENCE_OFFICIAL,
    ),
    EvidenceSource(
        "COMMON-CRAWL",
        "Common Crawl — open web crawl corpus and CDX index",
        "https://commoncrawl.org/",
        EVIDENCE_DESCRIPTIVE,
    ),
)

EVIDENCE_SOURCES: dict[str, EvidenceSource] = {source.source_id: source for source in _SOURCES}

_GEO = ("GEO-AGGARWAL-2024",)
_CWV = ("GOOGLE-CWV",)
_LH = ("LIGHTHOUSE",)
_AIF = ("GOOGLE-AI-FEATURES",)

# --- Per-check classification ----------------------------------------------
# Single source of truth for the evidence taxonomy. Keys MUST equal the set of
# check keys Silentfrog can emit (guard test pins this to the tooltip registry).
# Thresholds (TTR 0.5, readability 60, keyword 4%, pronoun 0.2%, CTR ~2%, etc.)
# are Silentfrog heuristics; GEO effect-direction claims cite GEO-AGGARWAL-2024.
CHECK_EVIDENCE: dict[str, tuple[str, tuple[str, ...]]] = {
    # Access
    "access_missing": (EVIDENCE_DESCRIPTIVE, ()),
    "access_agents": (EVIDENCE_OFFICIAL, ("RFC-9309",)),
    "access_controls": (EVIDENCE_OFFICIAL, ("GOOGLE-ROBOTS-META",)),
    "access_ssr_parity": (EVIDENCE_HEURISTIC, ()),
    "access_bot_render": (EVIDENCE_HEURISTIC, ()),
    # Site-wide discovery
    "access_llms_txt": (EVIDENCE_OFFICIAL, _AIF),
    "access_llms_full_txt": (EVIDENCE_OFFICIAL, _AIF),
    "access_well_known_ai_json": (EVIDENCE_OFFICIAL, _AIF),
    "access_sitemap": (EVIDENCE_OFFICIAL, _AIF),
    # Topic clarity
    "topic_alignment": (EVIDENCE_HEURISTIC, ()),
    "topic_language": (EVIDENCE_HEURISTIC, ()),
    "topic_depth": (EVIDENCE_HEURISTIC, ()),
    "structure_semantic_html": (EVIDENCE_OFFICIAL, _AIF),
    "structure_internal_links": (EVIDENCE_OFFICIAL, _AIF),
    "seo_viewport_mobile": (EVIDENCE_OFFICIAL, _LH),
    "seo_descriptive_url": (EVIDENCE_HEURISTIC, ()),
    # Answerability
    "answer_intro": (EVIDENCE_HEURISTIC, ()),
    "answer_chunking": (EVIDENCE_HEURISTIC, ()),
    # Citation readiness
    "citation_schema": (EVIDENCE_OFFICIAL, ("SCHEMA-ORG", "GOOGLE-RICH-RESULTS")),
    "citation_social": (EVIDENCE_HEURISTIC, ()),
    "citation_stability": (EVIDENCE_OFFICIAL, ("GOOGLE-ROBOTS-META",)),
    "citation_images_alt": (EVIDENCE_OFFICIAL, _AIF),
    "citation_question_headings": (EVIDENCE_HEURISTIC, _AIF),
    "citation_stats_density": (EVIDENCE_HEURISTIC, _GEO),
    "citation_definition_patterns": (EVIDENCE_HEURISTIC, _AIF),
    "citation_quotations": (EVIDENCE_RESEARCH, _GEO),
    "citation_readability": (EVIDENCE_HEURISTIC, _GEO),
    "citation_vocabulary_diversity": (EVIDENCE_HEURISTIC, ()),
    "citation_no_keyword_stuffing": (EVIDENCE_HEURISTIC, _GEO),
    "citation_authoritative_tone": (EVIDENCE_HEURISTIC, _GEO),
    # Entity clarity
    "entity_naming": (EVIDENCE_HEURISTIC, ()),
    "entity_schema": (EVIDENCE_OFFICIAL, ("SCHEMA-ORG",)),
    # Hreflang (Silentfrog §1.5 myth-aware policy)
    "hreflang_return_tag_complete": (EVIDENCE_HEURISTIC, ()),
    "hreflang_x_default_present": (EVIDENCE_HEURISTIC, ()),
    "hreflang_cluster_consistent": (EVIDENCE_HEURISTIC, ()),
    # E-E-A-T
    "eeat_author_byline": (EVIDENCE_HEURISTIC, ()),
    "eeat_publish_date": (EVIDENCE_HEURISTIC, ()),
    "eeat_update_freshness": (EVIDENCE_HEURISTIC, ()),
    "eeat_author_bio": (EVIDENCE_HEURISTIC, ()),
    "eeat_external_citations": (EVIDENCE_OFFICIAL, _AIF),
    # Performance — Core Web Vitals (LCP/INP/CLS, lab + field)
    "perf_lcp": (EVIDENCE_OFFICIAL, _CWV),
    "perf_inp": (EVIDENCE_OFFICIAL, _CWV),
    "perf_cls": (EVIDENCE_OFFICIAL, _CWV),
    "perf_crux_lcp": (EVIDENCE_OFFICIAL, _CWV),
    "perf_crux_inp": (EVIDENCE_OFFICIAL, _CWV),
    "perf_crux_cls": (EVIDENCE_OFFICIAL, _CWV),
    # Performance — Lighthouse-scored metrics (not Core Web Vitals)
    "perf_fcp": (EVIDENCE_OFFICIAL, _LH),
    "perf_tbt": (EVIDENCE_OFFICIAL, _LH),
    "perf_speed_index": (EVIDENCE_OFFICIAL, _LH),
    # AI Citations (optional 8th area)
    "ai_citations_brave": (EVIDENCE_CORRELATION, ("BRAVE-CLAUDE-TECHCRUNCH-2025", "BRAVE-SEARCH-API")),
    "ai_citations_common_crawl": (EVIDENCE_DESCRIPTIVE, ("COMMON-CRAWL",)),
    # V20 — topic embeddings + brand mentions
    "topic_embedding_coherence": (EVIDENCE_HEURISTIC, ()),
    "brand_mentions_visibility": (EVIDENCE_DESCRIPTIVE, ("BRAVE-SEARCH-API", "COMMON-CRAWL")),
    "brand_mentions_trend": (EVIDENCE_HEURISTIC, ()),
    # Real performance / Engagement (GSC + GA4)
    "gsc_impressions_present": (EVIDENCE_DESCRIPTIVE, ()),
    "gsc_ctr_above_average": (EVIDENCE_HEURISTIC, ()),
    "gsc_position_in_top_10": (EVIDENCE_DESCRIPTIVE, ()),
    "gsc_query_count": (EVIDENCE_DESCRIPTIVE, ()),
    "ga4_engagement_above_median": (EVIDENCE_HEURISTIC, ()),
    "ga4_bounce_below_threshold": (EVIDENCE_HEURISTIC, ()),
    # Lighthouse lab scores
    "lighthouse_perf_above_90": (EVIDENCE_OFFICIAL, _LH),
    "lighthouse_a11y_above_90": (EVIDENCE_OFFICIAL, _LH),
    "lighthouse_seo_above_90": (EVIDENCE_OFFICIAL, _LH),
    "lighthouse_freshness": (EVIDENCE_DESCRIPTIVE, ()),
    # Rich results
    "rich_results_eligible": (EVIDENCE_OFFICIAL, ("GOOGLE-RICH-RESULTS", "SCHEMA-ORG")),
    "rich_results_warning_count": (EVIDENCE_OFFICIAL, ("GOOGLE-RICH-RESULTS",)),
    # Semrush authority (off-page signals)
    "semrush_domain_authority_above_30": (EVIDENCE_HEURISTIC, ()),
    "semrush_organic_keywords_present": (EVIDENCE_DESCRIPTIVE, ()),
    "semrush_organic_traffic_above_threshold": (EVIDENCE_HEURISTIC, ()),
    "semrush_backlinks_above_threshold": (EVIDENCE_HEURISTIC, ()),
    "semrush_referring_domains_diverse": (EVIDENCE_HEURISTIC, ()),
    "semrush_paid_signal_present": (EVIDENCE_DESCRIPTIVE, ()),
    # AI Share of Voice (v3 G3 Stage 1, off-page BYO-key sampling)
    "sov_openai": (EVIDENCE_HEURISTIC, ()),
    "sov_perplexity": (EVIDENCE_HEURISTIC, ()),
    "sov_gemini": (EVIDENCE_HEURISTIC, ()),
    "sov_share": (EVIDENCE_HEURISTIC, ()),
}


def evidence_for(key: str) -> tuple[str, tuple[str, ...]]:
    """Return ``(evidence_class, source_ids)`` for a check key.

    An unmapped key returns ``("", ())`` — the H6 completeness guard fails if a
    produced check is ever unmapped, so this stays an explicit, testable gap
    rather than a silent default.
    """
    return CHECK_EVIDENCE.get(key, ("", ()))


def attach_evidence(check: AiVisibilityCheck) -> AiVisibilityCheck:
    """Stamp a built check with its evidence metadata (additive; status-neutral)."""
    evidence_class, source_ids = evidence_for(check.key)
    return replace(check, evidence_class=evidence_class, evidence_source_ids=source_ids)


def resolve_source(source_id: str) -> EvidenceSource | None:
    return EVIDENCE_SOURCES.get(source_id)


__all__ = [
    "CHECK_EVIDENCE",
    "EVIDENCE_CLASSES",
    "EVIDENCE_SOURCES",
    "EVIDENCE_CORRELATION",
    "EVIDENCE_DESCRIPTIVE",
    "EVIDENCE_HEURISTIC",
    "EVIDENCE_OFFICIAL",
    "EVIDENCE_RESEARCH",
    "EVIDENCE_SCORING",
    "EvidenceSource",
    "SOURCED_CLASSES",
    "attach_evidence",
    "evidence_for",
    "resolve_source",
]
