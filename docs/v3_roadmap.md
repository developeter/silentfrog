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

| # | Theme | Gap | Competitor precedent | Notes |
|---|---|---|---|---|
| G1 | A | **Prioritized hints engine** — severity + plain-English *why* + *how to fix* per finding | Sitebulb Hints (300+), Semrush thematic reports | Biggest UX gap; most data already exists in check details/recommendations — this is a presentation + curation layer |
| G2 | A | **Audit health score + per-issue trend history** across stored crawls | Ahrefs always-on audits, Sitebulb Audit Scores | SQLite runs already persist everything; longitudinal issue charts are presentation work |
| G3 | B | **AI citation share-of-voice** — BYO-key prompt sampling of ChatGPT/Perplexity/Gemini with mention/citation/sentiment scoring | Profound ($499+/mo), Peec, Otterly ($29/mo) | The whole $300M GEO category, local-first; no OSS equivalent exists. Needs a "new AI-engine APIs" policy decision (v2.0 locked this out; v3 can reopen it as strictly BYO-key opt-in) |
| G4 | A | **Accessibility auditing** (axe-core, WCAG 2.1/2.2) | SF v21 ships Deque AXE (~90 rules) | Rides the existing render pool; axe-core JS injectable via Playwright |
| G5 | C | **Interactive visualisations** — force-directed link graph, content-cluster map | SF force-directed/3D + v22 content clusters | Link graph + local embeddings already exist; clustering = presentation |
| G6 | C | **MCP server** (`silentfrog-mcp serve`) | SF v24 shipped MCP | Was V18, dropped in v2.0; SF validated the bet — revive it |
| G7 | B | **Custom AI prompts over crawl data** (Ollama/OpenAI/Anthropic BYO key, per-page) | SF v21 AI tab (100 prompts) | Local Ollama default keeps the local-first story |
| G8 | A | **Client-ready HTML/PDF report export** | Sitebulb's consultant staple | Excel doesn't demo well; single self-contained HTML first, print-to-PDF free |
| G9 | C | **Scheduled runs + notifications with auto-diff digest** (email/webhook) | SF v24 auto-compare, Sitebulb alerts | Watch mode exists; missing the alerting transport + scheduling |
| G10 | B | **llms.txt generator/validator** | Sitebulb ships one | Cheap; complements the existing per-bot matrix |
| G11 | B | **AI-agent log analytics view** — classify 40+ AI crawlers in the existing log module | Peec server-log integration (€169/mo tier) | bot_fingerprint.py already exists; extend taxonomy + dedicated view |
| G12 | A | **"Blocked from AI Search" rollup + AI Readiness Score** | Semrush AI widget, Rankscale score | Pure repackaging of existing robots-matrix/GEO data |
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
