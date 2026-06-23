# Research citations & evidence taxonomy (H6)

This file is the **canonical, machine-checkable registry** of every external
source Silentfrog cites in its AI Visibility (SEO/GEO) audit, plus the taxonomy
that classifies *how* each recommendation is grounded.

It exists so that no user-facing claim rests on an invented citation or an
unsupported causal leap. The companion code is
[`src/silentfrog/research_evidence.py`](../src/silentfrog/research_evidence.py):

- `EVIDENCE_SOURCES` mirrors the **Source registry** below — the H6 guard tests
  assert the two are in exact lockstep (no source in code that the doc omits,
  and none in the doc that the code omits).
- `CHECK_EVIDENCE` maps every check to its `(evidence_class, source_ids)` and is
  pinned to the full set of emittable check keys.
- A guard test asserts every **sourced** claim (an `official_standard` or
  `research` check) resolves to a real source ID, and that no user-facing
  effect size (`%` / `×`) survives without a resolvable research citation.

Evidence is **metadata only**: classifying or citing a check never changes its
status or the GEO Score.

## How to read a source entry

Each source has a stable ID (used in code as `evidence_source_ids`), a class, a
URL, and an explicit note on **what it does and does not support**. IDs are
written as ``### `ID` — Title`` so they can be extracted programmatically.

## Evidence taxonomy

Silentfrog classifies each recommendation into exactly one class:

| Class (`evidence_class`) | Meaning | Source IDs required? |
|---|---|---|
| `official_standard` | Cites a published specification or vendor documentation (schema.org, Google Search Central, RFC, Lighthouse, web.dev). | **Yes** |
| `research` | States a **measured effect size** drawn from a cited study. | **Yes** |
| `correlation` | A reported or observed relationship, presented **without** implying causation. | Optional (cite the report) |
| `silentfrog_heuristic` | A Silentfrog editorial rule or numeric **threshold** (e.g. TTR ≥ 0.5, readability ≥ 60, keyword density ≤ 4%, pronoun density ≥ 0.2%). Not an external standard. | Optional (may cite supporting direction) |
| `silentfrog_scoring` | Product-specific scoring logic (e.g. `_geo_score`). | No |
| `descriptive` | A factual observation about the page or connected data, with no external claim. | No |

**Rules enforced by the guard tests**

1. Every emittable check carries a non-empty `evidence_class`.
2. Every `official_standard` and `research` check resolves at least one source
   ID present in this registry.
3. No user-facing effect size (a `%` or `×` magnitude) appears in a check's
   recommendation/details/tooltip unless that check is `research`-classed and
   cites a resolvable research source.
4. Numeric gating thresholds are labelled Silentfrog heuristics, not facts.

## Source registry

### `SCHEMA-ORG` — Schema.org vocabulary

- **Class:** official standard
- **URL:** https://schema.org/
- **Supports:** the existence, names, and required/recommended properties of
  structured-data types (Organization, Article, Product, FAQPage, BreadcrumbList,
  HowTo, WebSite, Person, LocalBusiness).
- **Does not support:** any claim that a given type causes ranking, citation, or
  a quantified visibility lift.

### `GOOGLE-RICH-RESULTS` — Google Search Central: Structured data / rich results gallery

- **Class:** official standard
- **URL:** https://developers.google.com/search/docs/appearance/structured-data/search-gallery
- **Supports:** which structured-data types are *eligible* for Google rich
  results and the markup requirements/validity rules for each.
- **Does not support:** that valid markup *guarantees* a rich result — Google
  states eligibility is necessary but not sufficient. "Eligible" in Silentfrog
  therefore means *syntactically valid for the type*, not *granted by Google*.

### `GOOGLE-AI-FEATURES` — Google Search Central: AI features and your website

- **Class:** official standard
- **URL:** https://developers.google.com/search/docs/appearance/ai-features
- **Supports:** that **no special markup, AI text files, or `llms.txt` are
  required** to appear in Google's AI features; standard SEO best practices
  (semantic HTML, internal links, image SEO, quality external references) remain
  the basis, and quality matters more than quantity.
- **Does not support:** that `llms.txt`, `llms-full.txt`, or `/.well-known/ai.json`
  are required by Google, or that any single on-page change yields a quantified
  AI-visibility increase.

### `GOOGLE-ROBOTS-META` — Google Search Central: Robots meta tag, data-nosnippet, and X-Robots-Tag

- **Class:** official standard
- **URL:** https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag
- **Supports:** the meaning and effect of `noindex`, `nosnippet`,
  `max-snippet`, and related Google-honoured directives on indexing and reuse.
- **Does not support:** that nonstandard directives (`noai`, `noimageai`) are
  honoured — those are advisory absent vendor confirmation.

### `GOOGLE-CWV` — Google web.dev: Core Web Vitals and thresholds (LCP, INP, CLS)

- **Class:** official standard
- **URL:** https://web.dev/articles/vitals
- **Supports:** the Core Web Vitals metrics and their "good/needs-improvement/poor"
  thresholds — LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1 (field P75 is the canonical
  measure; lab is diagnostic).
- **Does not support:** Core Web Vitals as an AI-citation guarantee, or
  vendor-specific "AI answer" latency cutoffs.

### `LIGHTHOUSE` — Google Lighthouse: audit references and performance scoring

- **Class:** official standard
- **URL:** https://developer.chrome.com/docs/lighthouse/overview
- **Supports:** the Lighthouse SEO/performance audits (e.g. responsive viewport
  meta tag), the lab metrics that are *not* Core Web Vitals (FCP, Total Blocking
  Time, Speed Index) and their thresholds, and the 0–100 category scoring band.
- **Does not support:** that a 90+ lab score guarantees ranking or citation.

### `RFC-9309` — RFC 9309: Robots Exclusion Protocol

- **Class:** official standard
- **URL:** https://www.rfc-editor.org/rfc/rfc9309.html
- **Supports:** robots.txt grammar, user-agent group selection (longest-match),
  and `Allow`/`Disallow` semantics used to decide whether an agent may fetch a URL.
- **Does not support:** crawl-delay (non-standardised) or any AI-specific token
  behaviour beyond what a vendor documents.

### `GEO-AGGARWAL-2024` — Aggarwal et al., "GEO: Generative Engine Optimization", KDD 2024 (arXiv:2311.09735)

- **Class:** research (measured effect sizes)
- **URL:** https://arxiv.org/abs/2311.09735 — DOI 10.48550/arXiv.2311.09735
- **Supports:** that content-level GEO methods can **boost source visibility in
  generative-engine responses by up to ~40%** (GEO-bench, Position-Adjusted Word
  Count). Among the nine methods tested, **Quotation Addition, Statistics
  Addition, and Cite Sources were the most effective**; **Keyword Stuffing
  reduced visibility below baseline**; **Unique Words showed minimal gain**. The
  paper also notes efficacy varies by domain.
- **Does not support:** per-method exact percentages presented as universal
  constants, schema-type effect sizes (e.g. "FAQPage +40%"), per-engine update-
  cadence multipliers (e.g. "3.2× on a 30-day refresh"), or any claim about
  FAQPage markup — the paper studies **text content**, not schema markup.

### `BRAVE-CLAUDE-TECHCRUNCH-2025` — TechCrunch (2025-03-21): Anthropic appears to use Brave to power Claude web search

- **Class:** correlation (reported, not vendor-confirmed)
- **URL:** https://techcrunch.com/2025/03/21/anthropic-appears-to-be-using-brave-to-power-web-searches-for-its-claude-chatbot/
- **Supports:** that Claude's web search **appears** to draw on Brave's index,
  per reporting.
- **Does not support:** an official, permanent, or exclusive Brave→Claude
  relationship. Treat as a reported, changeable integration — never as a
  guarantee that Brave indexing causes Claude citations.

### `BRAVE-SEARCH-API` — Brave Search API: independent web index

- **Class:** official standard (vendor documentation)
- **URL:** https://brave.com/search/api/
- **Supports:** that Brave operates an independent search index queryable via API.
- **Does not support:** any claim about which AI engines consume it or with what
  weight.

### `COMMON-CRAWL` — Common Crawl: open web crawl corpus and CDX index

- **Class:** descriptive (factual reference)
- **URL:** https://commoncrawl.org/
- **Supports:** that Common Crawl publishes a periodic open crawl with a
  URL-addressable CDX index (months-lagged).
- **Does not support:** that presence in Common Crawl causes citation by any
  specific AI engine.

## Silentfrog heuristic thresholds

These numeric cut-offs are **Silentfrog editorial heuristics**, not external
standards or measured effect sizes. They are labelled as such wherever they
appear and never presented as research findings. Most are configurable.

| Threshold | Value (default) | Where | Config |
|---|---|---|---|
| Readability band | Flesch / Gulpease ≥ 60 | `citation_readability` | — |
| Vocabulary diversity | type-token ratio ≥ 0.5 | `citation_vocabulary_diversity` | — |
| Keyword-stuffing warning | top keyword density > 4% | `citation_no_keyword_stuffing` | `SILENTFROG_KEYWORD_WARN_DENSITY` |
| Authoritative-tone band | first/second-person pronouns ≥ 0.2% of tokens | `citation_authoritative_tone` | — |
| E-E-A-T freshness window | updated within 365 days | `eeat_update_freshness` | `SILENTFROG_EEAT_FRESHNESS_DAYS` |
| Good CTR | ≥ ~2% | `gsc_ctr_above_average` | — |
| Top-position band | average position ≤ 10 | `gsc_position_in_top_10` | — |
| Good engagement | ≥ 30 s avg engagement | `ga4_engagement_above_median` | — |
| High bounce | > 70% | `ga4_bounce_below_threshold` | — |
| Good Lighthouse score | ≥ 90 / 100 | `lighthouse_*_above_90` | — |
| Semrush authority floor | Authority Score > 30 | `semrush_domain_authority_above_30` | — |
| **STANDARD link-probe cap** | **25 links/page** | crawl profile (H4) | `crawl_options._STANDARD_LINK_PROBE_CAP` |
| **Auto-suggest LIGHTWEIGHT** | **above 50,000 target URLs** | crawl profile (H4) | `crawl_options._AUTO_LIGHTWEIGHT_THRESHOLD` |

The last two (added in H4) bound a site crawl's per-page request fan-out: a
STANDARD crawl probes at most 25 internal links per page for HTTP status, and a
STANDARD crawl over more than 50,000 target URLs auto-suggests the LIGHTWEIGHT
profile. They are operational guards, not visibility claims.

## Effect-size audit (PR-15)

What changed when the user-facing effect sizes were audited against the primary
sources, so the record is explicit:

**Retained and cited** (`GEO-AGGARWAL-2024`):

- "GEO methods improved generative-engine visibility by **up to ~40%**" — the
  paper's headline result.
- Quotation addition was the **most effective** method tested.
- Keyword stuffing **reduced visibility below baseline** (it can hurt).
- Easy-to-understand text and an authoritative tone were **among the methods
  that helped**; unique-word variation was **among the least effective**.

**Removed as unsupported** (not present in the paper or any resolvable source —
the number was deleted rather than re-cited):

- "FAQPage schema → +40% AI visibility / largest schema-driven boost." The paper
  studies **text content**, not schema markup types. FAQPage is now framed as a
  relevance-driven schema choice, not a visibility multiplier.
- "30-day updates → 3.2× more ChatGPT citations." No source. Freshness is now a
  labelled Silentfrog heuristic window.
- "Bing weights < 2 s LCP for AI Answer eligibility." No source; removed.
- Per-method exact percentages presented as constants (`+30% / +20% / +15% /
  −10% / +25%`). The paper's per-method numbers are benchmark-specific and
  domain-varying; the direction is retained and cited, the invented constants
  removed.
- "Perplexity prioritises FAQ-shaped content (Princeton signal)." No source for
  the per-engine claim; removed.

**Re-worded for accuracy:**

- "Brave is Claude's primary index / a URL absent from Brave is invisible to
  Claude" → caveated as **reported, not officially confirmed** (`BRAVE-CLAUDE-
  TECHCRUNCH-2025`); Brave indexing is a useful but not guaranteed proxy.
- Rich-results "Eligible" → clarified as **syntactically valid for a Google
  rich-result type, not a guarantee Google will show a rich result**; Person and
  WebSite flagged as valid types that are not standalone rich results.

No check status, verdict threshold, or scoring weight was changed by this audit.

## Maintenance

When adding or changing a citation:

1. Add/edit the source entry above **and** the matching `EvidenceSource` in
   `research_evidence.py` (the guard test fails if they diverge).
2. Map any new check key in `CHECK_EVIDENCE` with the correct class.
3. Cite only primary/authoritative sources. If a magnitude cannot be tied to a
   resolvable source, **remove the number** rather than invent a citation.
