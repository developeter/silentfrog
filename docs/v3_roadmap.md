# Silentfrog v3 Roadmap — Gap analysis vs Screaming Frog / Sitebulb / Ahrefs / GEO tools

> Drafted 2026-07-06 from a three-way review: full feature inventory of the
> shipped v2.0 tree, competitor research (Screaming Frog v21–v24, Sitebulb,
> Ahrefs/Semrush Site Audit, Profound/Peec/Otterly/AthenaHQ, OSS crawlers),
> and a GUI design assessment with rendered screenshots.
> v2.0 (V1..V20) is complete; this is the candidate scope for what's next.

## Where Silentfrog stands (July 2026)

- **Crawl/storage/GEO plumbing already exceeds every open-source entrant**
  (greenflare is dead since 2021; crawl4ai is a scraping pipeline, not an
  auditor) and matches desktop leaders at the 100k-URL verified scale.
- The moat is real: per-bot access matrix + per-bot SSR rendering, Princeton
  GEO methods, llms.txt/ai.json parsing, local topic embeddings, brand-mention
  time-series, log-based crawl-budget audit — no OSS or desktop tool bundles
  these.
- The exposure is **packaging, not plumbing**: raw checks instead of
  prioritized recommendations, Excel-only reporting, a developer-styled GUI,
  and no in-engine AI-visibility measurement.

## Gap catalogue (ranked by user value)

Three themes: **A** — turn checks into prioritized, trended, reportable
recommendations; **B** — local-first AI-visibility measurement (BYO keys);
**C** — visual/automation surfaces.

> **Status (2026-07-06):** G1 ✅ shipped · G12 ✅ (delivered via G1) · plus,
> outside this table: JS-rendered link crawl (M8) ✅, reopenable past scans ✅,
> Multi-URL Dashboard retired ✅, Lighthouse button fixed ✅, GUI token pass ✅.
> Remaining top gaps: G2, G3 (policy decision), G4, G8, G9.
>
> **Update (2026-07-20):** execution queue decided by the operator —
> **G2 → G3 → G4 → G5 → G6**, then the remaining must-haves (G8, G9), then
> nice-to-haves. The G3 policy question is resolved: the v2.0 "no new
> AI-engine APIs" lockout is reopened strictly as BYO-key opt-in (OFF by
> default, user-supplied keys only). G2 ✅ and G3 ✅ shipped the same day;
> G4 ✅, G5 ✅ and G6 ✅ shipped 2026-07-21 — the first operator queue is
> complete. Second queue (2026-07-21): G8 ✅ and G9 ✅ shipped — every
> must-have is done — and the fake `ai_citations_perplexity` proxy is
> retired (real coverage: `sov_perplexity`). G11 ✅ shipped. Remaining:
> G10 → G7 → G13 → G14 → G15.

| # | Theme | Gap | Competitor precedent | Notes |
|---|---|---|---|---|
| G1 ✅ | A | **Prioritized hints engine** — severity + plain-English *why* + *how to fix* per finding | Sitebulb Hints (300+), Semrush thematic reports | SHIPPED: `hints.py` + recap. Data already existed in check details/recommendations; this is the ranking + grouping layer |
| G2 ✅ | A | **Audit health score + per-issue trend history** across stored crawls | Ahrefs always-on audits, Sitebulb Audit Scores | SHIPPED: `crawl_trends.py` pure derivation over `CrawlHistoryStore` + Trends panel (health-score series chart + per-issue count chains with signed deltas) in the past-scans dialog |
| G3 ✅ | B | **AI citation share-of-voice** — BYO-key prompt sampling of ChatGPT/Perplexity/Gemini with mention/citation/sentiment scoring | Profound ($499+/mo), Peec, Otterly ($29/mo) | SHIPPED: `integrations/ai_engines/` (plain REST, no SDKs, per-host once-per-session sampling memo), "AI Share of Voice" checks area + badge group, Settings BYO-key group, local JSON history. Strictly opt-in: `SILENTFROG_AI_SOV_ENABLE=1` + keys |
| G4 ✅ | A | **Accessibility auditing** (axe-core, WCAG 2.1/2.2) | SF v21 ships Deque AXE (~90 rules) | SHIPPED: vendored axe-core 4.10.3 (MPL-2.0, `_vendor/`) injected via the render pool's new `inject_js`/`evaluate_js` seam; opt-in flag + DEEP profile; issues (impact→severity map) + Accessibility tab (Trust bucket) + Excel sheet |
| G5 ✅ | C | **Interactive visualisations** — force-directed link graph, content-cluster map | SF force-directed/3D + v22 content clusters | SHIPPED: link graph was already live (V9); G5 added the Topic map — per-page embedding vectors retained in the payload (opt-in flag), `content_clusters.py` KMeans+PCA (rides the locked `[embeddings]` extra, zero new deps), cluster-scatter dialog with bounded store scan |
| G6 ✅ | C | **MCP server** (`silentfrog-mcp serve`) | SF v24 shipped MCP | SHIPPED: hand-rolled stdlib JSON-RPC/stdio server (`mcp_server.py`, zero new deps — supersedes V18's planned `mcp` extra); tools: `audit_page` (STANDARD default, TLS/SSRF guards inherited), `list_crawls`, `get_crawl_summary` |
| G7 | B | **Custom AI prompts over crawl data** (Ollama/OpenAI/Anthropic BYO key, per-page) | SF v21 AI tab (100 prompts) | Local Ollama default keeps the local-first story |
| G8 ✅ | A | **Client-ready HTML/PDF report export** | Sitebulb's consultant staple | SHIPPED: `exporters/html_report.py` — one self-contained inline-CSS HTML (SVG charts, @media print, everything escaped), "Export HTML report" button; single-stream via new `issues_for_results` (Excel's double-stream not copied) |
| G9 ✅ | C | **Scheduled runs + notifications with auto-diff digest** (email/webhook) | SF v24 auto-compare, Sitebulb alerts | SHIPPED: one-shot `silentfrog-cli crawl` (headless, store-backed, saved to history so the GUI reopens it) + history-diff digest; `alert_transport.py` webhook (aiohttp) + email (stdlib SMTP, keyring password); scheduling via OS Task Scheduler/cron — no daemon |
| G10 | B | **llms.txt generator/validator** | Sitebulb ships one | Cheap; complements the existing per-bot matrix |
| G11 ✅ | B | **AI-agent log analytics view** — classify 40+ AI crawlers in the existing log module | Peec server-log integration (€169/mo tier) | SHIPPED: taxonomy 20→48 signatures (30 ai_*) with vendor/kind, `classify_bot`, `CrawlBudgetReport.ai_agents` section, three additive AI findings in `log_analysis` (no_activity=info per §1.5), CLI summary. GUI log window stays M6-deferred |
| G12 ✅ | A | **"Blocked from AI Search" rollup + AI Readiness Score** | Semrush AI widget, Rankscale score | DELIVERED VIA G1: AI-access checks flow into `ai_geo.*` issues, so `build_hints` groups them into "AI crawler blocked — N pages" site-wide. A separate AI-readiness number would duplicate the existing GEO Score — deliberately not added |
| G13 | B | **Semantic redirect mapping** (embedding old→new URL matching for migrations) | SF v23 | Embeddings extra already in the tree |
| G14 | A | **Uncrawlable link detection** (onclick/span/div pseudo-links) | SF v24 | Small crawl-layer check |
| G15 | A | **Spelling/grammar** | SF classic | Low effort with local dictionaries; multilingual caveat |

Also observed in-tree (not competitor-driven): 1M-URL scale is still
aspirational (100k verified); spider follows raw-HTML links only (no
rendered-DOM link discovery for SPA route graphs); no first-party backlink
index (Semrush-only by design).

## Suggested v3 milestone ordering

Tier S (identity): **G1 hints engine → G2 health score + trends → G12 AI
readiness rollup** — these three convert the existing check corpus into "an
audit" and cost mostly presentation work.
Tier A (moat expansion): **G3 share-of-voice (policy decision first) → G11
AI-agent log view → G10 llms.txt generator → G4 accessibility**.
Tier B (reach): **G8 HTML report → G5 visualisations → G6 MCP → G9
scheduling/alerts → G7 custom prompts**.
Tier C (parity nits): G13, G14, G15.

## Notable absences — verdict (2026-07-06)

**Must-have** (without these it is not a credible alternative to the paid tools):

| Rank | Absence | Why it gates adoption |
|---|---|---|
| M1 ✅ | Prioritized hints engine (G1) | Raw checks ≠ an audit; every competitor leads with "what do I fix first" |
| M2 ✅ | Fully browsable past scans | Stored runs users can't reopen page-by-page make the SQLite store invisible value |
| M3 ✅ | Health score + issue trends (G2) | The retention loop: "is my site getting better?" is THE recurring question |
| M4 ✅ | AI readiness rollup / "Blocked from AI Search" (G12) | The moat data exists but has no headline surface |
| M5 ✅ | Client-ready HTML report (G8) | Consultants demo with reports, not Excel |
| M6 ✅ | Accessibility audits via axe-core (G4) | Table stakes since Screaming Frog v21; legal pressure makes it a checklist item |
| M7 ✅ | Scheduled re-crawl + alert digest (G9) | Watch mode exists; without transport (email/webhook) it's a demo |
| M8 ✅ | Rendered-DOM link discovery for SPAs | Spider misses JS-routed sites entirely — a correctness gap, not a feature |

**Nice-to-have** (differentiators or parity nits, after the must list):
MCP server (G6) · custom AI prompts w/ Ollama (G7) · force-directed/cluster
visualisations (G5) · llms.txt generator (G10) · AI-agent log analytics view
(G11) · semantic redirect mapping (G13) · uncrawlable-link detection (G14) ·
spelling/grammar (G15) · WARC export · crawl segments · sitemap generation.

**Deliberately out** (policy, unchanged from v2.0): cloud/SaaS/team features,
telemetry, first-party backlink index (Semrush BYO-key covers it), keyword
rank tracking (needs SERP scraping infra), white-label/multi-tenant.

**Removed in v3**: the Multi-URL Dashboard (duplicate of Site Crawl's URL-list
mode; its GEO-Score-per-URL view moves to the Site Crawl results table).

## GUI redesign (Stage B, prerequisite polish shipped separately)

Assessment verdict: functional, dark-mode-first, "developer-styled" — closer
to Screaming Frog than Sitebulb. Highest perceived-quality movers, all plain
Qt Widgets:

1. **Status pills/badges instead of flooded table cells** + **table restyle**
   (36px rows, zebra, no gridlines, flat headers) — the app is 80% tables.
2. **Design tokens + full-widget QSS pass** (combos, spinners, scrollbars,
   progress bars are default-Qt today; light theme has inverted-looking
   selected tabs and dark borders).
3. **Recap redesign into stat tiles + structured issue rows** — the first
   screen after every audit is currently the least designed.

Then: segmented/underline tab nav, form layout caps + grouping on Site
Crawl/Redirect/Dashboard, SVG icon set, guided empty states, chart/sparkline
polish.
