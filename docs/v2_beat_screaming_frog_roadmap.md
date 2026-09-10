# Silentfrog v2.0 Roadmap — V1..V20

> Durable source of truth for v2.0 milestone scope + ordering.
> Supersedes the earlier V1..V9 draft. Per-task execution plans live
> (ephemerally) under `.claude/plans/`.

## Goal

v1.1 gave Silentfrog the GEO moat (CWV, CrUX, Princeton GEO methods, AI
citation tracking, the 19-bot Bot Matrix, watch mode). v2.0's explicit
goal is to **crawl very large sites completely (up to ~1M URLs)**, raise
the information density of the audit, beat Screaming Frog on its own
turf, and surface signals nobody else gives.

## Two findings that shaped the plan

1. **The "whole-site crawl" is not a crawl.** `resolve_site_urls`
   ([site_crawler.py](../src/silentfrog/site_crawler.py)) only audits
   URLs from a sitemap, an auto-discovered sitemap, or a manual list —
   **zero link-following**. Pages absent from a sitemap are never
   visited. Every audited page already produces `payload.links`, so the
   data for a real spider exists; it is discarded after each page.
   Making the crawl truly whole-site is the headline Tier-S milestone
   (**V3**).
2. **The real OOM driver is `SiteCrawlResult.payload`.** Every crawled
   URL keeps its full `CrawlPayload` in an in-memory list, sorted O(n²)
   at the end. At 1M URLs this is impossible. The fix is a streaming
   SQLite store with on-disk payload blobs (**V2**).

## Locked decisions

| Topic | Decision |
|---|---|
| Scale target | Up to ~1M URLs. Streaming SQLite, zlib payload blobs, flat RAM, sampled link graph. |
| Crawl default | **Hybrid** — seed frontier with (sitemap ∪ base URL), then spider-follow same-host links; union + dedupe. |
| LLM export | Markdown + JSON, compact-by-default, GUI button + CLI, self-describing prompt preamble. |
| Stealth fetcher (V1) | Off by default, opt-in via Settings. |
| Semrush rate (V17) | Per-user configurable max-calls-per-day (default 100). |
| GUI redesign (V19) | Stage A only — PyQtGraph + tab regroup. No local web dashboard in v2.0. |
| V20 AI engines | No new AI-engine APIs. Reuse Brave + Common Crawl + local embeddings. |
| GSC/GA4 OAuth (V7) | System-browser loopback redirect (RFC 8252) — no QtWebEngine. |
| MCP (V18) | Standalone `silentfrog-mcp serve` console script. |
| Robots simulator (V16) | Nested in Settings → Tools. |

## Out of scope for v2.0

PDF export · white-label / multi-tenant · proprietary backlink datasets
(V12 = Common Crawl only; V17 plugs the user's own Semrush key, never
ships Semrush data) · cloud sync / telemetry · new AI-engine API clients
(OpenAI/Anthropic/Perplexity) · multilingual UI (audit *signals* stay
multilingual; UI stays English) · mobile/web apps.

## Operating principles (from AGENTS.md — every milestone)

- **Code shape** (`tools/code_shape_guard.py`): max nesting 2, no
  `if/elif` string dispatch, 80-line function cap, baseline must not
  grow.
- **Types**: frozen dataclasses across module boundaries, not dicts.
  Parsing / derivation / orchestration / UI stay in separate functions.
- **Tests**: focused unit tests near the change; GUI uses pytest-qt +
  smoke-render PNGs; CI diff-cover ≥85% on touched files.
- **Supply chain**: deps ≥48h old (PyPI JSON), pinned, `poetry.lock`
  committed; heavy deps behind optional extras.
- **GUI**: centralised theme; §1.5 myth rule (absent not-required signal
  ⇒ `info`, never warning/critical).
- **Back-compat**: payload keys add-only; new Settings default off (sole
  exception: V3 crawl-mode default → Hybrid, documented in README).

## Milestone catalogue

Tiers: **S** scale foundation · **A** parity + high user value ·
**B** push-ahead / unique info · **C** strategic. Execution is strict
V1 → V20; **V1–V4 (Tier S) must come first and in order**.

| V | Tier | Depends | Milestone |
|---|---|---|---|
| V1 | S | — | Fetcher strategy (Scrapling: aiohttp → curl_cffi → stealth browser) |
| V2 | S | — | Streaming SQLite crawl store (~1M, zlib blobs, resume) |
| V3 | S | V1,V2 | **True hybrid spider crawl** (frontier + robots matcher) |
| V4 | S | V2 | Concurrent Playwright render pool |
| V5 | A | V2 | **LLM-friendly export** (Markdown+JSON, compact, prompt preamble) |
| V6 | A | — | Custom CSS/XPath/regex extraction |
| V7 | A | V2 | GSC + GA4 integration (system-browser OAuth) |
| V8 | A | V2 | Crawl comparison / diff view |
| V9 | A | V2,V3 | Link graph + sitemap visualisation (sampled) |
| V10 | B | V4 | Per-bot SSR rendering |
| V11 | B | — | Per-agent ai.json + llms.txt parsing |
| V12 | B | — | Common Crawl backlink harvest |
| V13 | B | — | Server log parser + crawl-budget audit |
| V14 | B | — | Lighthouse + Rich Results API |
| V15 | B | — | Wappalyzer-style tech stack detection |
| V16 | B | V3 | Robots.txt simulator + hreflang depth |
| V17 | C | V2 | Semrush API integration |
| V18 | C | — | Silentfrog MCP server |
| V19 | A | — | GUI redesign (PyQtGraph + tab regroup) |
| V20 | C | V19 | Topic embeddings + brand-mention time-series |

### V1 — Fetcher strategy (Scrapling) · Tier S

Replace the single `aiohttp` call site
([seo_crawler.py](../src/silentfrog/seo_crawler.py)) with a 3-stage
fallback (`Fetcher` curl_cffi → `StealthyFetcher` browser → `aiohttp`
when `scrapling` absent). New `src/silentfrog/fetchers/` package with
frozen `FetchRequest`/`FetchResult`/`FetchOptions`. Optional extra
`stealth`. Settings checkbox off by default (done — v2.0 R1: reachable
in Settings → Advanced, gated on the extra like the other opt-in
checks). The promised `access_fetch_backend` info check was dropped in
v2.0 R1: purely diagnostic, and not worth a permanent AI Visibility row.

### V2 — Streaming SQLite crawl store (~1M) · Tier S

New `crawl_store.py` + `crawl_store_schema.py`: SQLite WAL, `runs` +
`audits` tables, zlib-compressed payload blob + duplicated lightweight
columns, streaming batched writes, insertion-order column (kills the
O(n²) sort), `resume_pending()`. `SiteCrawlTableModel` gains a paged
provider. JSON `crawl_history` imported on first launch.

### V3 — True hybrid spider crawl · Tier S

`CrawlMode` enum (`SITEMAP|LIST|SPIDER|HYBRID`, default HYBRID). Extend
`SiteCrawlConfig` with `mode`, `max_depth`, `max_urls` (≤1M),
`respect_robots`, `politeness_delay_ms`, `follow_subdomains`. New
`frontier.py` (`CrawlFrontier`: dedup, depth, scope, robots filtering,
per-host politeness) + `robots_matcher.py`. Frontier-driven worker loop
extracts same-host links from `payload.links` and enqueues unseen ones.
Hybrid seeding = sitemap ∪ base URL. Configurable concurrency. New
`crawl_orphan_*` checks. Site Crawl gets a Crawl-mode selector.

### V4 — Concurrent Playwright render pool · Tier S

New `render_pool.py` — fixed pool of long-lived browsers, recycled every
N pages, `async with pool.lease()`. Replaces per-URL launch in
`render_diff.py`. Settings: concurrent renders + recycle threshold.

### V5 — LLM-friendly export · Tier A

New `exporters/llm_export.py` — `export_for_llm(target, mode, fmt)`,
compact + both by default. Self-describing prompt preamble. Single-page
= full detail; site-crawl = rollup + worst-N. JSON mirror. GUI "Export
for AI analysis" button (single-page + Site Crawl) + `silentfrog-cli
export --format llm`.

### V6–V20

See the milestone table above and the per-task plans under
`.claude/plans/` for full detail. Summary:

- **V6** Custom extraction (`custom_extraction.py`, sandboxed
  CSS/XPath/regex, ≤10 rules). Rules are configured in Settings and the
  results reach the LLM export; the promised dedicated Site Crawl tab
  was NOT built (nice-to-have, see v2_0_release_roadmap.md §8).
- **V7** GSC+GA4 (`integrations/google/`, RFC 8252 OAuth, `keyring`,
  8 checks, "Top GEO opportunities" widget). Extra `google`.
- **V8** Crawl diff (`crawl_diff.py`, new Diff tab, feeds LLM export).
- **V9** Link graph (`link_graph/`, in-tree force-directed layout,
  sampled at scale, new Graph tab, 2 checks).
- **V10** Per-bot SSR rendering (per-UA renders via V4 pool, 19 checks,
  off by default).
- **V11** Per-agent ai.json + llms.txt parsing (per-bot llms.txt
  column, 2 checks).
- **V12** Common Crawl backlinks — **NOT BUILT.** Dropped in favour of
  the V17 Semrush integration; there is no `backlinks/` package, no tab
  and no checks (see v2_0_release_roadmap.md §8).
- **V13** Server log parser + crawl budget (`logs/`, new window, 5
  checks).
- **V14** Lighthouse + Rich Results API (`integrations/google/`, 6
  checks). Extra `google`.
- **V15** Tech stack detection (`tech_stack.py`, vendored
  wappalyzer.json, new tab, 3 checks).
- **V16** Robots simulator + hreflang depth (`robots_simulator.py`,
  `hreflang_validator.py`, 3 checks). Robots-simulator surface done —
  v2.0 R1: `robots_sim_dialog.py`, launched from Settings → Advanced;
  hreflang depth unchanged.
- **V17** Semrush integration (`integrations/semrush/`, keyring, per-user
  rate cap, 6 checks). Extra `semrush`.
- **V18** MCP server (`mcp_server.py`, `silentfrog-mcp serve`). Extra
  `mcp`.
- **V19** GUI redesign (PyQtGraph charts + 5 user-goal tab buckets).
  Extra `charts`.
- **V20** Topic embeddings + brand mentions (`embeddings/`,
  `brand_mentions/`, Brave + Common Crawl + local sentence-transformers,
  3 checks). Extra `embeddings`.

## Definition of Done

- `CLAUDE.md` at repo root (done).
- V1..V20 shipped, each with a focused plan + tests.
- Whole-site crawl follows links (V3) and streams ≥1M URLs at flat RAM
  (V2).
- LLM export is paste-ready Markdown+JSON with a prompt preamble (V5).
- `doctor.py` (full) + `quality_gates.py` green every PR;
  `code_shape_baseline.json` unchanged.
- Install base needs zero new deps; heavy deps behind extras.
- diff-cover ≥85% on touched files.

## Hardening prerequisite before V19

The active H0-H7 hardening plan under `.claude/plans/` is the release gate
for V19. Its final task is **PR-21 — Documentation and release alignment**:

- align `README.md`, `HANDOFF.md`, `CLAUDE.md`, and relevant public docs with
  shipped behavior;
- distinguish the verified 100k synthetic gate from aspirational 1M support;
- document crawl profiles, persistence/resume, paging, security and updater
  trust, and known limits;
- verify public CLI, Settings, and installation instructions against the app;
- remove obsolete or contradictory claims.

PR-21 is documentation-only except for focused checks that prevent stale
public documentation. The H0-H7 gate cannot close, and V19 cannot begin, until
PR-21 is complete.
