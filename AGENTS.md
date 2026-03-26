# Silentfrog Codex Operating Rules

This file is the local execution contract for Codex in this repository.

## 1) Engineering quality

- Reply in English unless the user explicitly asks for another language.
- Keep code simple and explicit.
- Prefer guard clauses over deep nesting.
- Avoid chained `if/else` blocks when a map, helper, or `match` is clearer.
- New code must stay readable by a human maintainer first.
- Keep imports minimal and remove dead code.

## 2) Change workflow (mandatory)

For every non-trivial change:

1. Run quick checks:
   - `poetry run python tools/doctor.py --quick`
2. Run focused tests for touched modules when applicable.
3. Before closing the task, run full checks:
   - `poetry run python tools/doctor.py`

If tests cannot run, report why and what remains unverified.

## 3) Testing policy

- Every bug fix should have a regression test.
- Prefer small unit tests near the changed module.
- Keep integration tests stable; do not rewrite snapshots unless behavior changed intentionally.

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
