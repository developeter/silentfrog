# Silentfrog — Handoff

Last updated: 2026-07-20

**Start here.** This is the entry point for a new session: what shipped, where
we are, what's next. Read this first, then the linked sources for depth — the
durable detail lives there, not here.

- **Contract & map:** [`AGENTS.md`](AGENTS.md) (operating rules) · [`CLAUDE.md`](CLAUDE.md) (repo map, key dirs) · [`docs/PLAYBOOKS.md`](docs/PLAYBOOKS.md) (mechanical recipes — read the matching one BEFORE adding a check / payload key / opt-in feature / dependency / audit issue, or touching GUI styling)
- **Roadmaps (three, related — see "How the roadmaps fit" below):** [`PLAN.md`](PLAN.md) (product direction, M0–M9) · [`docs/v2_beat_screaming_frog_roadmap.md`](docs/v2_beat_screaming_frog_roadmap.md) (the V1–V20 build, complete) · [`docs/v3_roadmap.md`](docs/v3_roadmap.md) (post-v2 gap analysis — the ACTIVE track). Per-task scratch plans (if any) under `.claude/plans/`.
- **Install / security:** [`docs/INSTALL.md`](docs/INSTALL.md) · [`bootstrap/README.md`](bootstrap/README.md) · [`SECURITY.md`](SECURITY.md) · [`README.md`](README.md)

## Where we are (2026-07-20)

- **v2.0 roadmap V1..V20: complete.** **H0–H7 hardening gate: landed.** v3 first
  wave shipped (see "v3" below), plus the M6-debt payoff (CLI log analysis wired
  into the shared issue model). All work is committed AND **pushed** —
  `origin/feature/v2.0` is in sync with local `HEAD`; the tree is clean.
- **Operator queue 1 (2026-07-20) COMPLETE:** G2 ✅, G3 ✅ (2026-07-20);
  G4 ✅, G5 ✅, G6 ✅ (2026-07-21) — each via `ship-roadmap-pr` with the
  matching `docs/PLAYBOOKS.md` recipe.
- **Operator queue 2 (2026-07-21, run to the end of the roadmap):** G8 ✅ →
  G9 → proxy retirement (`ai_citations_perplexity`) → G11 → G10 → G7 →
  G13 → G14 → G15.
  **Policy decision (2026-07-20):** the v2.0 "no new AI-engine APIs" lockout is
  reopened for G3 — strictly BYO-key, opt-in, OFF by default.

## How the roadmaps fit (avoid confusion)

- **`PLAN.md`** = the product north star (M0–M9: issue model → recap → export →
  history → GSC → logs → AI → remote sync → future integrations). Direction and
  privacy policy; not a live build queue.
- **`docs/v2_beat_screaming_frog_roadmap.md`** = the executed V1–V20 build that
  delivered most of PLAN.md's milestones plus the GEO moat. Historical now.
- **`docs/v3_roadmap.md`** = the CURRENT execution track: gaps vs Screaming
  Frog / Sitebulb / Ahrefs / GEO tools, ranked, with a must/nice verdict.
- ⚠️ **Naming collision:** PLAN.md's "M8" is *Remote Sync*; v3's "M8" is *JS
  link crawl*. They are unrelated — disambiguate by which doc you're reading.

## Working rules

- Reply in English unless asked otherwise.
- Keep changes small, typed, covered by focused tests. Don't revert unrelated
  edits already in the working tree.
- Before closing non-trivial work: `poetry run python tools/doctor.py --quick`
  → focused tests → full `poetry run python tools/doctor.py`.
- Python 3.12 is the tested baseline. Keep installer/launcher entrypoints aligned
  when startup behaviour changes (AGENTS.md §6).

## Git & release

- **Active branch `feature/v2.0`** (the v2.0 build). `dev` holds shipped v1.1.
- Remote is pinned to GitHub account **`developeter`** via a repo-local credential
  helper. Before pushing, confirm `git config --local user.email` is
  `developeter.apps@gmail.com`.
- **Push runs a pre-push gate** (full `doctor` + quality gates: poetry lock-check,
  dependency-policy, ruff, mypy allowlist, pytest+coverage). It can take several
  minutes — that's the gate, not an auth hang; allow ≥5 min.

## v2.0 status

Goal: crawl whole sites (verified to **100k URLs**; ~1M is a post-gate goal, not
yet a supported scale) with parity-plus vs Screaming Frog / Sitebulb, led by
prioritized issues + evidence, local-first.

- **Shipped:** V1 fetcher · V2 streaming SQLite store · V3 hybrid spider · V4
  render pool · V5 LLM export · V6 custom extraction · V7 GSC+GA4 · V8 crawl diff ·
  V9 link graph · V11 ai.json/llms.txt · V13 log + crawl-budget · V14 Lighthouse +
  Rich Results · V15 tech stack · V16 robots simulator · V17 Semrush.
- **H0–H7 hardening gate — landed.** Lossless payload round-trip; `CrawlRunRef` +
  run-bound repository (SQLite prod / in-memory tests); bounded-memory SQL paging
  with a 100k perf gate; resumable SQLite frontier + unified robots; `AuditProfile`
  (Lightweight/Standard/Deep) gating network cost only; source-first coverage +
  per-module mypy allowlist + dependency-policy gate; evidence taxonomy
  (`docs/RESEARCH_CITATIONS.md`); TLS/SSRF on by default + minisign-signed updater.
  (Detail: the H-plan in `.claude/plans/` + the roadmap.)
- **V19 GUI redesign — Stage A: shipped.** The ~18 flat audit tabs are regrouped
  into a top-level **Recap** + five buckets (**Indexability · Content · Speed ·
  Trust · AI/GEO**) via one shared `tab_buckets` builder reused by the Single Page
  window and the Site Crawl detail dialog (tab widgets/wiring unchanged; recap rows
  navigate to the right bucket + sub-tab). Optional **`[charts]`** (PyQtGraph)
  distribution charts on the Site Crawl results screen, fed by read-only repository
  aggregates, with a pure-Qt text fallback when the extra is absent. Stage B
  (premium UI / QML) is out of scope for v2.0.
- **V10 — shipped.** Per-bot SSR rendering: 19 bot user-agents rendered through
  the V4 pool (now hardened against launch failures), per-bot cells in the Bot
  Matrix SSR column, `access_bot_render` check. Off by default (Crawl Settings),
  needs Playwright + DEEP profile.
- **V20 — shipped.** Topic embeddings (local MiniLM title/body coherence, extra
  **`[embeddings]`**, opt-in checkbox) + brand-mention time-series (Brave +
  Common Crawl reuse, local per-host JSON series, `SILENTFROG_BRAND_MENTIONS_ENABLE`).
  Three checks, emitted only when measured. **Roadmap V1..V20 complete.**
  **Dropped:** V18 (MCP server); V12 (folded into V17).

## v3 — post-v2.0 (gap analysis: `docs/v3_roadmap.md`)

Shipped:
- **Prioritized hints engine (G1):** `hints.py` groups per-URL `AuditIssue`s by
  type into severity-ranked `Hint`s with a prevalence count; the Site Crawl
  recap now reads "Missing meta description — 142 of 900 pages" instead of a
  flat per-URL list. Site-wide "blocked from AI search" (G12) falls out of this
  for free (AI-access checks already flow into `ai_geo.*` issues).
- **JS-rendered link crawl (M8):** opt-in `render_js` unions JS-rendered DOM
  links into `payload.links` so the spider follows SPA/React/Vue routes. Off by
  default; needs Playwright + DEEP.
- **Reopenable past scans:** crawl SQLite stores are now retained (rolling prune,
  10 newest); "View past scans" → **Open scan** reloads the SQL-paged results
  table with full per-page detail. History records `db_path`/`store_run_id`.
- **Multi-URL Dashboard retired:** Site Crawl URL-list mode covers it; its
  GEO-Score-per-URL view moved to a sortable **GEO** column in the results table.
- **Lighthouse fix:** the button silently no-op'd (anonymous PSI quota is
  permanently 429, swallowed at three layers). Failures now surface a dialog
  with the `SILENTFROG_PSI_API_KEY` remedy; the "Not run" hint row always shows.
- **GUI design-token pass:** one QSS template + per-theme tokens (light mode was
  visibly broken); zebra/gridless tables, underline tabs, styled inputs.
- **M6 debt paid (PLAN.md numbering):** CLI log analysis now feeds the shared
  issue model. Still deferred: a GUI log-import window, and unifying the two
  log parsers (`logs/` crawl-budget path vs `log_analysis.py`).
- **Health score + issue trends (G2):** `crawl_trends.py` derives, per site,
  the health-score series and per-issue count chains across stored history
  runs (window 12, top 8 issues, signed deltas); the past-scans dialog grows
  a Trends panel (series chart via the `[charts]` triad with pure-Qt text
  fallback). Reads the JSON history only — no schema change, no new score.

- **AI citation share-of-voice (G3):** `integrations/ai_engines/` samples a
  small prompt set against OpenAI/Perplexity/Gemini via plain REST (no
  SDKs), scores brand mentions / domain citations / lexicon sentiment, and
  keeps a local per-host JSON series. Strictly BYO-key opt-in
  (`SILENTFROG_AI_SOV_ENABLE=1` + keys in Settings), sampled once per host
  per session; results surface as "AI Share of Voice" `ok` rows + a GEO
  checks badge group. (The fabricated `ai_citations_perplexity` proxy was
  retired on 2026-07-21 in favour of the real `sov_perplexity` signal.)

- **Accessibility audit (G4):** vendored axe-core 4.10.3 (MPL-2.0,
  `_vendor/axe.min.js` + license, pinned + sha-recorded) runs in the rendered
  page via the render pool's new `inject_js`/`evaluate_js` seam. Opt-in
  `accessibility_audit` flag + DEEP profile + Playwright; violations become
  `accessibility.*` issues (critical→critical, serious→warning,
  moderate/minor→info) feeding recap/hints, plus an Accessibility tab (Trust
  bucket, both surfaces) and an "Accessibility actions" Excel sheet.

- **Topic map (G5):** the force-directed link graph already shipped in V9;
  G5 adds the content-cluster map. Measured pages now retain their rounded
  MiniLM document vector inside `topic_embeddings` (opt-in flag only);
  `content_clusters.py` clusters via KMeans+PCA (sklearn rides the locked
  `[embeddings]` extra — zero dependency changes); a "Topic map" button opens
  a cluster-colored scatter dialog (click → page detail). Store collection is
  bounded both ways: 2000 vectored pages, 5000 scanned rows.

- **MCP server (G6, the revived V18):** `silentfrog-mcp serve` — a hand-rolled
  stdlib JSON-RPC/stdio MCP server (`mcp_server.py`, zero new deps). Tools:
  `audit_page` (headless single-page audit, STANDARD profile default,
  TLS/SSRF guards inherited, integrations stay env-gated off), `list_crawls`,
  `get_crawl_summary` (history + hints + trend reuse). Claude Desktop config
  example in README §MCP server.

- **Client-ready HTML report (G8):** `exporters/html_report.py` builds one
  self-contained HTML (inline CSS from the light theme tokens, hand-rolled
  SVG charts, @media print, every crawl-derived string escaped): summary,
  top hints, GEO distribution, status/indexability, worst pages, and a
  health trend (labeled lower-is-better) when ≥2 history runs exist.
  "Export HTML report" button; single crawl stream via the new
  `audit_issues.issues_for_results` (the Excel double-stream was not copied).

- **Scheduled crawls + alert digest (G9):** one-shot `silentfrog-cli crawl`
  runs a headless store-backed site crawl, saves it to crawl history (the
  GUI's "View past scans" reopens it), prints a history-diff digest, and with
  `--digest` delivers it via webhook (`SILENTFROG_ALERT_WEBHOOK_URL`) and/or
  stdlib SMTP (`SILENTFROG_SMTP_*`, password keyring-first). Scheduling is
  the OS's job (Task Scheduler/cron — README has examples); no daemon, zero
  new deps. `--out-report` also writes the G8 HTML report.

Next: the nice-to-have tail — G11 → G10 → G7 → G13 → G14 → G15. All
must-haves (M1–M8) are ✅; the fake `ai_citations_perplexity` proxy is
retired.

**Invariants (hold on every change):** §1.5 myth rule (absent not-required signal
→ info, never warning/critical); add-only `CrawlPayload` keys; new
Settings/integrations default OFF; zero new **base** deps — heavy deps go behind
extras (`[stealth] [google] [semrush] [charts]` …); the code-shape baseline never
grows.

## Running & testing

- Gate: `poetry run python tools/doctor.py --quick` · full: drop `--quick`.
- Tests: `poetry run pytest -q` · GUI smoke render:
  `poetry run python tools/smoke_render_tabs.py tmp_smoke_render`.
- Launch: `poetry run silentfrog`.
- **Non-editable install quirk:** `tests/conftest.py` prepends `src/`, so tests
  exercise the working tree — but the *app* runs the copy in
  `.venv/Lib/site-packages/silentfrog`. After editing source **while the GUI is
  open**, re-sync with
  `cp -r src/silentfrog/* .venv/Lib/site-packages/silentfrog/` (a normal
  `pip install --no-deps --upgrade .` rolls back while `silentfrog.exe` is locked).
  With the app closed, a plain pip reinstall works.

## Install / update (summary — full detail in docs/INSTALL.md, bootstrap/README.md, README §2/§6)

Three layers: **bootstrap** one-click installers (`bootstrap/Get-Silentfrog.*`,
attached to GitHub Releases) → **in-app updater** (Help → Check for Updates…;
installs only a **minisign-signed** Release, verified against the pinned key in
`src/silentfrog/update_trust.py`, **fail-closed**; dev clones are routed to
`git pull`) → **source installer** (`install_silentfrog.py`). **Known gap:** the
first-install bootstrap fetches source over HTTPS but is **not yet
signature-verified** (only the in-app updater is) — tracked in `SECURITY.md`.

## Integrations & secrets (all OFF by default; keys in OS keychain / env, never in the repo)

No integration runs on a stock audit.

- **Semrush (V17):** key via Settings → keyring `silentfrog-semrush` (or env
  `SILENTFROG_SEMRUSH_API_KEY`); enrichment needs `SILENTFROG_SEMRUSH_ENABLE=1`
  (daily cap via spinbox / `SILENTFROG_SEMRUSH_MAX_CALLS`).
- **Lighthouse (V14):** the "Run Lighthouse" button is on-demand only — clicking
  is the consent, no enable gate. Optional `SILENTFROG_PSI_API_KEY` lifts the PSI
  rate limit. (The separate background CrUX collection still uses
  `SILENTFROG_PSI_ENABLE`, intentionally.)
- **GSC + GA4 (V7):** `SILENTFROG_GOOGLE_ENABLE=1` + system-browser OAuth (tokens
  in keyring `silentfrog-google`). Rich Results is schema-derived for free; it
  upgrades to Google's verdict only when GSC is connected.
- **AI share of voice (v3 G3):** BYO keys via Settings → AI share of voice
  (BYO keys) → keyring `silentfrog-ai-engines` (or env
  `SILENTFROG_OPENAI_API_KEY` / `SILENTFROG_PERPLEXITY_API_KEY` /
  `SILENTFROG_GEMINI_API_KEY`); sampling needs `SILENTFROG_AI_SOV_ENABLE=1`
  (optional `SILENTFROG_AI_SOV_PROMPTS`, `SILENTFROG_AI_SOV_MAX_PROMPTS`,
  `SILENTFROG_AI_SOV_COMPETITORS`).

Never commit keys, tokens, crawl history, or exports. `.env*`,
`secrets.local.json`, `*.secrets.json` are git-ignored; full policy in `SECURITY.md`.

## Cautions

- Don't add code-shape baseline exceptions or weaken the guards — refactor instead.
- Avoid broad refactors while adding features; keep GUI changes cross-platform
  (macOS sizing especially).
- Integrations must never run automatically; external-API tests use mocks by default.
