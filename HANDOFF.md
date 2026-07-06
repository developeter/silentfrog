# Silentfrog — Handoff

Last updated: 2026-07-06

Fast orientation for the next session. This file stays short on purpose —
durable detail lives in the linked sources, not here.

- **Contract & map:** [`AGENTS.md`](AGENTS.md) (operating rules) · [`CLAUDE.md`](CLAUDE.md) (repo map, key dirs)
- **Roadmap:** [`docs/v2_beat_screaming_frog_roadmap.md`](docs/v2_beat_screaming_frog_roadmap.md) · active per-task plan under `.claude/plans/`
- **Install / security:** [`docs/INSTALL.md`](docs/INSTALL.md) · [`bootstrap/README.md`](bootstrap/README.md) · [`SECURITY.md`](SECURITY.md) · [`README.md`](README.md)

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

Next (ranked in `docs/v3_roadmap.md`): G2 health-score + issue trends · G3
BYO-key AI citation share-of-voice (needs the "no new AI-engine APIs" policy
reopened) · G4 accessibility (axe-core via the render pool) · G8 HTML report ·
G9 scheduled crawls + alert digest.

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

Never commit keys, tokens, crawl history, or exports. `.env*`,
`secrets.local.json`, `*.secrets.json` are git-ignored; full policy in `SECURITY.md`.

## Cautions

- Don't add code-shape baseline exceptions or weaken the guards — refactor instead.
- Avoid broad refactors while adding features; keep GUI changes cross-platform
  (macOS sizing especially).
- Integrations must never run automatically; external-API tests use mocks by default.
