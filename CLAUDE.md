# Silentfrog — Claude Code project memory

> If you are a new agent picking this up: read this file, then `AGENTS.md`
> (the operating contract), then `HANDOFF.md` (current state). This file is
> the durable map + the hard-won lessons that aren't obvious from the code.

## What this repo is

Silentfrog is a Python + Qt (PySide6/qtpy) desktop SEO/GEO auditor — a
local-first, open-source alternative to Screaming Frog / Sitebulb with a GEO
(generative-engine optimization) moat no other tool bundles: a 19-bot access
matrix with per-bot SSR rendering, Princeton GEO methods, llms.txt/ai.json
parsing, Core Web Vitals (lab + CrUX field), local topic embeddings, and
brand-mention tracking. Three audit surfaces: **single-page**, **Site Crawl**
(whole-site, verified to ~100k URLs), and per-page detail.

**Reply in English.** (AGENTS.md rule; the user has corrected this repeatedly.)

## Status (2026-07-06)

- **v2.0 roadmap V1..V20: complete.** Full milestone history in
  `docs/v2_beat_screaming_frog_roadmap.md`; shipped list in `HANDOFF.md`.
- **v3 gap analysis: `docs/v3_roadmap.md` — COMPLETE (2026-07-30).** Every
  G-item (G1–G15) is shipped, retired, or delivered via another (G12 via
  G1; V18 revived as G6); the fake `ai_citations_perplexity` proxy is
  retired. Full shipped list + dates in `HANDOFF.md`.
- **Remaining pools if work resumes:** unnumbered nice-to-haves (WARC
  export · crawl segments · sitemap generation), PLAN.md foundations
  (M5 GSC full deliverable · M6 GUI log window + parser unification ·
  M8 remote-sync OAuth/UI · M9 future integrations), V19 Stage B (QML),
  ~1M-URL scale (100k verified), Settings UI for the G7 provider keys.

## Where the rules live

- `AGENTS.md` (repo root) — the operating contract. Read it first.
- **`docs/PLAYBOOKS.md` — mechanical recipes. Before adding an AI Visibility
  check, a CrawlPayload key, an opt-in feature, a dependency, an audit issue,
  or touching GUI styling: open the matching playbook and follow it LITERALLY.
  Every step exists because a guard test fails without it. It also has the
  risk-classification table (which diffs need adversarial review) and the
  gate-failure → remedy table. When intuition and playbook disagree, the
  playbook wins.**
- `docs/code_review_checklist.md` — run before closing any non-trivial task.
- `docs/v2_beat_screaming_frog_roadmap.md` — the v2.0 master roadmap (V1..V20).
- `docs/v3_roadmap.md` — the post-v2.0 gap analysis + milestone ordering.
- `.claude/plans/` — active per-task plans (ephemeral; not committed).

## Key directories

- `src/silentfrog/` — runtime modules
- `src/silentfrog/models/` — Qt table models (e.g. `bot_matrix.py`)
- `src/silentfrog/exporters/` — Excel + LLM export (V5)
- `src/silentfrog/fetchers/` — fetcher strategy (V1)
- `src/silentfrog/integrations/` — google (GSC/GA4/Lighthouse/CrUX/Rich), semrush
- `src/silentfrog/embeddings/`, `brand_mentions/` — V20 (optional extra)
- `src/silentfrog/link_graph/`, `logs/` — link graph, server-log analysis
- `src/silentfrog/crawl_store.py` — streaming SQLite audit store (V2)
- `tests/` — unit + GUI smoke tests via pytest-qt
- `tools/` — `doctor.py`, `quality_gates.py`, `code_shape_guard.py`,
  `smoke_render_tabs.py`

## How to run things

- Quick gate: `poetry run python tools/doctor.py --quick`
- Full gate (7 gates: lock-check, dep-policy, ruff, format, mypy allowlist,
  pytest+coverage, diff-cover): `poetry run python tools/doctor.py`
- Tests only: `poetry run pytest -q`
- Launch GUI: `poetry run silentfrog`
- Smoke-render GUI tabs to PNG (no display needed, good for visual review):
  `poetry run python tools/smoke_render_tabs.py tmp_smoke_render`

## CLI surface

- `silentfrog` — GUI entry point
- `silentfrog-cli aggregate <sitemap_url>` — sitemap-level GEO report
- `silentfrog-cli watch <urls>` — watch mode with regression alerts
- `silentfrog-cli export --format llm <url|crawl.db>` — LLM-friendly export (V5)
- `silentfrog-mcp serve` — local MCP server over stdio (G6): `audit_page`,
  `list_crawls`, `get_crawl_summary` tools for AI clients

## Invariants (hold on EVERY change — these are load-bearing)

- **§1.5 myth rule:** an absent not-required signal → `info`, NEVER
  `warning`/`critical`. Absence is informational, never a penalty.
- **Add-only `CrawlPayload` keys.** New keys must survive the H0 lossless
  `to_mapping`/`from_raw` round-trip, and old blobs must load with the field's
  default (`_extra_group` returns `{}`). A guard test pins `_decode_fields`
  keys == dataclass fields == `to_mapping` keys — a new field left unread
  fails it.
- **New features/integrations default OFF.** Every heavy or network feature is
  opt-in via a `CrawlOptions` flag + Settings checkbox (or an env enable knob).
  A stock audit must make zero extra network calls and load zero heavy models.
- **Zero new base deps.** `tools/dependency_policy.py` freezes the base set;
  heavy deps go behind extras (`[stealth] [google] [semrush] [charts]
  [embeddings] [geo-render]`). Verify a new dep is ≥48h old on PyPI, pin it,
  commit `poetry.lock`.
- **Code shape** (`tools/code_shape_guard.py`): max nesting 2, no `if/elif`
  string dispatch, 80-line function cap, ≤2 bool args, baseline never grows —
  refactor instead.
- **Integrations never run automatically**; external-API tests use mocks.
  Never commit keys/tokens/crawl history/exports.

## Working the roadmap

- Use `ship-roadmap-pr` for one numbered PR at a time; the main session
  orchestrates — do NOT spawn a second orchestrator.
- `lean-adversarial-reviewer` only for high-risk boundaries (persistence/
  schema, concurrency/cancellation, networking/TLS/SSRF, updater/installer,
  data loss, scoring, large-scale memory, mutable GUI identity). It is
  read-only, Sonnet, probe-limited; it does not rerun the full suite.
- `caveman-commit`/`caveman-review` for concise messages/reports.

## Hard-won lessons (traps that cost time — heed them)

- **The reviewer often truncates.** `lean-adversarial-reviewer` frequently
  hits its turn budget mid-probe and stops before printing findings. If the
  result isn't in `SEV file:symbol — …` / `No verified blockers.` form,
  resume it via SendMessage asking for the report — it finishes reliably.
- **The pre-push hook runs the full doctor** (several minutes) — that's the
  gate, not an auth hang. Allow ≥5 min; a 2-min Bash timeout will look stuck.
- **Non-editable install quirk:** `tests/conftest.py` prepends `src/`, so
  tests exercise the working tree, but the *app* runs the copy in
  `.venv/Lib/site-packages/silentfrog`. After editing source while the GUI is
  open, re-sync with `cp -r src/silentfrog/* .venv/.../silentfrog/` (a plain
  pip reinstall rolls back while `silentfrog.exe` is locked). App closed → a
  normal reinstall works.
- **A plain `poetry install` breaks the canonical layout**: it reinstalls the
  root project EDITABLE (a `silentfrog.pth` appears, appending `src` at the
  TAIL of sys.path) and, combined with a stale copied-in site-packages
  `silentfrog/` dir, made tests import the stale copy — full doctor failed
  2/7 gates machine-wide (2026-07-30). Recover with `pip uninstall -y
  silentfrog`, delete any leftover `site-packages/silentfrog/` dir, then
  `pip install --no-deps .`. `tests/conftest.py` now forces `src` to
  `sys.path[0]` so tests survive a stray editable install; prefer
  `poetry install --no-root` + `pip install --no-deps .` going forward.
- **Git commits:** a PreToolUse hook denies a bare `git commit`. Supply
  `-m`/`-F`/`--amend`. For multi-line messages on Windows, write the message
  to a scratch file and use `git commit -F` — PowerShell here-strings into
  `git` are fragile and have failed silently mid-session.
- **CRLF warnings on commit are harmless** (the repo is LF; Git converts).
- **A long-lived resource on a worker thread must guard its construction.**
  The V4 `RenderPool` originally let a failed browser launch kill the worker
  thread, hanging every queued render forever. Any pool/thread that other code
  awaits must resolve pending work with an error on construction failure, not
  die. (Same lesson bit the V20 embedder — guard the model *constructor*, not
  just the import: the download happens on first use.)
- **The repo lives in the NESTED `silentfrog/` subdir**, not the outer
  workspace. `git`, `pyproject.toml`, `tests/` are all under `silentfrog/`.
- **Push identity:** the remote is pinned to the `developeter` GitHub account
  via a repo-LOCAL credential helper. Before pushing, confirm
  `git config --local user.email` is `developeter.apps@gmail.com` — never rely
  on a global identity.

## Comment policy

Comments explain intent or tradeoffs, never restate the code. Prefer typed
frozen dataclasses over loose dicts when data crosses module boundaries. Keep
parsing / derivation / orchestration / UI rendering in separate functions.
