from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from .ai_citations import AiCitationsPayload, build_ai_citations_checks
from .citation_advanced import AdvancedCitationPayload, build_advanced_citation_checks
from .citation_readiness_content import CitationContentPayload, build_citation_content_checks
from .crawl_types import (
    AiVisibilityCheck,
    AiVisibilityPayload,
    AiVisibilitySummary,
    CanonicalInfo,
    ContentQuality,
    CrawlPayload,
    RedirectInfo,
    SocialPayload,
    StructuredDataPayload,
)
from .discovery_files import DiscoveryPayload, build_discovery_checks
from .eeat_signals import EeatPayload, build_eeat_checks
from .hreflang_validator import build_hreflang_checks
from .integrations.google.checks import (
    build_lighthouse_checks,
    build_real_performance_checks,
    build_rich_results_checks,
)
from .integrations.google.lighthouse import LighthouseScores
from .integrations.google.rich_results import RichResultsReport
from .integrations.google.types import Ga4Metrics, GscMetrics
from .integrations.semrush.checks import build_semrush_authority_checks
from .integrations.semrush.types import SemrushMetrics
from .perf_crux import CruxData
from .perf_vitals import WebVitals, build_performance_checks
from .render_diff import RenderDiff, build_render_diff_check
from .seo_basics import SeoBasicsPayload, build_seo_basics_checks
from .structure_signals import StructurePayload, build_structure_checks

AI_VISIBILITY_AREAS = (
    "Access",
    "Topic clarity",
    "Answerability",
    "Citation readiness",
    "Entity clarity",
    "Hreflang",
    "E-E-A-T",
    "Performance",
    # v2.0 V7 — only populated when Google Search Console / GA4 are connected.
    "Real performance",
    "Engagement",
    # v2.0 V17 — only populated when Semrush is connected (optional).
    "Authority signals",
)

_STATUS_ALIASES = {
    "ok": "good",
    "pass": "good",
    "good": "good",
    "info": "good",
    "warn": "warning",
    "warning": "warning",
    "needs work": "warning",
    "bad": "critical",
    "risk": "critical",
    "critical": "critical",
    "blocked": "critical",
}

_VERDICT_STRONG = "Strong"
_VERDICT_NEEDS_WORK = "Needs work"
_VERDICT_WEAK = "Weak"
_WORD_RE = re.compile(r"[^\W\d_]+(?:['\u2019-][^\W\d_]+)*", re.UNICODE)
_SOCIAL_TITLE_SIMILARITY = 0.6
_ENTITY_SCHEMA_TYPES = {"organization", "localbusiness", "product", "article", "person", "service"}
_RICH_SCHEMA_TYPES = {
    "organization",
    "localbusiness",
    "product",
    "article",
    "faqpage",
    "breadcrumblist",
    "howto",
    "website",
}
_AI_VISIBILITY_SUMMARY_TOOLTIP = (
    "AI Visibility combines five signals: Access, Topic clarity, Answerability, Citation readiness, "
    "and Entity clarity.\n\n"
    "Verdict meanings:\n"
    "- Strong: the page is accessible to major AI agents and only minor issues were found.\n"
    "- Needs work: the page is partially limited or several warning-level signals reduce reuse quality.\n"
    "- Weak: AI access is blocked or multiple critical issues make the page hard to reuse or summarize.\n\n"
    "Best practice: keep the page accessible, explicit, well-structured, and supported by stable metadata. "
    "This is a heuristic visibility audit, not a guarantee of citation or ranking in AI products."
)
_AI_VISIBILITY_CHECK_TOOLTIPS = {
    "access_missing": (
        "Checks whether Silentfrog had enough AI access data to evaluate the page.\n\n"
        "Best practice: make sure robots.txt, meta robots, and response headers are reachable so access "
        "signals can be audited reliably."
    ),
    "access_agents": (
        "Checks whether the audited AI and search-facing agents can fetch the page URL.\n\n"
        "Best practice: allow the official user-agent tokens you want in robots.txt and avoid "
        "blocking them with conflicting path rules.\n\n"
        "Claude note: Claude uses Brave Search's index, not Google's. Verify Brave indexing separately "
        "if Claude citations matter (Princeton 2024 seo-geo signal)."
    ),
    "access_controls": (
        "Checks whether standard Google search controls or nonstandard AI directives may limit reuse.\n\n"
        "Best practice: remove nosnippet, noindex, or restrictive max-snippet directives if you want "
        "Google search and AI surfaces to reuse the page more freely. Treat nonstandard directives such "
        "as noai or noimageai as advisory unless you have vendor-specific confirmation they are honored."
    ),
    "topic_alignment": (
        "Checks whether the title and H1 describe the same primary topic.\n\n"
        "Best practice: keep one descriptive title and one clear H1 aligned on the same entity or page intent."
    ),
    "topic_language": (
        "Checks whether the page declares its main language.\n\n"
        "Best practice: set a valid <html lang> that matches the visible content language."
    ),
    "topic_depth": (
        "Checks whether the page has enough original content to explain the topic.\n\n"
        "Best practice: avoid thin pages and provide enough topical detail for search engines and AI systems "
        "to summarize confidently."
    ),
    "answer_intro": (
        "Checks whether the page explains its topic early with a concise intro or summary paragraph.\n\n"
        "Best practice: answer the core question in the first visible content block."
    ),
    "answer_chunking": (
        "Checks whether the content is segmented into clear, reusable sections.\n\n"
        "Best practice: use a logical heading hierarchy and self-contained paragraphs instead of long "
        "unbroken text blocks."
    ),
    "citation_schema": (
        "Checks whether supported structured data helps machines interpret the page and its main entity.\n\n"
        "Best practice: provide valid Organization, Article, Product, FAQ, or Breadcrumb schema when relevant.\n\n"
        "Breadcrumb note: Lighthouse's SEO audit categorises Breadcrumb schema as a high-priority structured "
        "data signal (Addy Osmani web-quality skill)."
    ),
    "citation_social": (
        "Checks whether social metadata is complete enough to represent the page consistently outside the body copy.\n\n"
        "Best practice: keep OpenGraph and Twitter title/description fields complete and aligned with the page."
    ),
    "citation_stability": (
        "Checks whether the page is a stable, indexable canonical source.\n\n"
        "Best practice: use a self-canonical, avoid unnecessary redirects, and do not apply noindex to pages "
        "you want cited."
    ),
    "entity_naming": (
        "Checks whether the same entity or topic wording is used across title, H1, and social metadata.\n\n"
        "Best practice: keep naming consistent so AI systems do not have to guess which entity the page is about."
    ),
    "entity_schema": (
        "Checks whether entity-supporting schema is present for the kind of page being audited.\n\n"
        "Best practice: add the most relevant entity schema type, such as Organization, LocalBusiness, "
        "Product, Article, Service, or Person.\n\n"
        "FAQPage note: Princeton 2024 GEO research measured FAQPage schema correlating with +40% AI "
        "visibility — the largest schema-driven boost. Perplexity in particular prioritises FAQPage-shaped content."
    ),
    "hreflang_return_tag_complete": (
        "Checks whether every hreflang alternate links back to this page (return-tag reciprocity).\n\n"
        "Per §1.5: reciprocity can only be confirmed by crawling the alternates as a cluster. Without a "
        "cluster this stays info when reciprocity is unconfirmable and good when the page self-references; "
        "it NEVER warns. With a cluster, an alternate that fails to link back => warning."
    ),
    "hreflang_x_default_present": (
        "Checks whether an x-default hreflang is declared for multi-language pages.\n\n"
        "Per §1.5 x-default is recommended, not required: present or single-language => good; multiple "
        "languages without it => info. NEVER warned."
    ),
    "hreflang_cluster_consistent": (
        "Checks whether the hreflang set is internally consistent and (when a cluster is supplied) symmetric.\n\n"
        "Per §1.5: a genuine in-set defect — duplicate language codes or a malformed lang value, or a "
        "cluster that diverges — => warning. A sound or merely unconfirmable set => good or info. "
        "Absence of a cluster never forces a warning."
    ),
    "access_llms_txt": (
        "Checks whether the site publishes an llms.txt declaring policies and entry points "
        "for AI crawlers.\n\n"
        "Per Google's AI Optimization Guide this file is NOT required to appear in Google's AI surfaces; "
        "some other AI engines (Anthropic, Perplexity, OpenAI) treat its presence as a positive signal. "
        "Absent => info; present => good. Never warned."
    ),
    "access_llms_full_txt": (
        "Checks whether the site publishes an llms-full.txt with the long-form policy and "
        "structured content map.\n\n"
        "Per Google's AI Optimization Guide this file is NOT required; same Google-not-required rule "
        "as access_llms_txt: absent => info, present => good."
    ),
    "access_well_known_ai_json": (
        "Checks whether the site publishes /.well-known/ai.json with a machine-readable AI access policy.\n\n"
        "Per Google's AI Optimization Guide this file is NOT required: absent => info, present => good. "
        "Useful only for engines that explicitly read the file."
    ),
    "access_sitemap": (
        "Checks whether a sitemap.xml is discoverable via a Sitemap: directive in robots.txt "
        "or at the site root.\n\n"
        "Best practice: publish a sitemap and reference it in robots.txt. Per Google's AI Optimization Guide, "
        "sitemap is part of standard crawlability hygiene; not specific to AI. "
        "Absent => info, present => good. Never warned."
    ),
    "eeat_author_byline": (
        "Checks whether the page exposes a visible author byline near the title.\n\n"
        "Best practice: show the author name in the page body and link it to a stable profile."
    ),
    "eeat_publish_date": (
        "Checks whether the page declares a publish date a generative engine can attribute.\n\n"
        "Best practice: expose datePublished (or a visible publication date) so AI systems can date the claim."
    ),
    "eeat_update_freshness": (
        "Checks whether the page was updated within the configured freshness window.\n\n"
        "Best practice: maintain dateModified (or a visible last-update marker) and refresh evergreen pages "
        "within the SILENTFROG_EEAT_FRESHNESS_DAYS threshold (default 365).\n\n"
        "ChatGPT note: Princeton 2024 measured 30-day updates correlating with 3.2x more citations from ChatGPT."
    ),
    "eeat_author_bio": (
        "Checks whether the author has a discoverable bio or sameAs link.\n\n"
        "Best practice: link the byline to an /about page, a Person schema with sameAs, or a stable external profile."
    ),
    "eeat_external_citations": (
        "Checks whether the page cites a small number of named, authoritative external sources.\n\n"
        "Best practice: link standards bodies, peer-reviewed work, or primary docs when relevant. "
        "Per Google's AI Optimization Guide, QUALITY matters more than quantity; manufactured or "
        "inauthentic mentions do NOT help. Absent => info; never recommends pursuing mentions."
    ),
    "structure_semantic_html": (
        "Checks whether the page uses semantic HTML containers (article, section, main, nav, header, footer) "
        "instead of generic div soup.\n\n"
        "Best practice: structure the page with semantic landmarks. Per Google's AI Optimization Guide, "
        "semantic HTML aids machine understanding without any AI-specific markup. "
        "Absent => info, present => good. Never warned."
    ),
    "structure_internal_links": (
        "Checks whether the page links to related internal pages.\n\n"
        "Best practice: a small set of contextual internal links to deeper or related content. "
        "Per Google's AI Optimization Guide, internal architecture that helps crawlers and readers is "
        "standard SEO hygiene. Absent => info, present => good. Never warned."
    ),
    "citation_images_alt": (
        "Checks whether content images carry meaningful alt text.\n\n"
        "Best practice: descriptive alt per image. Per Google's AI Optimization Guide, image SEO is part "
        "of standard hygiene. The detailed image audit lives in the Images tab; this row summarises it "
        "for GEO. Absent => info, present => good. Never warned."
    ),
    "citation_question_headings": (
        "Checks whether H2/H3 headings are phrased as questions that the body answers.\n\n"
        "Per Google's AI Optimization Guide you do NOT need to rewrite content specifically for "
        "generative AI search; question-form headings are a positive signal where they fit the natural "
        "editorial style. Present => good; absent => info. Never warned.\n\n"
        "Perplexity note: Perplexity in particular prioritises FAQ-shaped content with question-form "
        "headings for AI citation (Princeton 2024 seo-geo signal)."
    ),
    "citation_stats_density": (
        "Checks whether the page contains specific numbers, dates, and units AI engines can quote.\n\n"
        "Best practice: include concrete data points (percentages, monetary values, dated events) when "
        "they are accurate and supportable. Warning only when zero quantitative tokens are found."
    ),
    "citation_definition_patterns": (
        'Checks whether the page defines its key terms with clear "X is Y" sentences.\n\n'
        "Per Google's AI Optimization Guide this is a positive signal, never a requirement. Present => good; "
        "absent => info. Never warned. Best practice: where it fits the editorial style, open sections with "
        "a one-sentence definition."
    ),
    "access_ssr_parity": (
        "Checks whether the page rendered without JavaScript matches what a JS-capable engine would see.\n\n"
        "Best practice: render critical content server-side; AI crawlers commonly fetch without executing JS. "
        "When Playwright is not installed this check reports 'not measured' (status=info) and does not "
        "affect the verdict. Enable in Crawl settings after installing silentfrog[geo-render]."
    ),
    "perf_lcp": (
        "Largest Contentful Paint — lab measurement via Playwright CDP. Google's threshold: <2.5s good, "
        "<4s warn, >=4s critical. Bing also weights <2s for AI Answer eligibility (Princeton seo-geo signal).\n\n"
        "Best practice: preload the LCP image, inline critical CSS, defer non-critical JS."
    ),
    "perf_inp": (
        "Interaction to Next Paint — lab measurement of how responsive the page is to the first interaction. "
        "Google's threshold: <200ms good, <500ms warn, >=500ms critical.\n\n"
        "Best practice: break up long main-thread tasks; defer non-essential third-party scripts."
    ),
    "perf_cls": (
        "Cumulative Layout Shift — lab measurement of unexpected layout movement during page load. "
        "Google's threshold: <0.1 good, <0.25 warn, >=0.25 critical.\n\n"
        "Best practice: reserve dimensions on images and ads; avoid inserting content above existing content."
    ),
    "perf_fcp": (
        "First Contentful Paint — lab measurement of when the first text or image renders. Google's "
        "threshold: <1.8s good, <3s warn, >=3s critical.\n\n"
        "Best practice: inline critical CSS, eliminate render-blocking resources, edge-cache HTML."
    ),
    "perf_tbt": (
        "Total Blocking Time — lab measurement of main-thread blocking time between FCP and TTI. "
        "Google's threshold: <200ms good, <600ms warn, >=600ms critical.\n\n"
        "Best practice: code-split bundles; defer non-essential third-party scripts; remove unused JS."
    ),
    "perf_speed_index": (
        "Speed Index — how quickly content visually populates during page load. Google's threshold: "
        "<3.4s good, <5.8s warn, >=5.8s critical.\n\n"
        "Best practice: optimise the above-the-fold critical path; lazy-load below-the-fold media."
    ),
    "perf_crux_lcp": (
        "Field LCP — Google's CrUX dataset P75 from real Chrome users in the last 28 days. Same thresholds "
        "as lab LCP (2.5s/4s). Field data is the source of truth for ranking; lab data is the debugging tool.\n\n"
        "Best practice: prioritise improvements to field LCP; lab improvements should reflect in field within ~28 days. "
        "When CrUX has no field data for the URL (low traffic), this check reports 'not measured' and does not affect the GEO Score."
    ),
    "perf_crux_inp": (
        "Field INP — CrUX P75 from real Chrome users. Same thresholds as lab INP (200ms/500ms). Reflects the "
        "actual interaction profile of real users; lab INP only measures one synthetic interaction.\n\n"
        "Best practice: triage real-user interactions; replays from Chrome User Experience Report are the gold standard."
    ),
    "perf_crux_cls": (
        "Field CLS — CrUX P75 from real Chrome users. Same thresholds as lab CLS (0.1/0.25). Field CLS often "
        "differs from lab when the page injects layout-shifting content on user scroll or interaction.\n\n"
        "Best practice: monitor field CLS as the canonical signal; lab CLS misses scroll-triggered shifts."
    ),
    # v1.1 N2 — Princeton GEO method coverage.
    "citation_quotations": (
        "Checks whether the page contains quotations with named attribution (blockquote, q, or attribution dash).\n\n"
        "Princeton 2024 GEO research measured +30% AI visibility from QUOTATION ADDITION (quality over quantity). "
        "Quote experts with attribution where it fits the editorial voice. Absent => info; present => good."
    ),
    "citation_readability": (
        "Checks the page's readability score against the AI-friendly band.\n\n"
        "English uses Flesch Reading Ease (target >= 60). Italian uses Indice Gulpease (target >= 60). "
        "Princeton 2024 measured +20% AI visibility from easier-to-understand text. "
        "Other languages route to info — language-guard fallback."
    ),
    "citation_vocabulary_diversity": (
        "Checks vocabulary diversity via type-token ratio (unique tokens / total tokens).\n\n"
        "Princeton 2024 GEO research measured +15% AI visibility from UNIQUE WORDS — increased "
        "vocabulary diversity and distinctive phrasing. TTR >= 0.5 is a healthy band for editorial prose. "
        "Absent => info; present => good."
    ),
    "citation_no_keyword_stuffing": (
        "Checks whether the page's top keyword density stays below the anti-stuffing threshold.\n\n"
        "Princeton 2024 GEO research measured -10% AI visibility from KEYWORD STUFFING — actively "
        "penalised by AI engines. Default threshold 4% (env: SILENTFROG_KEYWORD_WARN_DENSITY). "
        "Above threshold => warning; at or below => good."
    ),
    "citation_authoritative_tone": (
        "Checks first/second-person pronoun density as a proxy for authoritative editorial voice.\n\n"
        "Princeton 2024 GEO research measured +25% AI visibility from AUTHORITATIVE TONE. "
        "Healthy band: >=0.2% of tokens are we/you/our/your. Below threshold => info; never warned."
    ),
    "seo_viewport_mobile": (
        "Checks whether the page declares a mobile-responsive viewport meta tag.\n\n"
        'Best practice: `<meta name="viewport" content="width=device-width, initial-scale=1">` in <head>. '
        "Per Google Search Central + Addy Osmani web-quality SEO checklist, this is a Lighthouse "
        "high-priority SEO check. Absent => info; present => good."
    ),
    "seo_descriptive_url": (
        "Checks whether the URL slug is descriptive (lowercase, no UUIDs, no 4+ consecutive digit runs, "
        "<=80 chars).\n\n"
        "Per Addy Osmani's web-quality SEO checklist, descriptive URLs sit in the 'high' tier of "
        "technical SEO. Non-descriptive slugs (UUIDs, long digit IDs) make URLs less quotable. "
        "Bad shape => info; good shape => good."
    ),
    # v1.1 N4a — cross-engine AI citation tracking (optional 8th area).
    "ai_citations_brave": (
        "Probes Brave Search to see whether the URL is indexed AND whether Brave's AI summary mentions "
        "the netloc.\n\n"
        "Brave is Claude's primary search index. If a URL isn't in Brave it's effectively invisible to "
        "Claude regardless of other SEO work. Gated behind SILENTFROG_AI_CITATIONS_ENABLE + "
        "SILENTFROG_BRAVE_API_KEY env vars. Brave free tier: 2,000 queries/month per key. "
        "Not measured => info; indexed => good; absent from Brave => warning."
    ),
    "ai_citations_common_crawl": (
        "Probes Common Crawl's CDX index to see whether the URL has been seen in the most recent crawl.\n\n"
        "Common Crawl powers the training and citation paths of many open AI engines (GPT-3.5 era, "
        "Anthropic's older Claude, Together, etc.). Index lags by ~3 months — positioned as a "
        "'historical' signal alongside Brave's fresh signal. Free and public, no API key required."
    ),
    "ai_citations_perplexity": (
        "Heuristic — whether Perplexity likely indexes the URL.\n\n"
        "Perplexity composes from Brave + Bing-shaped indexes; we don't have a public API to query "
        "Perplexity directly, so this signal is currently inferred from Brave presence. "
        "Not measured => info; likely indexed => good."
    ),
    # v2.0 V7 — Google Search Console + GA4 (optional `silentfrog[google]`).
    "gsc_impressions_present": (
        "Real Search Console impressions + clicks for this URL over the last 28 days.\n\n"
        "Connect via Settings -> Connect Google Search Console (or set SILENTFROG_GOOGLE_ENABLE=1 + "
        "SILENTFROG_GSC_SITE_URL). Not connected => info; never penalises the score."
    ),
    "gsc_ctr_above_average": (
        "Click-through rate from Search Console.\n\n"
        "CTR at/above ~2% is a good signal; below average suggests the title/meta description "
        "isn't earning the click despite impressions. Not connected => info."
    ),
    "gsc_position_in_top_10": (
        "Average Search Console position for this URL.\n\n"
        "Position <= 10 means page-one presence. Good when in the top 10; otherwise informational."
    ),
    "gsc_query_count": (
        "The top queries Search Console attributes to this URL — useful for confirming the page "
        "ranks for the topic you intended. Info-only."
    ),
    "ga4_engagement_above_median": (
        "Average GA4 engagement time for this URL.\n\n"
        "Higher engagement time indicates the content holds visitors. Connect via Settings -> "
        "Connect Google Analytics 4 (or SILENTFROG_GA4_PROPERTY_ID). Not connected => info."
    ),
    "ga4_bounce_below_threshold": (
        "GA4 bounce rate for this URL.\n\n"
        "Bounce above ~70% is a warning — visitors leave without engaging, often an above-the-fold "
        "relevance or intent-match problem. Below the threshold => good."
    ),
    "lighthouse_perf_above_90": (
        "Lighthouse Performance lab score (0-100) from PageSpeed Insights.\n\n"
        "A measured score below 90 warns; 90+ is good. The lab run is slow and opt-in, so until you "
        "click Run Lighthouse on the page audit this stays info (never penalised, per §1.5)."
    ),
    "lighthouse_a11y_above_90": (
        "Lighthouse Accessibility lab score (0-100).\n\n"
        "Below 90 warns; 90+ is good. Only evaluated after the opt-in single-page Lighthouse run; "
        "otherwise info."
    ),
    "lighthouse_seo_above_90": (
        "Lighthouse SEO lab score (0-100).\n\n"
        "Below 90 warns; 90+ is good. Only evaluated after the opt-in single-page Lighthouse run; "
        "otherwise info."
    ),
    "lighthouse_freshness": (
        "When the Lighthouse lab run was fetched, plus the Best-practices score.\n\n"
        "Informational context for the scores above; never affects the GEO Score."
    ),
    "rich_results_eligible": (
        "Whether the page has rich-result-eligible structured data.\n\n"
        "Derived from the page's own schema (Google retired the public Rich Results Test API), upgraded "
        "to Google's real verdict when the site is Search-Console-connected. No eligible markup => info, "
        "never a penalty (§1.5)."
    ),
    "rich_results_warning_count": (
        "Count of structured-data warnings that threaten rich-result eligibility.\n\n"
        "These are genuine defects in markup the page already ships, so they warn. Zero warnings => good."
    ),
    # v2.0 V17 — Semrush authority signals (optional `silentfrog[semrush]`).
    "semrush_domain_authority_above_30": (
        "Semrush Authority Score (0-100) for the domain.\n\n"
        "A higher score reflects a stronger, harder-to-fake link profile that AI engines and search "
        "treat as a trust signal. Connect via Settings -> Authority (Semrush). This is an off-page "
        "signal the page does not control cheaply, so per §1.5 it is good above 30 and otherwise info, "
        "never a penalty. Not connected => info."
    ),
    "semrush_organic_keywords_present": (
        "Count of organic keywords the domain ranks for, per Semrush.\n\n"
        "A broad ranking footprint signals topical breadth and crawl-worthiness. Present => good; "
        "absent or not connected => info. Never penalises the GEO Score (§1.5)."
    ),
    "semrush_organic_traffic_above_threshold": (
        "Estimated monthly organic traffic for the domain, per Semrush.\n\n"
        "A meaningful organic traffic base correlates with the authority AI engines reward. Above the "
        "threshold => good; below or not connected => info. Off-page signal — never a penalty (§1.5)."
    ),
    "semrush_backlinks_above_threshold": (
        "Total backlinks pointing at the domain, per Semrush.\n\n"
        "Volume is a coarse signal — quality and diversity matter more — so this routes good above the "
        "threshold and info otherwise, never a warning. Not connected => info."
    ),
    "semrush_referring_domains_diverse": (
        "Count of unique referring domains, per Semrush.\n\n"
        "Diversity of distinct linking domains is a stronger authority signal than raw backlink count. "
        "Above the threshold => good; below or not connected => info. Never a penalty (§1.5)."
    ),
    "semrush_paid_signal_present": (
        "Whether the domain runs paid search (paid keywords / traffic), per Semrush.\n\n"
        "Purely informational context on the domain's marketing footprint; it neither helps nor hurts "
        "the GEO Score. Present => good; absent or not connected => info."
    ),
}


def normalize_ai_visibility_status(value: str) -> str:
    return _STATUS_ALIASES.get(str(value or "").strip().lower(), "warning")


def ai_visibility_summary_tooltip() -> str:
    return _AI_VISIBILITY_SUMMARY_TOOLTIP


def ai_visibility_check_tooltip(key: str) -> str:
    normalized = str(key or "").strip().lower()
    return _AI_VISIBILITY_CHECK_TOOLTIPS.get(
        normalized,
        (
            "This row evaluates a signal that affects how easy the page is to access, understand, and reuse in "
            "AI-generated answers.\n\nBest practice: keep the page accessible, explicit, and well-structured."
        ),
    )


def _coerce_check(value: AiVisibilityCheck | Mapping[str, Any]) -> AiVisibilityCheck:
    if isinstance(value, AiVisibilityCheck):
        return value
    if isinstance(value, Mapping):
        return AiVisibilityCheck.from_raw(value)
    raise TypeError("AI visibility checks must be AiVisibilityCheck instances or mappings")


def _geo_score(warning_count: int, critical_count: int) -> int:
    """GEO Score 0..100 per docs/geo_roadmap.md §Context decision 3.

    Formula: ``max(0, min(100, 100 - 4 * warnings - 10 * criticals))``.
    """
    return max(0, min(100, 100 - 4 * warning_count - 10 * critical_count))


def build_ai_visibility_summary(
    checks: Iterable[AiVisibilityCheck | Mapping[str, Any]],
) -> AiVisibilitySummary:
    items = [_coerce_check(item) for item in checks]
    if not items:
        return AiVisibilitySummary.empty()

    # Normalise so "info" rows fold into "good" (§1.5 alias), keeping the
    # tab summary, GEO Score, and verdict consistent with the tooltip text.
    normalised = [normalize_ai_visibility_status(item.status) for item in items]
    counts = Counter(normalised)
    critical_count = counts.get("critical", 0)
    warning_count = counts.get("warning", 0)
    good_count = counts.get("good", 0)
    access_statuses = {normalize_ai_visibility_status(item.status) for item in items if item.area == "Access"}

    verdict = _VERDICT_STRONG
    if "critical" in access_statuses or critical_count >= 2 or (critical_count == 1 and warning_count >= 2):
        verdict = _VERDICT_WEAK
    elif "warning" in access_statuses or critical_count == 1 or warning_count >= 2:
        verdict = _VERDICT_NEEDS_WORK

    return AiVisibilitySummary(
        verdict=verdict,
        good_count=good_count,
        warning_count=warning_count,
        critical_count=critical_count,
        score=_geo_score(warning_count, critical_count),
    )


def _token_set(value: str) -> set[str]:
    return {token.casefold() for token in _WORD_RE.findall(value or "")}


def _overlap_ratio(left: str, right: str) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    smallest = min(len(left_tokens), len(right_tokens)) or 0
    return len(left_tokens & right_tokens) / smallest if smallest else 0.0


def _payload_mapping(value: CrawlPayload | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(value, CrawlPayload):
        return value.to_mapping()
    if isinstance(value, Mapping):
        return value
    raise TypeError("AI visibility analyzer expects CrawlPayload or mapping input")


def _resolve_page_url(data: Mapping[str, Any]) -> str:
    """Page URL used by URL-dependent checks (e.g. hreflang).

    Priority: the post-redirect ``final_url``, then the originally
    ``requested_url``, then a legacy top-level ``url`` key for pre-H0 blobs.
    Empty/missing values fall through; nothing resolved → ``""``."""
    return str(data.get("final_url") or data.get("requested_url") or data.get("url") or "")


def _rows(value: Any) -> list[list[str]]:
    return (
        [
            [str(cell) for cell in row]
            for row in value
            if isinstance(row, Iterable) and not isinstance(row, (str, bytes))
        ]
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes))
        else []
    )


def _title_from_meta(meta_rows: list[list[str]]) -> str:
    return next((row[1].strip() for row in meta_rows if len(row) > 1 and row[0].strip().lower() == "title"), "")


def _first_h1(header_rows: list[list[str]]) -> str:
    return next((row[1].strip() for row in header_rows if len(row) > 1 and row[0].strip().lower() == "h1"), "")


def _schema_type_sets(schema: StructuredDataPayload) -> tuple[set[str], set[str], set[str]]:
    all_types = {entry.schema_type.casefold() for entry in schema.eligibility if entry.schema_type}
    eligible = {
        entry.schema_type.casefold()
        for entry in schema.eligibility
        if entry.schema_type and entry.eligibility.casefold() == "eligible"
    }
    detected = {entry.schema_type.casefold() for entry in schema.eligibility if entry.schema_type and entry.detected}
    return all_types, eligible, detected


def _check(
    area: str,
    check: str,
    status: str,
    details: str,
    recommendation: str,
    key: str,
) -> AiVisibilityCheck:
    return AiVisibilityCheck(
        area=area,
        check=check,
        status=normalize_ai_visibility_status(status),
        details=details,
        recommendation=recommendation,
        key=key,
    )


def _build_access_checks(ai_rows: list[list[str]]) -> list[AiVisibilityCheck]:
    if not ai_rows:
        return [
            _check(
                "Access",
                "AI crawler access could not be evaluated",
                "warning",
                "No AI crawl rows were available for this page.",
                "Run the page analysis again and verify robots.txt and meta robots signals are available.",
                "access_missing",
            )
        ]

    blocked = [row[0] for row in ai_rows if len(row) > 5 and row[5] == "Blocked"]
    limited = [row[0] for row in ai_rows if len(row) > 5 and row[5] == "Limited"]
    allowed = [row[0] for row in ai_rows if len(row) > 5 and row[5] == "Allowed"]
    search_controls = [row[4] for row in ai_rows if len(row) > 4 and row[4] != "-"]
    nonstandard_directives = [row[3] for row in ai_rows if len(row) > 3 and row[3] != "-"]
    status = "good" if not blocked and not limited else "warning"
    status = "critical" if blocked else status
    details = (
        f"Allowed: {', '.join(allowed) or '-'}; "
        f"Limited: {', '.join(limited) or '-'}; "
        f"Blocked: {', '.join(blocked) or '-'}."
    )
    access_check = _check(
        "Access",
        "Audited AI and search agents can access the page",
        status,
        details,
        "Keep robots.txt open for the official AI and search agents you want to allow.",
        "access_agents",
    )
    controls_status = "warning" if nonstandard_directives or search_controls else "good"
    controls_detail = "Nonstandard directives: {directives}; Google search controls: {controls}.".format(
        directives=", ".join(dict.fromkeys(nonstandard_directives)) or "-",
        controls=", ".join(dict.fromkeys(search_controls)) or "-",
    )
    controls_check = _check(
        "Access",
        "Reuse restrictions are limited",
        controls_status,
        controls_detail,
        "Remove Google search controls or nonstandard AI directives if you want broader reuse, but verify vendor support before treating nonstandard directives as blockers.",
        "access_controls",
    )
    return [access_check, controls_check]


def _build_topic_clarity_checks(
    quality: ContentQuality,
    title: str,
    h1: str,
) -> list[AiVisibilityCheck]:
    alignment_status = (
        "good"
        if quality.title_present and quality.h1_count == 1 and quality.title_h1_alignment in {"Aligned", "Exact match"}
        else "warning"
    )
    alignment_status = "critical" if not quality.title_present or quality.h1_count == 0 else alignment_status
    topic_alignment = _check(
        "Topic clarity",
        "The page states a clear primary topic",
        alignment_status,
        f"Title present: {'Yes' if quality.title_present else 'No'}; H1 count: {quality.h1_count}; Title/H1: {quality.title_h1_alignment or '-'}.",
        "Keep one descriptive title and one clear H1 that express the same core topic.",
        "topic_alignment",
    )
    language_status = "good" if quality.language and quality.language != "Not declared" else "warning"
    language_check = _check(
        "Topic clarity",
        "The page language is explicit",
        language_status,
        f"Declared language: {quality.language or 'Not declared'}.",
        "Declare a valid html lang that matches the main visible content language.",
        "topic_language",
    )
    depth_map = {"Low": "good", "Medium": "warning", "High": "critical"}
    depth_check = _check(
        "Topic clarity",
        "The page has enough topical depth",
        depth_map.get(quality.thin_content_risk, "warning"),
        (
            f"Word count: {quality.word_count}; Paragraphs: {quality.paragraph_count}; "
            f"Thin-content risk: {quality.thin_content_risk or '-'}."
        ),
        "Add enough original, on-topic copy to satisfy the page intent and support summarization.",
        "topic_depth",
    )
    return [topic_alignment, language_check, depth_check]


def _build_answerability_checks(quality: ContentQuality) -> list[AiVisibilityCheck]:
    intro_status = "good" if quality.intro_paragraph == "Present" else "warning"
    intro_check = _check(
        "Answerability",
        "The page answers the topic early",
        intro_status,
        f"Intro paragraph: {quality.intro_paragraph or '-'}; Overall content verdict: {quality.verdict or '-'}.",
        "Add a concise opening paragraph that explains the page topic immediately.",
        "answer_intro",
    )
    chunking_status = (
        "good" if quality.heading_structure == "Good" and quality.substantial_paragraph_count >= 2 else "warning"
    )
    chunking_status = "critical" if quality.heading_structure in {"Missing H1", "Multiple H1s"} else chunking_status
    chunking_check = _check(
        "Answerability",
        "The content is easy to chunk into answerable sections",
        chunking_status,
        (
            f"Heading structure: {quality.heading_structure or '-'}; "
            f"Substantial paragraphs: {quality.substantial_paragraph_count}; "
            f"Average words/paragraph: {quality.average_words_per_paragraph:.1f}."
        ),
        "Use clear heading hierarchy and several meaningful paragraphs instead of dense or fragmented copy.",
        "answer_chunking",
    )
    return [intro_check, chunking_check]


def _build_citation_checks(
    schema: StructuredDataPayload,
    social: SocialPayload,
    canonical: CanonicalInfo,
    redirect: RedirectInfo,
    meta_robots: str,
) -> list[AiVisibilityCheck]:
    all_types, eligible_types, detected_types = _schema_type_sets(schema)
    schema_status = "good" if eligible_types & _RICH_SCHEMA_TYPES else "warning"
    schema_status = (
        "critical" if detected_types & _RICH_SCHEMA_TYPES and not eligible_types & _RICH_SCHEMA_TYPES else schema_status
    )
    schema_check = _check(
        "Citation readiness",
        "Structured data supports interpretation and citation",
        schema_status,
        "Eligible schema: {eligible}; Detected schema: {detected}; Summary errors: {errors}.".format(
            eligible=", ".join(sorted(eligible_types)) or "-",
            detected=", ".join(sorted(detected_types or all_types)) or "-",
            errors=", ".join(schema.summary.errors[:3]) or "-",
        ),
        "Add or complete supported schema such as Organization, Article, Product, FAQ, or Breadcrumb.",
        "citation_schema",
    )
    social_cards = (social.open_graph, social.twitter)
    complete_cards = sum(bool(card.title and card.description) for card in social_cards)
    social_status = "good" if complete_cards == 2 else "warning"
    social_check = _check(
        "Citation readiness",
        "Cross-surface metadata is present",
        social_status,
        f"OpenGraph title/description: {'Yes' if social.open_graph.title and social.open_graph.description else 'No'}; "
        f"Twitter title/description: {'Yes' if social.twitter.title and social.twitter.description else 'No'}.",
        "Keep OpenGraph and Twitter metadata complete so the page is consistently represented outside the page body.",
        "citation_social",
    )
    meta_directives = {part.strip().lower() for part in str(meta_robots or "").split(",") if part.strip()}
    stability_status = "good"
    if "noindex" in meta_directives:
        stability_status = "critical"
    elif redirect.hops > 0 or not canonical.is_self or canonical.multiple:
        stability_status = "warning"
    stability_check = _check(
        "Citation readiness",
        "The page is a stable canonical source",
        stability_status,
        (
            f"Redirect hops: {redirect.hops}; Canonical self-reference: {'Yes' if canonical.is_self else 'No'}; "
            f"Multiple canonicals: {'Yes' if canonical.multiple else 'No'}; Meta robots: {meta_robots or '-'}."
        ),
        "Keep the page indexable, self-canonical, and free from unnecessary redirects if it should be cited as the source URL.",
        "citation_stability",
    )
    return [schema_check, social_check, stability_check]


def _build_entity_checks(
    title: str,
    h1: str,
    schema: StructuredDataPayload,
    social: SocialPayload,
) -> list[AiVisibilityCheck]:
    social_titles = [card.title for card in (social.open_graph, social.twitter) if card.title]
    title_matches = [_overlap_ratio(title, social_title) >= _SOCIAL_TITLE_SIMILARITY for social_title in social_titles]
    naming_status = (
        "good"
        if title and h1 and _overlap_ratio(title, h1) >= _SOCIAL_TITLE_SIMILARITY and all(title_matches or [True])
        else "warning"
    )
    naming_check = _check(
        "Entity clarity",
        "Naming is consistent across the page and social metadata",
        naming_status,
        "Title: {title}; H1: {h1}; OpenGraph title: {og}; Twitter title: {tw}.".format(
            title=title or "-",
            h1=h1 or "-",
            og=social.open_graph.title or "-",
            tw=social.twitter.title or "-",
        ),
        "Keep the main page title, H1, and social titles focused on the same entity or topic wording.",
        "entity_naming",
    )
    all_types, eligible_types, detected_types = _schema_type_sets(schema)
    entity_support = detected_types & _ENTITY_SCHEMA_TYPES
    entity_status = "good" if entity_support else "warning"
    entity_status = "good" if eligible_types & _ENTITY_SCHEMA_TYPES else entity_status
    entity_check = _check(
        "Entity clarity",
        "Entity-supporting markup is present",
        entity_status,
        "Detected entity schema: {detected}; Eligible entity schema: {eligible}.".format(
            detected=", ".join(sorted(entity_support)) or "-",
            eligible=", ".join(sorted(eligible_types & _ENTITY_SCHEMA_TYPES)) or "-",
        ),
        "Add clear Organization, LocalBusiness, Product, Article, Service, or Person markup when relevant.",
        "entity_schema",
    )
    return [naming_check, entity_check]


def build_ai_visibility_checks(value: CrawlPayload | Mapping[str, Any]) -> list[AiVisibilityCheck]:
    data = _payload_mapping(value)
    ai_rows = _rows(data.get("ai_crawl", []))
    meta_rows = _rows(data.get("meta", []))
    header_rows = _rows(data.get("headers", []))
    quality = ContentQuality.from_raw(data.get("content_quality", {}))
    schema = StructuredDataPayload.from_raw(data.get("schema", {}))
    social = SocialPayload.from_raw(data.get("social", {}))
    canonical = CanonicalInfo.from_raw(data.get("canonical", {}))
    redirect = RedirectInfo.from_raw(data.get("redirect", {}))
    discovery = DiscoveryPayload.from_raw(data.get("discovery", {}))
    eeat = EeatPayload.from_raw(data.get("eeat", {}))
    structure = StructurePayload.from_raw(data.get("structure", {}))
    citation_content = CitationContentPayload.from_raw(data.get("citation_content", {}))
    citation_advanced = AdvancedCitationPayload.from_raw(data.get("citation_advanced", {}))
    seo_basics = SeoBasicsPayload.from_raw(data.get("seo_basics", {}))
    ai_citations = AiCitationsPayload.from_raw(data.get("ai_citations", {}))
    gsc = GscMetrics.from_dict(data.get("gsc", {}))
    ga4 = Ga4Metrics.from_dict(data.get("ga4", {}))
    lighthouse = LighthouseScores.from_dict(data.get("lighthouse", {}))
    rich_results = RichResultsReport.from_dict(data.get("rich_results", {}))
    semrush = SemrushMetrics.from_dict(data.get("semrush", {}))
    render_diff = _render_diff_from_raw(data.get("render"))
    vitals = WebVitals.from_raw(data.get("perf_vitals", {}))
    crux = CruxData.from_raw(data.get("perf_crux", {}))
    meta_robots = str(data.get("meta_robots", "")).strip()
    hreflang_rows = _rows(data.get("hreflang", []))
    page_url = _resolve_page_url(data)
    title = _title_from_meta(meta_rows)
    h1 = _first_h1(header_rows)
    structure_checks = build_structure_checks(structure)
    structure_by_area = _partition_structure_checks(structure_checks)
    checks = [
        *_build_access_checks(ai_rows),
        build_render_diff_check(render_diff),
        *build_discovery_checks(discovery),
        *_build_topic_clarity_checks(quality, title, h1),
        *structure_by_area["Topic clarity"],
        *build_seo_basics_checks(seo_basics),
        *_build_answerability_checks(quality),
        *_build_citation_checks(schema, social, canonical, redirect, meta_robots),
        *structure_by_area["Citation readiness"],
        *build_citation_content_checks(citation_content),
        *build_advanced_citation_checks(citation_advanced),
        *_build_entity_checks(title, h1, schema, social),
        *build_hreflang_checks(page_url, hreflang_rows, cluster=None),
        *build_eeat_checks(eeat),
        *build_performance_checks(vitals, crux),
    ]
    # AI Citations area (N4a): only emitted when actually measured, so
    # the optional 8th area stays invisible on stock audits.
    if ai_citations.measured:
        checks.extend(build_ai_citations_checks(ai_citations))
    # Real performance / Engagement (V7): only when GSC/GA4 connected.
    if gsc.measured or ga4.measured:
        checks.extend(build_real_performance_checks(gsc, ga4))
    # Authority signals (V17): only when Semrush is connected (optional).
    if semrush.measured:
        checks.extend(build_semrush_authority_checks(semrush))
    # Rich results (V14): schema-derived on every audit; Lighthouse only
    # after the opt-in single-page run, so it doesn't clutter stock pages.
    if rich_results.measured:
        checks.extend(build_rich_results_checks(rich_results))
    if lighthouse.measured:
        checks.extend(build_lighthouse_checks(lighthouse))
    return checks


def _render_diff_from_raw(value: Any) -> RenderDiff | None:
    if not isinstance(value, Mapping):
        return None
    if not value:
        return None
    status = str(value.get("status", "")).strip()
    if status not in {"good", "warning", "critical", "not_measured"}:
        return None
    missing_headings = value.get("missing_headings") or ()
    headings_tuple = (
        tuple(str(item) for item in missing_headings) if isinstance(missing_headings, (list, tuple)) else ()
    )
    return RenderDiff(
        status=status,  # type: ignore[arg-type]
        missing_headings=headings_tuple,
        missing_main_text_chars=int(value.get("missing_main_text_chars", 0) or 0),
        missing_links=int(value.get("missing_links", 0) or 0),
        reason=str(value.get("reason", "")),
    )


def _partition_structure_checks(items: list[AiVisibilityCheck]) -> dict[str, list[AiVisibilityCheck]]:
    bins: dict[str, list[AiVisibilityCheck]] = {"Topic clarity": [], "Citation readiness": []}
    for item in items:
        if item.area in bins:
            bins[item.area].append(item)
    return bins


def build_ai_visibility_payload(value: CrawlPayload | Mapping[str, Any]) -> AiVisibilityPayload:
    checks = build_ai_visibility_checks(value)
    return AiVisibilityPayload(summary=build_ai_visibility_summary(checks), checks=checks)


def recompute_with_lighthouse(payload: CrawlPayload, scores: Mapping[str, Any]) -> dict[str, Any]:
    """Merge Lighthouse ``scores`` into ``payload`` and recompute AI Visibility
    from the full payload mapping.

    Deterministic by construction: ``CrawlPayload.to_mapping()`` is lossless
    (H0), so a store round-trip of ``payload`` cannot change the result — the
    recompute sees the same source groups either way. Returns the updated
    payload mapping (ready to emit or persist). This is the single derivation
    path; the GUI only emits what this returns."""
    mapping = payload.to_mapping()
    mapping["lighthouse"] = dict(scores)
    mapping["ai_visibility"] = build_ai_visibility_payload(mapping).to_dict()
    return mapping


__all__ = [
    "AI_VISIBILITY_AREAS",
    "ai_visibility_check_tooltip",
    "ai_visibility_summary_tooltip",
    "build_ai_visibility_checks",
    "build_ai_visibility_payload",
    "recompute_with_lighthouse",
    "build_ai_visibility_summary",
    "normalize_ai_visibility_status",
]
