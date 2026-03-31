# Silentfrog Codex Operating Rules

This file is the local execution contract for Codex in this repository.

## 1) Engineering quality

- Reply in English unless the user explicitly asks for another language.
- Keep code simple and explicit.
- Prefer guard clauses over deep nesting.
- Avoid chained `if/else` blocks when a map, helper, or `match` is clearer.
- New code must stay readable by a human maintainer first.
- Keep imports minimal and remove dead code.
- Target a maximum nesting depth of `2` in new code. If you need more, extract helpers first.
- Avoid `if/elif` ladders for string dispatch. Prefer constants, maps, or typed strategy helpers.
- Keep parsing, derivation, orchestration, and UI rendering in separate functions/modules.
- Avoid boolean-flag soup in function signatures. If behavior splits, create a named helper or typed config.
- Prefer typed dataclasses/models over loose dict passing when data crosses module boundaries.
- Comments must explain intent or tradeoffs, not restate the code.
- Do not add a new baseline exception for code-shape violations unless refactoring first has been considered and rejected for a documented reason.

## 2) Change workflow (mandatory)

For every non-trivial change:

1. Run quick checks:
   - `poetry run python tools/doctor.py --quick`
2. Run focused tests for touched modules when applicable.
3. Before closing the task, run full checks:
   - `poetry run python tools/doctor.py`

If tests cannot run, report why and what remains unverified.
If the code-shape guard fails, refactor the touched code instead of weakening the rule or silently growing the baseline.
Before closing a non-trivial code task, run the review questions in `docs/code_review_checklist.md`.

## 3) Testing policy

- Every bug fix should have a regression test.
- Prefer small unit tests near the changed module.
- Keep integration tests stable; do not rewrite snapshots unless behavior changed intentionally.
- For GUI work, prefer user-path tests over implementation-only tests when behavior depends on clicks, sorting, tooltips, or visible layout.

## 4) UI and UX policy

- Keep styling/theme behavior centralized (use shared theme helpers).
- Avoid ad-hoc per-widget patches unless strictly required.
- Cross-platform behavior (Windows/macOS) must be considered in every GUI change.

## 5) Safety policy

- Do not use destructive git commands (`reset --hard`, checkout discard).
- Never revert user changes unless explicitly requested.
- Use UTF-8 safe file editing.

## 6) Install and launcher policy

- The supported end-user install flow is the local source installer:
  - `install_silentfrog.py`
  - `install_silentfrog.bat`
  - `install_silentfrog.sh`
- End-user installation should target a local `.venv` with `pip install .`, not Poetry.
- Poetry is for development workflow only.
- Keep these entrypoints aligned whenever startup logic changes:
  - `pyproject.toml` script entrypoint
  - `src/silentfrog/__main__.py`
  - `run_silentfrog.bat`
  - `run_silentfrog.sh`
  - `tools/source_install.py`
- Keep the installer best-effort for Desktop launchers:
  - Windows: `Silentfrog.lnk`
  - macOS: `Silentfrog.command`
- If install behavior changes, update `README.md` in the same task.
- Treat Python 3.12 as the tested baseline unless the dependency matrix is intentionally expanded.
