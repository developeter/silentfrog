# Silentfrog — Claude Code project memory

## What this repo is

Silentfrog is a Python + Qt desktop SEO/GEO auditor. v1.1 shipped the
GEO moat (Core Web Vitals, CrUX field data, Princeton GEO methods, AI
citation tracking, the 19-bot Bot Matrix heatmap, watch mode, the
GEO-checks badge row). v2.0 (in flight) targets ~1M-URL whole-site
crawling, richer audit data, and parity-plus versus Screaming Frog /
Sitebulb while staying the best open-source alternative to the paid
tools.

**Reply in English.**

## Where the rules live

- `AGENTS.md` (repo root) — the operating contract. Read it first.
- `docs/code_review_checklist.md` — run before closing any non-trivial
  task.
- `.claude/plans/` — active per-task plans (ephemeral; not committed).
- `docs/v2_beat_screaming_frog_roadmap.md` — the durable v2.0 master
  roadmap (V1..V20). Source of truth for milestone scope + ordering.

## Key directories

- `src/silentfrog/` — runtime modules
- `src/silentfrog/models/` — Qt table models
- `src/silentfrog/exporters/` — Excel exporters (+ LLM export, V5)
- `src/silentfrog/fetchers/` — fetcher strategy (V1)
- `src/silentfrog/crawl_store.py` — streaming SQLite audit store (V2)
- `tests/` — unit + GUI smoke tests via pytest-qt
- `tools/` — `doctor.py`, `quality_gates.py`, `code_shape_guard.py`,
  `smoke_render_tabs.py`

## How to run things

- Quick gate: `poetry run python tools/doctor.py --quick`
- Full gate: `poetry run python tools/doctor.py`
- Tests only: `poetry run pytest -q`
- Re-install editable after source edits:
  `./.venv/Scripts/python.exe -m pip install --no-deps --upgrade .`
- Smoke-render GUI tabs to PNG (no need to open the app):
  `poetry run python tools/smoke_render_tabs.py tmp_smoke_render`

## CLI surface

- `silentfrog` — GUI entry point
- `silentfrog-cli aggregate <sitemap_url>` — sitemap-level GEO report
- `silentfrog-cli watch <urls>` — watch mode with regression alerts
- `silentfrog-cli export --format llm <url|crawl.db>` — LLM-friendly
  export (V5)

## Supply chain rules (§4.5)

- Never install a PyPI dep less than 48 hours old. Verify via the PyPI
  JSON endpoint (`https://pypi.org/pypi/<pkg>/json`) before adding.
- Commit `poetry.lock` alongside every dependency bump.
- Heavy / risky deps go behind optional extras (`silentfrog[stealth]`,
  `[google]`, `[semrush]`, `[mcp]`, `[charts]`, `[embeddings]`). The
  install base needs zero new deps.

## Commit policy

- A PreToolUse hook denies bare `git commit`. Use the `caveman-commit`
  skill or supply `-m "..."`, `-F file`, or `--amend`. Never bypass by
  re-running the same bare command.
- The user's verbatim commit message always wins; the skill only drafts
  when the user hasn't supplied one.

## Roadmap automation

- Use `ship-roadmap-pr` when starting or continuing a numbered roadmap PR.
- The main session orchestrates; do not create an additional orchestrator.
- Use `lean-adversarial-reviewer` only for the high-risk boundaries listed in
  `AGENTS.md`. It is read-only, Sonnet, probe-limited, and does not rerun the
  full suite.
- Keep `caveman-review`/`caveman-commit` for concise reporting and messages;
  they do not replace behavioral verification.

## Code shape (enforced by tools/code_shape_guard.py)

- Max nesting depth 2; guard clauses over nesting.
- No `if/elif` ladders for string dispatch — use constants or maps.
- 80-line per-function cap. New code must NOT grow
  `tools/code_shape_baseline.json` — refactor instead.
- Comments explain intent or tradeoffs, never restate the code.
- Prefer typed frozen dataclasses over loose dicts when data crosses
  module boundaries.
