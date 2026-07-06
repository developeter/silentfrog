# Silentfrog Playbooks — mechanical recipes for common changes

> Audience: any agent or contributor, regardless of capability. Each playbook
> is the EXACT sequence of touches a change needs. Follow it literally — every
> step exists because a guard test or invariant fails without it. When a
> playbook and your intuition disagree, the playbook wins. All recipes were
> extracted from real shipped diffs (V10, V20, v3 G1/M8), not theory.

## P0 — Decision rules when uncertain

1. Make the smallest change that satisfies the acceptance criteria. No bonus
   refactors, no future-proofing, no compatibility shims.
2. If a guard/gate fails, fix YOUR code. Never edit
   `tools/code_shape_baseline.json`, never weaken a guard, never add `noqa`
   without a stated reason.
3. New behavior defaults OFF. A stock audit must make zero extra network
   calls and load zero heavy models.
4. Absence of a not-required signal → `info`, never `warning`/`critical`
   (§1.5). Measured-but-bad → `warning`/`critical` is fine.
5. Don't add a dependency unless the acceptance criteria require it (then P4).
6. If you cannot verify a claim, say "unverified" in your report — never
   claim green gates you didn't run.
7. Prefer extending an existing test over adding a new file; a regression
   test must FAIL when the defect it covers is reintroduced.

## P1 — Add a new AI Visibility check (key `<area>_<slug>`)

Five touches, four files. Missing any of 2-5 fails the H6 guard suite.

1. **Builder** — a function returning `AiVisibilityCheck(key="<key>", ...)`.
   Opt-in features return `None` (or `[]`) when unmeasured so stock audits
   stay clean (pattern: `bot_render.build_bot_render_check`); always-on
   checks return an `info` row when unmeasured (pattern:
   `render_diff.build_render_diff_check`).
2. **Emit** it in `ai_visibility.build_ai_visibility_checks` — the single
   aggregation seam (evidence stamping happens there; do not stamp yourself).
3. **Tooltip** — entry in `_AI_VISIBILITY_CHECK_TOOLTIPS` (same file).
4. **Classify** — entry in `research_evidence.CHECK_EVIDENCE`. Thresholds you
   invented = `(EVIDENCE_HEURISTIC, ())`. Citing an external claim requires a
   source id that exists in BOTH `EVIDENCE_SOURCES` and
   `docs/RESEARCH_CITATIONS.md` (a lockstep test pins them).
5. **Fixture** — extend `comprehensive_audit_raw()` in
   `tests/test_research_evidence_unit.py` with a measured payload for your
   key so the guards exercise it.

Copy rules: never put an effect size (`+40%`, `3x`, `up to N%`) in details/
recommendation/tooltip unless the check is `EVIDENCE_RESEARCH` with a research
source — a regex guard scans for this.

Verify: `poetry run pytest tests/test_research_evidence_unit.py tests/test_ai_visibility_unit.py -q`

## P2 — Add a new CrawlPayload key

Three touches in `crawl_types.py`, all mandatory (a field-parity guard pins
them to each other):

1. Dataclass field with a default (`dict` groups: `field(default_factory=dict)`).
2. `_decode_fields`: `"<key>": _extra_group(data, "<key>")` (tolerates absence
   → old blobs load with `{}`; this is what "add-only" means).
3. `to_mapping`: `"<key>": dict(self.<key>)`.

Values must be JSON-native (no tuples/sets — the store round-trips through
zlib+JSON and a tuple reloads as a list, breaking equality). Producer side:
build the dict in `seo_crawler._analyse`'s `raw_payload`.

Verify: `poetry run pytest tests/test_crawl_types_unit.py -q`

## P3 — Add a new opt-in crawl feature (flag + Settings)

1. `crawl_options.CrawlOptions`: field `<flag>: bool = False` + entry in
   `default()`.
2. `from_ui`: parameter as `<flag>: bool | None = None`, assign
   `bool(<flag>)`. **`bool | None`, not `bool`** — a third plain-bool
   parameter trips the code-shape `bool_args` guard (precedent:
   `use_stealth`, `tech_stack_detection`).
3. Collector in `seo_crawler`, gated FIRST on the flag, then by cost class
   (H4):
   - renders a page → also require `policy.render` (DEEP only)
   - extra HTTP/integration → also require `policy.run_integrations`
   - heavy local compute (model inference) → flag only, but run via
     `await asyncio.to_thread(...)` so the crawl loop stays responsive
   - cheap local parse → always allowed
4. `settings_dialog.py`: checkbox in `_build_geo_group` (disable + explain in
   tooltip when the optional extra is missing — pattern:
   `_playwright_available()` / `_embeddings_available()`), initialize in
   `_initialize_options`, collect in `options()` as
   `bool(chk.isEnabled() and chk.isChecked())`.
5. Test default-off in `tests/test_crawl_options.py` (three asserts: default(),
   from_ui() bare, from_ui(flag=True)).

## P4 — Add an optional dependency (new extra)

1. Age-check on PyPI (≥48h since upload, supply-chain rule):
   `Invoke-RestMethod https://pypi.org/pypi/<pkg>/json` → compare
   `upload_time_iso_8601` of the latest release.
2. Pin `>=X,<Y` under `[project.optional-dependencies]` in `pyproject.toml`
   with a comment explaining the extra; run `poetry lock`; commit
   `poetry.lock` in the same commit.
3. Import lazily INSIDE a function, wrapped in try/except — and wrap the
   **constructor/first-use too**, not just the import (model downloads and
   runtime setup fail on offline machines; the V20 embedder bug was exactly
   this). Degrade to unmeasured, never raise.
4. Never add to base `[project.dependencies]` — `tools/dependency_policy.py`
   freezes that set and will fail the gate.

## P5 — Add a new audit issue (Site Crawl recap / hints)

Emit an `AuditIssue` from the right `_*_issues` builder in `audit_issues.py`
with `issue_id="<category>.<slug>"`. That's all: `hints.build_hints` groups by
`issue_id` automatically, so the recap shows "your issue — N pages" ranked by
severity. §1.5 applies to severity choice. AI Visibility checks with
warning/critical status become `ai_geo.<key>` issues automatically — don't
duplicate them.

## P6 — Change GUI styling

All colors/spacing live in `theme.py`: two token dicts (`_DARK_TOKENS`,
`_LIGHT_TOKENS`) + one `_QSS_TEMPLATE` (string.Template — `$name`, because QSS
braces break str.format). Edit the template once; both themes inherit. Never
add inline `setStyleSheet` hex in widgets. Status tints come from
`status_brushes()` — soft tints, glyphs/text carry meaning.

Verify visually, not just by tests:
`poetry run python tools/smoke_render_tabs.py tmp_smoke_render` then view the
PNGs. Consider both themes — the template makes dark/light parity automatic,
but layout code can still differ.

## P7 — Ship a roadmap PR (condensed loop)

1. Read `CLAUDE.md`, `AGENTS.md`, the roadmap item, `git status`, the
   relevant code. State scope + non-goals.
2. Implement the smallest coherent change (P1-P6 as applicable).
3. Focused tests + `ruff check` + `ruff format --check` +
   `tools/code_shape_guard.py` on touched files.
4. Classify risk with the table below. HIGH → `lean-adversarial-reviewer`
   once, with the raw diff + acceptance criteria. If its reply is not in
   `SEV ...` / `No verified blockers.` form, it ran out of turns — resume it
   (SendMessage) asking for the final report; it completes reliably.
5. Fix only reproducible in-scope blockers; max two reviewer passes, then
   report instead of looping.
6. Full doctor ONCE after stabilizing: `poetry run python tools/doctor.py`
   (~5-6 min; don't re-run unless a failed gate forced a code change).
7. `docs/code_review_checklist.md`, then a Caveman report: outcome, files,
   verification, later-scope items, commit readiness.

### Risk classification (HIGH → adversarial review; else NORMAL)

| Diff touches | Risk |
|---|---|
| `crawl_store*`, `crawl_run_repository`, `frontier`, `crawl_history` (schema/persistence) | HIGH |
| `site_crawler` worker loop, `render_pool`, `workers.py`, cancellation/threading | HIGH |
| `transport`, `ssrf`, `http_client`, `fetchers/`, TLS, any new outbound HTTP | HIGH |
| `updater`, `update_trust`, `bootstrap/`, installers | HIGH |
| `_geo_score`, `build_ai_visibility_summary`, issue severities (scoring) | HIGH |
| anything that writes/deletes user files or DBs | HIGH |
| pure parsers, check builders, Qt models/tabs display, theme, docs, tests | NORMAL |

### Gate failure → remedy

| Failure | Remedy |
|---|---|
| `ruff check` | fix the lint; `--fix` for mechanical ones; no blanket `noqa` |
| `ruff format --check` | `poetry run ruff format src/ tests/ tools/ .claude/hooks/`, rerun |
| code-shape `bool_args N > 2` | make the new flag `bool \| None = None` in the signature (P3.2) |
| code-shape nesting/length | extract helpers; NEVER touch the baseline file |
| mypy (allowlist) | fix types in the listed module; don't remove it from the allowlist |
| diff-cover < 85% | add focused tests for the uncovered lines the report names |
| H6 guard (`test_every_emittable_check_is_classified` etc.) | you skipped a P1 step — tooltip, CHECK_EVIDENCE, or fixture |
| pytest fails in a test you didn't write | your change broke a contract — fix the code; edit the test only if the behavior change IS the task |
| pre-commit denies `git commit` | you ran it bare — supply `-m`, or write the message to a scratch file and `git commit -F <file>` (most reliable on Windows; PowerShell here-strings into git have failed silently) |
| push looks hung | it's the pre-push doctor (~5 min); use a ≥5-minute timeout |

## Environment traps (Windows dev box)

- The git repo + sources are in the NESTED `silentfrog/` subdir of the
  workspace, not the workspace root.
- Tests exercise `src/` (conftest prepends it) but the launched app runs
  `.venv/Lib/site-packages/silentfrog`. GUI open → sync with
  `cp -r src/silentfrog/* .venv/Lib/site-packages/silentfrog/`; GUI closed →
  `pip install --no-deps --upgrade .` works.
- Before pushing: `git config --local user.email` must be
  `developeter.apps@gmail.com` (repo-local `developeter` credential helper).
- CRLF warnings on commit are noise (repo is LF; Git converts).
