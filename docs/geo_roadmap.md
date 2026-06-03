# Silentfrog GEO Roadmap

## 1. Goal & Definition of "GEO-ready"

Per Google's AI Optimization Guide
(<https://developers.google.com/search/docs/fundamentals/ai-optimization-guide>),
the high-value signals are: helpful / reliable / people-first content,
semantic structure, and standard SEO hygiene. Silentfrog already
audits AI Visibility through 13 checks across 5 areas
(`AI_VISIBILITY_AREAS` in `src/silentfrog/ai_visibility.py:19`). GEO
extends that surface to cover (a) the Google-aligned positive signals
above and (b) optional positive signals for non-Google AI engines
(Anthropic, Perplexity, OpenAI) without ever marking those optional
signals as warnings when absent — see §1.5 myth alignment.

A page is "GEO-ready" when the same engine reports:

- **Access pillar**: AI agents allowed, `llms.txt` / `llms-full.txt` /
  `/.well-known/ai.json` present, server-rendered content matches the
  Playwright-rendered DOM.
- **Topic clarity**: title/H1 aligned, language declared, depth
  sufficient — unchanged from today.
- **Answerability**: intro paragraph, chunked content — unchanged.
- **Citation readiness**: schema valid (now incl. Person / HowTo /
  WebSite), question-form headings, definition patterns, stats density.
- **Entity clarity**: consistent naming, entity schema present —
  extended by the new schema validators.
- **E-E-A-T** *(new sixth area)*: author byline, publish/update dates,
  author bio, external citations.

At M4 completion the aggregated verdict from
`build_ai_visibility_summary` (`ai_visibility.py:149`) takes inputs
from ≥ 28 checks across 6 areas, plus a numeric GEO Score 0–100 shown
in the tab header and in both Excel exports.

## 1.5. Google AI Optimization Guide alignment

The Google AI Optimization Guide gives authoritative
anti-recommendations for Google's AI surfaces. Silentfrog treats these
explicitly: signals Google calls "not required" surface as **positive
INFO signals when present**, and **NEVER as warnings or criticals
when absent**. Every affected tooltip carries a one-line
Google-myth disclaimer so users do not chase non-existent ranking
factors.

| Google myth (verbatim quote) | Affected check_keys | Silentfrog rule |
|---|---|---|
| "You don't need to create new machine readable files, AI text files, markup, or Markdown to appear in generative AI search" | `access_llms_txt`, `access_llms_full_txt`, `access_well_known_ai_json` (M1) | Absent → `status="info"` (mapped to "good"); present → "good". No warning emitted. |
| "There's no requirement to break your content into tiny pieces for AI to better understand it" | `answer_chunking` (existing, `ai_visibility.py:346`) | Keep current "Good" status for any reasonable structure; never emit "critical" purely on chunk size. |
| "You don't need to write in a specific way just for generative AI search" | `citation_question_headings`, `citation_definition_patterns` (M3) | Present → "good"; absent → "info" only, never "warning". |
| "You don't have to worry that you don't have enough 'long-tail' keywords or haven't captured every variation" | (none — Silentfrog has no long-tail check today) | Confirmed not introduced by this roadmap. |
| "Seeking inauthentic 'mentions' across the web isn't as helpful as it might seem" | `eeat_external_citations` (M2) | Tooltip emphasises QUALITY of citations over QUANTITY; absence → "info"; never recommends pursuing mentions. |
| "Structured data isn't required for generative AI search, and there's no special schema.org markup you need to add" | `citation_schema`, `entity_schema` (existing) | Keep current grading; tooltip notes structured data is a positive SEO signal, not an AI-specific requirement. |

`_STATUS_ALIASES` (`ai_visibility.py:27`) already maps `"info"` to
`"good"`, so info rows count toward the Good column in the tab
summary and contribute zero to the GEO Score penalty. No new status
keyword is introduced.

**Positive checks driven by the Google guide** (added in this
roadmap, see M1/M2): `access_sitemap`, `structure_semantic_html`,
`structure_internal_links`, `citation_images_alt`.

## 2. Architecture mapping

| New module | Integration point in `seo_crawler.py` | Consumer | `CrawlPayload` field |
|---|---|---|---|
| `src/silentfrog/discovery_files.py` | new call inside `_collect_analysis_sections` (`seo_crawler.py:155`) right after `_parse_robots` (`seo_crawler.py:187`) | `ai_visibility.py::_build_access_checks` | `discovery` (mapping) |
| `src/silentfrog/eeat_signals.py` | new call inside `_collect_analysis_sections` after `_extract_social_cards` (`seo_crawler.py:205`) | `ai_visibility.py::_build_eeat_checks` (new) | `eeat` (mapping) |
| `src/silentfrog/structure_signals.py` *(M2)* | new call inside `_collect_analysis_sections` next to `extract_eeat_signals` | `ai_visibility.py::_build_structure_checks` (new) — folds into Topic clarity + Citation readiness | `structure` (mapping) |
| `src/silentfrog/citation_readiness_content.py` | new call inside `_collect_analysis_sections` next to `extract_content_quality` (`seo_crawler.py:204`) | `ai_visibility.py::_build_citation_checks` (extended) | `citation_content` (mapping) |
| `src/silentfrog/render_diff.py` | new top-level call inside `analyse` (`seo_crawler.py:209`) parallel to `_extract_schema_all` (`seo_crawler.py:213`); gated on optional Playwright import | `ai_visibility.py::_build_access_checks` (extended) | `render` (mapping) |
| `src/silentfrog/semantic_coverage.py` *(M5)* | new call after `_extract_keywords` (`seo_crawler.py:203`) | `ai_visibility.py::_build_topic_clarity_checks` (extended) | `semantic` (mapping) |
| `src/silentfrog/query_simulation.py` *(M5)* | new call after `_make_serp_snippet` (`seo_crawler.py:188`) | `ai_visibility.py::_build_topic_clarity_checks` (extended) | `query_intent` (mapping) |

Every new field is added to `_REQUIRED_CRAWL_KEYS`
(`crawl_types.py:86`) only after its milestone ships; until then the
ai-visibility consumers read via `data.get(key, {})` with a default —
same pattern as `data.get("content_quality", {})` at
`ai_visibility.py:462`.

New schema validators land in **both**
`_SCHEMA_ELIGIBILITY_TYPES` (`schema_extractor.py:30`) **and**
`_SCHEMA_VALIDATORS` (`schema_extractor.py:200`), following the
existing `_schema_validate_*` helper shape (e.g.
`_schema_validate_organization` at `schema_extractor.py:182`).

## 3. UX integration

**Choice**: extend the existing **AI Visibility** tab. No new
top-level tab. The Site Crawl detail dialog (which reuses the same
tab class) inherits the change for free.

Affected surface:

- **`AiVisibilityTab` (`tabs.py:433`)** — prepend a GEO Score header
  widget above `self._summary` (`tabs.py:442`); reads
  `payload.summary.score` (new optional int field on
  `AiVisibilitySummary`, default `None`). Format: `"GEO Score: 78 / 100"`
  with tooltip explaining the formula. Existing 5-column table absorbs
  new `check_key`s; no column change.
- **`AI_VISIBILITY_AREAS` (`ai_visibility.py:19`)** — appended `"E-E-A-T"` (M2).
- **`ai_visibility_check_tooltip` (`ai_visibility.py:130`)** — every new
  `check_key` adds an entry to `_AI_VISIBILITY_CHECK_TOOLTIPS`
  (`ai_visibility.py:58`); verbatim text per milestone below.
- **Single-page Excel (`exporters/excel.py`)** — new
  `_write_geo_score_sheet` at position 0 of the `writers` tuple
  (`excel.py:1054`). Sheet name: `"GEO Score"`.
- **Site Crawl Excel (`exporters/site_crawl_excel.py`)** — new sheets
  `"GEO Score"` (per-URL: URL, Score, Verdict, Good, Warning, Critical)
  and `"GEO Score detail"` (per-URL × per-check), injected next to the
  existing AI Visibility writes (`site_crawl_excel.py:49`, `:73`).
- **`CrawlSettingsDialog` (`settings_dialog.py`)** — one new checkbox
  `"Run SSR parity check (requires Playwright)"`, default off; disabled
  with tooltip when `geo-render` extra is missing. Persists in
  `CrawlOptions.ssr_parity_check: bool = False`.
- **`README.md`** — capability table gains row "GEO Visibility Score",
  status updated per milestone. §1 Prerequisites mentions the optional
  `geo-render` extra after M4 lands.

## 4. Milestones

### M0 — Quick fixes + schema parity (NEW_DEPS: False)

- **Goal**: ship the dependency reclassification and bring schema
  validators on par with the 9-type spec.
- **Scope**:
  - `pyproject.toml`: move `extruct` and `w3lib` from
    `[tool.poetry.group.dev.dependencies]` to `[project] dependencies`
    — they are runtime imports at `schema_extractor.py:21–22` (the
    `USE_EXTRUCT` guard hides, not removes, the requirement).
  - `src/silentfrog/schema_extractor.py`: remove unused
    `from w3lib.html import get_base_url` (line 22 — the extruct call
    at line 475 takes `base_url` directly). Extend
    `_SCHEMA_ELIGIBILITY_TYPES` and `_SCHEMA_VALIDATORS` with
    `("person", "Person")`, `("howto", "HowTo")`, `("website",
    "WebSite")`. Add `_schema_validate_person`,
    `_schema_validate_how_to`, `_schema_validate_website` using the
    `[(condition, message), ...]` pattern of
    `_schema_validate_organization` (`schema_extractor.py:182`).
  - Extend `_ENTITY_SCHEMA_TYPES` and `_RICH_SCHEMA_TYPES`
    (`ai_visibility.py:46–47`) so Person counts as entity and
    HowTo/WebSite as rich citation schema.
- **NEW_DEPS**: False (reclassification only).
- **UX changes**: none directly (the schema sheet already lists
  every detected type). Tooltip for `citation_schema` and
  `entity_schema` references the broader list.
- **Acceptance criteria**:
  - `tests/test_schema_extractor_unit.py` gains ≥ 8 cases (3 per new
    type for valid / missing-field / @graph nesting, +1 for the
    Person+sameAs entity overlap with `_ENTITY_SCHEMA_TYPES`).
  - Fixtures under `docs/tests/fixtures/`: `schema_person_valid.json`,
    `schema_person_missing_name.json`, `schema_howto_valid.json`,
    `schema_howto_missing_step.json`, `schema_website_valid.json`.
  - `poetry run python tools/doctor.py` passes on Windows + macOS
    Intel + macOS Apple Silicon.
  - No new entries in `tools/code_shape_baseline.json`.
  - README capability table: unchanged at this milestone.
- **New check_keys**: none (existing `citation_schema`,
  `entity_schema` now see the new types).
- **Effort**: 1 day.
- **Risk**: Low. Rollback = revert the pyproject + schema_extractor
  edits; behaviour identical to today.
- **Cooldown impact**: None.

### M1 — Discovery files + AI bot list expansion (NEW_DEPS: False)

- **Goal**: detect llms.txt / llms-full.txt / `.well-known/ai.json`
  and audit ≥ 16 AI bots in the robots matrix.
- **Scope**:
  - New `src/silentfrog/discovery_files.py` with signatures:
    - `async def fetch_discovery_files(base_url: str, timeout: int = 8) -> DiscoveryPayload`
    - `@dataclass(frozen=True) class DiscoveryPayload: llms_txt: DiscoveryEntry; llms_full_txt: DiscoveryEntry; well_known_ai_json: DiscoveryEntry`
    - `@dataclass(frozen=True) class DiscoveryEntry: url: str; status: int; present: bool; body_excerpt: str; parsed: Mapping[str, Any]`
    - `def build_discovery_checks(payload: DiscoveryPayload) -> list[AiVisibilityCheck]`
  - Modify `src/silentfrog/seo_crawler.py:_collect_analysis_sections`
    to call `fetch_discovery_files(response.url, timeout)` once and
    return its mapping under key `"discovery"`.
  - Modify `src/silentfrog/ai_visibility.py:_build_access_checks`
    (currently lines 248–294) to consume `data.get("discovery", {})`
    and emit three new checks.
  - Modify `src/silentfrog/parsers_meta.py:_AI_AGENTS` (line 630):
    extend to 18 entries — GPTBot, ChatGPT-User, OAI-SearchBot,
    ClaudeBot, anthropic-ai, Claude-Web, Claude-User,
    Claude-SearchBot, PerplexityBot, Perplexity-User, Googlebot,
    Google-Extended, Applebot-Extended, Amazonbot, Bytespider,
    CCBot, Meta-ExternalAgent, DuckAssistBot, cohere-ai. Preserve
    `applies_google_search_controls=True` only on Googlebot.
  - Extend `discovery_files.py` to also probe `sitemap.xml`: check
    (a) `Sitemap:` directives in robots.txt (already parsed via
    `_parse_robots` at `seo_crawler.py:187`), and (b)
    `GET /sitemap.xml` fallback. Emits `access_sitemap` check.
- **NEW_DEPS**: False.
- **UX changes**: tab gains 3 new Access rows; AI Crawl tab gains
  ≥ 12 additional bot rows (the matrix builder already renders
  one row per `_AI_AGENTS` entry — no GUI code change).
- **Acceptance criteria**:
  - `tests/test_discovery_files_unit.py` (new) ≥ 12 cases (3 per
    file for allow/deny/missing + 2 for sitemap + 1 combined
    integration with `aiohttp` stubbed via the `DummySession`
    pattern from `tests/test_http_client.py:13`).
  - `tests/test_ai_visibility_unit.py` extended by 4 cases for the
    new check_keys, asserting `"info"`/`"good"` status mapping
    (never `"warning"`).
  - `tests/test_parsers_meta_unit.py` extended by 4 cases for the
    18 bots and Googlebot's Google-search-controls flag.
  - Fixtures under `docs/tests/fixtures/`: as listed in §6.
  - `tools/doctor.py` passes on three platforms. README capability
    row "GEO Visibility Score" → "Partial".
- **New check_keys**:
  - `access_llms_txt` — *"Checks whether the site publishes an
    `llms.txt` declaring policies and entry points for AI crawlers.
    Per Google's AI Optimization Guide this file is NOT required to
    appear in Google's AI surfaces; some other AI engines
    (Anthropic, Perplexity, OpenAI) treat its presence as a positive
    signal. Absent → info; present → info. Never warned."*
  - `access_llms_full_txt` — *"Checks whether the site publishes an
    `llms-full.txt` with the long-form policy and structured
    content map. Same Google-not-required rule as `access_llms_txt`:
    absent → info, present → info."*
  - `access_well_known_ai_json` — *"Checks whether the site
    publishes `/.well-known/ai.json` with a machine-readable AI
    access policy. Same Google-not-required rule: absent → info,
    present → info. Useful only for engines that explicitly read
    the file."*
  - `access_sitemap` — *"Checks whether a `sitemap.xml` is
    discoverable via a `Sitemap:` directive in robots.txt or at
    the site root. Best practice: publish a sitemap and reference
    it in robots.txt; Google's AI Optimization Guide reinforces
    sitemap as part of standard crawlability hygiene."*
- **Effort**: 3 days.
- **Risk**: Medium — three extra HTTP fetches per page lengthen
  analysis time by ~0.5–1.5 s. Rollback = remove the
  `fetch_discovery_files` call; the consumers default to empty
  mapping and the new check_keys evaluate as "warning" (data
  absent), which mirrors the existing `access_missing` pattern at
  `ai_visibility.py:251`.
- **Cooldown impact**: None.

### M2 — E-E-A-T + Google-aligned structure signals (NEW_DEPS: False)

- **Goal**: extract author / date / citation signals, emit the new
  "E-E-A-T" area, AND fold in three Google-AI-guide-aligned positive
  checks (semantic HTML, internal links, image-alt summary).
- **Scope**:
  - New `src/silentfrog/eeat_signals.py`:
    - `def extract_eeat_signals(soup: BeautifulSoup, schema: StructuredDataPayload, freshness_days: int) -> EeatPayload`
    - `@dataclass(frozen=True) class EeatPayload: byline: str; publish_date: str; update_date: str; days_since_update: int; author_bio_url: str; same_as: tuple[str, ...]; external_citations: tuple[str, ...]`
    - `def build_eeat_checks(payload: EeatPayload, freshness_days: int) -> list[AiVisibilityCheck]`
    - `def _freshness_threshold_days() -> int` — reads
      `SILENTFROG_EEAT_FRESHNESS_DAYS` env var (default 365),
      mirroring `_keyword_density_threshold` at
      `src/silentfrog/crawl_constants.py:39`.
  - New `src/silentfrog/structure_signals.py`:
    - `def extract_structure_signals(soup: BeautifulSoup, page_url: str) -> StructurePayload`
    - `@dataclass(frozen=True) class StructurePayload: semantic_container_counts: dict[str, int]; internal_link_count: int; total_link_count: int; images_with_alt: int; images_total: int`
    - `def build_structure_checks(payload: StructurePayload) -> list[AiVisibilityCheck]`
    - Counts of `<article>`, `<section>`, `<main>`, `<nav>`,
      `<header>`, `<footer>` from the existing BeautifulSoup tree;
      reuses `_extract_links` (`parsers_meta.py`) shape for internal
      vs external link partition; image alt-text via the existing
      `_extract_images` row layout (alt is column index 2).
  - Modify `ai_visibility.py`: append `"E-E-A-T"` to
    `AI_VISIBILITY_AREAS` (line 19); call `build_eeat_checks` AND
    `build_structure_checks` from `build_ai_visibility_checks`
    (line 457). The 3 structure checks fold into existing areas:
    `structure_semantic_html` → Topic clarity,
    `structure_internal_links` → Citation readiness,
    `citation_images_alt` → Citation readiness. No 7th area.
  - Modify `seo_crawler.py:_collect_analysis_sections` to call
    `extract_eeat_signals(soup, structured_data, freshness_days)`
    AND `extract_structure_signals(soup, response.url)` and return
    the mappings under keys `"eeat"` and `"structure"`.
- **NEW_DEPS**: False (uses BeautifulSoup already in deps).
- **UX changes**: AI Visibility tab gains an "E-E-A-T" area band
  (5 rows) plus 3 new rows in existing areas (Topic clarity gets
  `structure_semantic_html`; Citation readiness gets
  `structure_internal_links` and `citation_images_alt`). Total +8
  rows in this milestone.
- **Acceptance criteria**:
  - `tests/test_eeat_signals_unit.py` (new) ≥ 12 cases covering each
    check_key across byline-present/missing, date-present/stale/fresh,
    bio-present/missing, citations-present/none, mixed schema-or-DOM.
  - `tests/test_structure_signals_unit.py` (new) ≥ 8 cases:
    semantic-rich vs div-soup pages, link-rich vs link-poor,
    images-with-vs-without alt, mixed.
  - `tests/test_ai_visibility_unit.py` extended by 9 cases (E-E-A-T
    rows + 3 structure rows + 1 case asserting
    `build_ai_visibility_summary` weights E-E-A-T as a non-Access
    area: warnings here never trigger "Weak" on their own — only
    Access criticals do, per `ai_visibility.py:167`).
  - Fixtures: as listed in §6.
  - `tools/doctor.py` passes on three platforms. README capability
    row stays at "Partial".
- **New check_keys**:
  - `eeat_author_byline` — *"Checks whether the page exposes a
    visible author byline near the title. Best practice: show the
    author name in the page body and link it to a stable profile."*
  - `eeat_publish_date` — *"Checks whether the page declares a
    publish date a generative engine can attribute. Best practice:
    expose `datePublished` (or visible publication date) so AI
    systems can date the claim."*
  - `eeat_update_freshness` — *"Checks whether the page was
    updated within the configured freshness window. Best practice:
    maintain `dateModified` (or a visible last-update marker) and
    refresh evergreen pages within the
    `SILENTFROG_EEAT_FRESHNESS_DAYS` threshold (default 365)."*
  - `eeat_author_bio` — *"Checks whether the author has a
    discoverable bio or `sameAs` link. Best practice: link the
    byline to an `/about` page, a Person schema with `sameAs`, or
    a stable external profile."*
  - `eeat_external_citations` — *"Checks whether the page cites a
    small number of named, authoritative external sources. Best
    practice: link standards bodies, peer-reviewed work, or
    primary docs when relevant. Quality, not quantity: per
    Google's AI Optimization Guide, manufactured or inauthentic
    mentions do NOT help. Absence → info; never recommends
    pursuing mentions."*
  - `structure_semantic_html` *(Topic clarity area)* — *"Checks
    whether the page uses semantic HTML containers (`<article>`,
    `<section>`, `<main>`, `<nav>`, `<header>`, `<footer>`)
    instead of generic `<div>` soup. Best practice: structure the
    page with semantic landmarks; per Google's AI Optimization
    Guide semantic HTML aids machine understanding without any
    AI-specific markup."*
  - `structure_internal_links` *(Citation readiness area)* —
    *"Checks whether the page links to related internal pages.
    Best practice: a small set of contextual internal links to
    deeper or related content; Google's AI Optimization Guide
    recommends internal architecture that helps crawlers and
    readers reach related material."*
  - `citation_images_alt` *(Citation readiness area)* — *"Checks
    whether content images carry meaningful alt text. Best
    practice: descriptive alt per image — Google's AI
    Optimization Guide cites image SEO as part of standard
    hygiene. The detailed image audit lives in the Images tab;
    this row summarises it for GEO."*
- **Effort**: 4 days.
- **Risk**: Medium — date parsing across `datePublished` /
  `dateModified` / visible `<time>` elements is brittle.
  Rollback = remove the area string from `AI_VISIBILITY_AREAS`;
  consumers degrade gracefully.
- **Cooldown impact**: None.

### M3 — Citation-readiness content patterns (NEW_DEPS: False)

- **Goal**: detect question-form headings, statistical density, and
  definition patterns, in English and Italian.
- **Scope**:
  - New `src/silentfrog/citation_readiness_content.py`:
    - `def extract_citation_content_signals(soup: BeautifulSoup, language_hint: str) -> CitationContentPayload`
    - `@dataclass(frozen=True) class CitationContentPayload: question_headings: tuple[str, ...]; stats_density: float; definitions: tuple[str, ...]; language: str`
    - `def build_citation_content_checks(payload: CitationContentPayload) -> list[AiVisibilityCheck]`
    - Module-level regex constants `_QUESTION_HEADING_EN`,
      `_QUESTION_HEADING_IT`, `_DEFINITION_EN`, `_DEFINITION_IT`,
      `_STATS_TOKEN` — exposed as constants per AGENTS.md rule
      "Avoid `if/elif` ladders for string dispatch".
  - Modify `ai_visibility.py:_build_citation_checks` (lines 363–414)
    to consume the new payload and emit the new check_keys.
  - Modify `seo_crawler.py:_collect_analysis_sections` to call
    `extract_citation_content_signals(soup, content_quality.language)`
    and return mapping under `"citation_content"`.
- **NEW_DEPS**: False.
- **UX changes**: 3 new rows under the existing "Citation
  readiness" area. No structural change.
- **Acceptance criteria**:
  - `tests/test_citation_readiness_content_unit.py` (new) ≥ 12 cases
    (3 per check, EN + IT for each, plus 3 for the language-guard
    fallback: when `content_quality.language` is neither `en` nor
    `it`, checks emit `status="info"` with detail
    `"Language not supported for content patterns"` — info, not
    warning, per §1.5 myth rule).
  - `tests/test_ai_visibility_unit.py` extended by 3 cases.
  - Fixtures: as listed in §6. `tools/doctor.py` passes. No new
    `code_shape_baseline.json` entries. README capability row
    → "Good" (≥ 5 of 7 pillars).
- **New check_keys**:
  - `citation_question_headings` — *"Checks whether H2/H3 headings
    are phrased as questions that the body answers. Per Google's
    AI Optimization Guide you do NOT need to rewrite content
    specifically for AI; question-form headings are a positive
    signal where they fit the natural editorial style, never a
    requirement. Present → good; absent → info."*
  - `citation_stats_density` — *"Checks whether the page contains
    specific numbers, dates, and units AI engines can quote. Best
    practice: include concrete data points (percentages, monetary
    values, dated events) when they are accurate and supportable."*
  - `citation_definition_patterns` — *"Checks whether the page
    defines its key terms with clear \"X is Y\" sentences. Same
    Google-not-required rule as `citation_question_headings`:
    present → good; absent → info, never warning. Best practice:
    where it fits the editorial style, open sections with a
    one-sentence definition."*
- **Effort**: 2.5 days.
- **Risk**: Medium — regexes will over- or under-fire on
  non-EN/IT pages and on heavily punctuated content. The
  language-guard fallback caps the blast radius; see risk register.
- **Cooldown impact**: None.

### M4 — SSR / JS render parity (NEW_DEPS: True — `playwright`)

- **Goal**: detect when the JS-rendered DOM diverges from the
  HTML AI crawlers will see.
- **Scope**:
  - New `src/silentfrog/render_diff.py`:
    - `def render_with_playwright(url: str, timeout_seconds: int = 15) -> RenderResult | None`
      (returns `None` when the optional import fails).
    - `def compute_render_diff(plain_html: str, rendered_html: str) -> RenderDiff`
    - `@dataclass(frozen=True) class RenderDiff: status: Literal["good","warning","critical","not_measured"]; missing_headings: tuple[str, ...]; missing_main_text_chars: int; missing_links: int`
    - `def build_render_diff_check(diff: RenderDiff | None) -> AiVisibilityCheck`
    - Optional import guard at the top: `try: from playwright.sync_api import sync_playwright except ImportError: sync_playwright = None`.
  - Modify `seo_crawler.py:analyse` (`seo_crawler.py:209`) to call
    `render_with_playwright(response.url)` only when
    `crawl_options.ssr_parity_check` is True; store result under
    `raw_payload["render"]`.
  - Modify `crawl_options.py::CrawlOptions` to add
    `ssr_parity_check: bool = False`.
  - Modify `settings_dialog.py::CrawlSettingsDialog` to add the
    checkbox described in §3, with `setEnabled(False)` and an
    explanatory tooltip when `playwright` is not importable.
- **NEW_DEPS**: True. `playwright (>=1.43,<2.0)`, optional group
  `geo-render` under `[project.optional-dependencies]`. Install:
  `pip install 'silentfrog[geo-render]' && playwright install chromium`.
  Reason: canonical headless render for JS-capable AI crawler parity;
  Selenium / Pyppeteer alternatives have heavier drivers or are
  unmaintained.
- **UX changes**: 1 new row in the Access area. Checkbox in
  `CrawlSettingsDialog`. README section 1 (Prerequisites) gains a
  line: "Optional: `pip install silentfrog[geo-render]` then
  `playwright install chromium` to enable the SSR parity check."
- **Acceptance criteria**:
  - `tests/test_render_diff_unit.py` (new) ≥ 8 cases: parity-good,
    parity-warning, parity-critical, playwright-not-installed
    (`sync_playwright is None` → `"not_measured"`,
    `build_ai_visibility_summary` does NOT down-weight),
    playwright-raises (→ `"warning"` with detail
    `"Render failed: <message>"`), empty render → `"critical"`,
    identical HTML → `"good"`, plus smoke test on a fixture pair.
  - Mocking strategy in §6: `render_with_playwright` is
    monkeypatched to return a precomputed `RenderResult` from a
    fixture. Test module never imports real `playwright`; CI runs
    without the optional extra (it stays out of `python-compat.yml`).
  - Fixtures: as listed in §6. `tools/doctor.py` passes. README
    capability row → "Strong" (6/7 pillars).
- **New check_keys**:
  - `access_ssr_parity` — *"Checks whether the page rendered
    without JavaScript matches what a JS-capable engine would see.
    Best practice: render critical content server-side; AI
    crawlers commonly fetch without executing JS. When Playwright
    is not installed this check reports `not measured` and does
    not affect the verdict."*
- **Effort**: 3.5 days.
- **Risk**: High — Playwright browser bundle download (~150 MB) is
  a sharp UX edge, especially on macOS Apple Silicon where the ARM
  bundle wasn't always shipped. See risk register.
- **Cooldown impact**: M4 is the first `NEW_DEPS: True`
  milestone. The required cooldown buffer before M5 ships is
  filled by the v1.0 release gate (M5 is post-1.0 by definition).

### M5 — Semantic coverage + query simulation, post-1.0 (NEW_DEPS: True — NLP)

- **Goal** *(stretch)*: estimate semantic completeness of the page
  for its primary query, and simulate the dominant intents an AI
  assistant would surface.
- **Scope**:
  - New `src/silentfrog/semantic_coverage.py`:
    - `def estimate_semantic_coverage(plain_text: str, keywords: list[KeywordEntry], language: str) -> SemanticCoverage`
    - `@dataclass(frozen=True) class SemanticCoverage: primary_topic: str; covered_entities: tuple[str, ...]; missing_entities: tuple[str, ...]; coverage_ratio: float`
  - New `src/silentfrog/query_simulation.py`:
    - `def simulate_query_intents(primary_topic: str, content: str, language: str) -> QueryIntentReport`
    - `@dataclass(frozen=True) class QueryIntentReport: dominant_intent: Literal["informational","navigational","transactional","mixed"]; intent_coverage: dict[str, float]`
  - Hook both into
    `ai_visibility._build_topic_clarity_checks`.
- **NEW_DEPS**: True. `spacy (>=3.7,<4.0)`,
  `sentence-transformers (>=2.7,<3.0)`; optional group `geo-nlp`.
  Install: `pip install 'silentfrog[geo-nlp]' && python -m spacy
  download en_core_web_sm it_core_news_sm`. Reason: entity recognition
  + sentence embeddings drive coverage and intent heuristics.
- **UX changes**: 2 new rows in Topic clarity area. README
  section 1 gains a second optional install line. No GUI change
  beyond the rows.
- **Acceptance criteria**:
  - `tests/test_semantic_coverage_unit.py` (new) ≥ 5 cases, spaCy
    fully stubbed (no model download in CI).
  - `tests/test_query_simulation_unit.py` (new) ≥ 5 cases, same
    stubbing strategy.
  - Fixtures: `semantic_coverage_sample_en.txt`,
    `semantic_coverage_sample_it.txt`,
    `query_simulation_informational.txt`,
    `query_simulation_transactional.txt`.
  - `tools/doctor.py` passes without the `geo-nlp` extra.
  - README capability matrix: "GEO Visibility Score" reaches
    "Stretch / experimental".
- **New check_keys**:
  - `topic_semantic_coverage` — *"Checks whether the page covers
    the semantic neighbourhood of its declared topic. Best
    practice: include the entities and sub-topics generative
    engines expect for the page's primary query, not just the
    headline keyword."*
  - `topic_query_intent_coverage` — *"Checks whether the page
    satisfies the dominant intents (informational, navigational,
    transactional) attached to its main query. Best practice:
    cover the explicit ask plus the related follow-up questions
    an AI assistant would likely surface."*
- **Effort**: 5 days.
- **Risk**: High — spaCy + sentence-transformers bring a heavy
  install footprint (≈ 500 MB). Mitigated by being optional and
  post-1.0.
- **Cooldown impact**: Time-gated. M5 ships **after v1.0 release**;
  the calendar gap between M4 ship and v1.0 release acts as the
  enforced cooldown buffer between the two NEW_DEPS:True
  milestones. The dependency table records this explicitly.

## 5. Dependencies & cooldown

| Library | Milestone | Group | License | Reason | Estimated cooldown hours |
|---|---|---|---|---|---|
| `extruct` | M0 | runtime (reclassified) | BSD-3 | Already imported at runtime in `schema_extractor.py:21`; moves from dev to runtime — no new dep | 0 (reclassification) |
| `w3lib` | M0 | runtime (reclassified) | BSD-3 | Same path as `extruct`; the unused `get_base_url` import is removed | 0 |
| `playwright` | M4 | optional `[geo-render]` | Apache-2.0 | Headless Chromium render for SSR parity | 24 h before M5 may ship (covered by the v1.0 release gate) |
| `spacy` | M5 | optional `[geo-nlp]` | MIT | Entity recognition for `semantic_coverage` | 24 h before any subsequent NEW_DEPS milestone |
| `sentence-transformers` | M5 | optional `[geo-nlp]` | Apache-2.0 | Sentence embeddings for topic / intent scoring | 24 h before any subsequent NEW_DEPS milestone |

**Adjacency check**: M0/M1/M2/M3 carry NEW_DEPS:False. M4 carries
NEW_DEPS:True. M5 also carries NEW_DEPS:True but is explicitly
post-1.0; the v1.0 release calendar gap (estimated ≥ 1 week) more
than covers the 24-hour cooldown buffer. No two adjacent in-flight
milestones share NEW_DEPS:True.

## 6. Test plan

| Milestone | New test file(s) | Case count | Fixture files |
|---|---|---|---|
| M0 | extend `tests/test_schema_extractor_unit.py` | +8 | `schema_person_valid.json`, `schema_person_missing_name.json`, `schema_howto_valid.json`, `schema_howto_missing_step.json`, `schema_website_valid.json` |
| M1 | `tests/test_discovery_files_unit.py` (new); extend `tests/test_ai_visibility_unit.py` (+4), `tests/test_parsers_meta_unit.py` (+4) | 12 + 4 + 4 | `llms_txt_allow.txt`, `llms_txt_block.txt`, `llms_full_txt_minimal.txt`, `well_known_ai_allow.json`, `well_known_ai_block.json`, `sitemap_via_robots.txt`, `sitemap_at_root.xml` |
| M2 | `tests/test_eeat_signals_unit.py` (new), `tests/test_structure_signals_unit.py` (new); extend `tests/test_ai_visibility_unit.py` (+9) | 12 + 8 + 9 | `eeat_full_signals.html`, `eeat_no_byline.html`, `eeat_stale_dated.html`, `eeat_external_citations.html`, `structure_semantic_full.html`, `structure_divsoup.html`, `structure_internal_links_rich.html`, `structure_images_alt_mixed.html` |
| M3 | `tests/test_citation_readiness_content_unit.py` (new); extend `tests/test_ai_visibility_unit.py` (+3) | 12 + 3 | `citation_question_headings_en.html`, `citation_question_headings_it.html`, `citation_stats_density.html`, `citation_definitions.html` |
| M4 | `tests/test_render_diff_unit.py` (new) | 8 | `render_diff_ssr_complete.html`, `render_diff_ssr_missing_h1.html`, `render_diff_jsr_only.html` |
| M5 | `tests/test_semantic_coverage_unit.py` (new), `tests/test_query_simulation_unit.py` (new) | 5 + 5 | `semantic_coverage_sample_en.txt`, `semantic_coverage_sample_it.txt`, `query_simulation_informational.txt`, `query_simulation_transactional.txt` |

Mocking strategy for `render_diff` (M4): the test module
**never** imports `playwright`. Tests monkeypatch
`silentfrog.render_diff.render_with_playwright` to return a
`RenderResult` built from a fixture file. The
`sync_playwright is None` branch is exercised by setting that
module attribute to `None` in the test setup. This mirrors the
pattern in `tests/test_http_client.py:10` where
`aiohttp.ClientSession` is replaced with `DummySession`.

For M5 the spaCy and sentence-transformer dependencies are
likewise replaced with stub callables in the test module
(no model download in CI).

## 7. Risk register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| False positives on non-EN/IT question headings (M3) | Medium | Low | `citation_readiness_content` skips pattern checks when `content_quality.language` is neither `en` nor `it` and emits `status="info"` with detail `"Language not supported for content patterns"`. |
| Site Crawl runtime balloons when render_diff is enabled (M4) | High | Medium | `ssr_parity_check` is opt-in via `CrawlSettingsDialog`, default off. When enabled, expect ≈ 2–5 s per URL. |
| extruct vs manual-fallback divergence after Person / HowTo / WebSite (M0) | Medium | Low | Both paths feed `_annotate_schema_blocks` which calls `_SCHEMA_VALIDATORS`; validators see the same normalised dict. Parity test in `tests/test_schema_extractor_unit.py` asserts the same Person fixture yields identical errors through both. |
| AI Visibility tab visual saturation past 22 rows | Medium | Low | `TableTab` (`tabs.py:433`) has built-in sorting; 25 rows after M4 is still browsable. Filter combobox is a future option, not blocking. |
| Playwright cross-platform compatibility (Windows + macOS Intel + ARM × Python 3.12/3.13/3.14) | Medium | High | Pin `playwright >= 1.43` (first version with stable Apple Silicon ARM bundle). Any `ImportError`, `PlaywrightTimeoutError`, or browser-launch failure → `status="warning"` with reason in `details`; analysis never crashes. CI does NOT install the optional extra. |
| `tools/code_shape_guard.py` failures from branch-heavy new functions | Medium | Medium | Per-check builders follow the `_check(...)` helper pattern (`ai_visibility.py:230`) and the constants-map dispatch (`_AI_VISIBILITY_CHECK_TOOLTIPS` at `ai_visibility.py:58`). Per AGENTS.md §1, depth ≤ 2 — extract helpers, do NOT grow `code_shape_baseline.json`. |
| Tooltip rewording drifts away from the §1.5 Google-myth disclaimers | Medium | Medium | Unit test in `tests/test_ai_visibility_unit.py` asserts the substring `"Per Google's AI Optimization Guide"` (or `"Google-not-required"`) is present in every tooltip for the 6 myth-flagged check_keys. |
| The 4 Google-aligned positive checks penalise pages that miss them | Low | Medium | Each emits `"good"` when present, `"info"` (→ "good") when absent — never `"warning"` or `"critical"`. Parametrised assert in `tests/test_ai_visibility_unit.py` enforces this for `access_sitemap`, `structure_semantic_html`, `structure_internal_links`, `citation_images_alt`. |

## 8. Out of scope

- Real-time monitoring of AI engine citations (would need integration with third-party SERP/AI tracking APIs).
- Auto-fix mode that rewrites HTML for missing fields.
- Visual / accessibility scoring (this remains the SEO crawler's
  job, not GEO's).
- Authentication-protected pages.
- Sitemap-level GEO Score aggregation beyond the existing Site
  Crawl detail dialog reuse.
- Code signing or notarisation of the binary (orthogonal to GEO).

## 9. Definition of done

- ☐ ≥ Partial coverage on each of the 7 GEO pillars (Access, Topic
  clarity, Answerability, Citation readiness, Entity clarity, E-E-A-T,
  SSR parity). M5 semantic coverage is bonus.
- ☐ `AI_VISIBILITY_AREAS` lists 6 entries; `AiVisibilityTab` renders
  ≥ 22 checks (today 13; expected after M4: 28).
- ☐ `payload.ai_visibility.summary.score` is a non-`None` int in
  [0, 100], shown in the tab header.
- ☐ `exporters/excel.py` writes `"GEO Score"`;
  `exporters/site_crawl_excel.py` writes `"GEO Score"` and
  `"GEO Score detail"`.
- ☐ `poetry run python tools/doctor.py` passes on Windows + macOS
  Intel + macOS Apple Silicon, with and without `geo-render`.
- ☐ README capability row "GEO Visibility Score" reads "Strong"
  (or "Stretch / experimental" if M5 has shipped).
- ☐ `AGENTS.md` updated only if optional-extras handling introduces a
  new convention (expectation: no change).
- ☐ No check_key emits `warning` or `critical` for absence of a §1.5
  Google-myth signal; enforced by the §7 parametrised test.
- ☐ Every tooltip for the 6 myth-flagged check_keys contains the
  Google-myth disclaimer substring documented in §1.5.
