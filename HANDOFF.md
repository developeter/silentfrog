# Silentfrog Handoff

Last updated: 2026-05-18

## Working Rules

- Reply to the user in English unless explicitly asked otherwise.
- Keep changes small, typed, and covered by focused tests.
- Do not revert user changes. The working tree may contain unrelated edits.
- Before closing non-trivial work, run:
  - `poetry run python tools/doctor.py --quick`
  - focused tests for touched modules
  - `poetry run python tools/doctor.py`
- Keep the source installer path aligned when startup/install behavior changes:
  - `install_silentfrog.py`
  - `install_silentfrog.bat`
  - `install_silentfrog.sh`
  - `run_silentfrog.bat`
  - `run_silentfrog.sh`
  - `tools/source_install.py`
- Treat Python 3.12 as the tested baseline unless the compatibility matrix is intentionally expanded.

## Current Git Context

- Main working branch in recent work: `dev`.
- Latest pushed commit at handoff time:
  - `f6681a1 Support Python 3.14 installers and packages`
- The dev branch carries an in-progress install/package hardening series (not yet committed) — see "Install / package overhaul" below.

## Product Direction

Silentfrog is being shaped as a local-first, open-source, action-oriented SEO audit tool.

The product should lead with:

- prioritized issues
- clear evidence
- practical recommendations
- local privacy by default
- optional integrations only after explicit user setup

Avoid turning it into a raw-data clone of Screaming Frog/Ahrefs. Raw data should remain available, but the main value should be action clarity.

## Roadmap State

See `PLAN.md` as the source of truth.

Implemented:

- M0 Product roadmap document.
- M1 Shared audit issue model.
- M2 Recap UX.
- M3 Action workbook export.
- M4 Crawl history and diff, now with visible local History Browser UI.
- M6 Local SEO log analysis.
- M7 AI-assisted SEO/GEO review foundation.
- M8 Remote sync foundation.

Not yet implemented:

- M5 Google Search Console integration.
- M9 Future integrations/API layer.
- Real AI provider calls and UI controls.
- Real Google Drive OAuth/sync UI.

## Install / package overhaul (uncommitted, 2026-05-18)

A series of small mergeable changes hardens the install/uninstall and packaging story across Windows + macOS Intel + macOS Apple Silicon + Python 3.12 / 3.13 / 3.14. Unsigned for now; code signing is a future milestone. See `CHANGELOG.md` under "Unreleased" for the user-facing summary. Highlights:

- Single source of truth for runtime deps: `tools/source_install.py` reads `pyproject.toml` via `tomllib`. No more `RUNTIME_WHEEL_REQUIREMENTS`. Drift impossible by construction.
- Cross-platform uninstaller in `tools/source_uninstall.py` plus `uninstall_silentfrog.{sh,bat,command}` launchers. `--purge` opt-in for local crawl history; never touches `~/nltk_data`.
- `tools/doctor.py` gained `--mode poetry|venv|both`. Workflow `python-compat.yml` runs the new venv mode after each source install.
- macOS first-run: `xattr -dr com.apple.quarantine` silently inside the `.command` scripts; `install_silentfrog.py` auto-runs `Install Certificates.command` when python.org Python is detected.
- Parametric drift test asserts every committed `run_*`, `install_*`, `reinstall_*`, `uninstall_*` launcher equals the corresponding `render_*()` output.
- `pysidedeploy.spec` committed at repo root. `tools/package_app.py` materializes a platform-specific copy inside `build/package/<os>/pysidedeploy.spec` (Nuitka flags include `--nofollow-import-to=pyRdfa,pyMicrodata,rdflib` to work around a 2.7.11 assertion via `extruct`'s RDFa parsers).
- Bundle data files: `--include-data-dir` for `src/silentfrog/assets` and `src/silentfrog/resources`. Without those, the gear/settings icon and stopwords are missing from the `.app`.
- `icon.icns` committed alongside `icon.png` / `icon.ico` to keep the build independent of `sips` / `iconutil`. `tools/package_app.py::ensure_macos_icns` still regenerates it locally if `icon.png` is newer.
- BOM stripped from 9 files under `src/silentfrog/` (e.g. `crawler_utils.py`, `seo_gui.py`, the `models/*.py`) — pyside6-deploy's `dependency_util.py` has a `tree` unbound-local bug that triggers on any `SyntaxError` (BOM counts as one).
- DMG (macOS) via pure `hdiutil` with drag-to-Applications layout; portable ZIP on Windows. Workflow `package-app.yml` publishes a draft GitHub Release on `v*` tag pushes.
- Maintainer-side `docs/packaging_preview.md` documents the local rehearsal flow.

### Cross-platform validation status (2026-05-18)

Verified physically on **macOS Apple Silicon** (the maintainer's machine):

- `poetry run python tools/doctor.py` → 291 passed
- `python install_silentfrog.py` end-user source flow (not re-run after every PR, but the underlying `tests/test_source_install_unit.py` and `tests/test_source_uninstall_unit.py` are green)
- `poetry run python tools/package_app.py --mode standalone` → `build/package/darwin/Silentfrog.app` (~287 MB) + `Silentfrog-1.0.0-macos-arm64.dmg` (~113 MB)
- `hdiutil verify` on the dmg → checksum valid
- `open Silentfrog.app` (after `xattr -dr com.apple.quarantine`) → window launches, `icon.png` and `settings.png` (gear) render from the bundled `silentfrog/assets/`, stopwords resolve from the bundled `silentfrog/resources/`

NOT yet executed physically — to be validated by CI (or by a maintainer with that box):

- Build Nuitka on **Windows** (`Silentfrog.exe`)
- Build Nuitka on **macOS Intel** (`Silentfrog.app` for Intel)
- DMG generation on macOS Intel (path `Silentfrog-<v>-macos-intel.dmg`)
- ZIP generation on Windows (`Silentfrog-<v>-windows-x64.zip`)
- `install_silentfrog.bat` → `.venv\Scripts\silentfrog.exe` real run
- `Silentfrog.lnk` PowerShell-created shortcut on Windows Desktop

The unit tests cover the platform-branching logic (`_arch_label`, `artifact_plan`, `select_icon_for_os`, `installer_paths`, `app_data_dir`, `windows_shortcut_command`, drift across `.bat` launchers, etc.) — they assert the code chooses the right path per OS but do not execute Nuitka or hdiutil on Windows/Intel from a macOS Apple Silicon developer machine.

### Continuation guide — validating on Windows from a fresh chat

When you open a new Claude conversation on the Windows machine, after a `git pull` on `dev`, brief the new instance with the following bullet list. It is self-contained.

1. The Silentfrog repo at `<wherever you cloned it>` has an in-progress install/package overhaul on branch `dev`. It was developed and validated on macOS Apple Silicon. Goal of this session: validate that the source installer and the packaging pipeline also work on Windows.

2. First sanity:
   ```cmd
   poetry install
   poetry run python tools\doctor.py --quick
   poetry run python tools\package_app.py --mode standalone --dry-run
   ```
   The dry-run should print a Nuitka command containing both `--nofollow-import-to=pyRdfa` and `--include-data-dir=...src\silentfrog\assets=silentfrog/assets`.

3. End-user source install path:
   ```cmd
   py install_silentfrog.py
   run_silentfrog.bat
   ```
   The installer should create `.venv\`, write a `Silentfrog.lnk` on the Desktop, and `run_silentfrog.bat` should open the Silentfrog window. Verify the home-screen icon and the gear icon in the Crawl settings dialog both render.

4. `tools/doctor.py --mode venv --skip-tests` after the install should confirm the `.venv` is intact.

5. Uninstall round-trip:
   ```cmd
   uninstall_silentfrog.bat
   ```
   `%LOCALAPPDATA%\Silentfrog\` must remain (local crawl history). Re-run with `--purge` to also wipe it.

6. Packaging:
   ```cmd
   poetry run python tools\package_app.py --mode standalone --keep-deployment-files
   ```
   Expected output:
   - `build\package\windows\Silentfrog\Silentfrog.exe` (the packaged binary)
   - `build\package\windows\Silentfrog-1.0.0-windows-x64.zip`
   Open `Silentfrog.exe` and verify the same icons render.

7. Known sharp edges to watch for on Windows:
   - SmartScreen will warn ("Windows protected your PC") on first launch of the unsigned `Silentfrog.exe`. Click **More info → Run anyway**.
   - If `pyside6-deploy` complains about a missing config file even when one exists in `build\package\windows\pysidedeploy.spec`, the `cwd` of the subprocess may have moved — check `tools/package_app.py::main()` and confirm `cwd=paths.build_dir` (the working dir feeds pyside6-deploy's spec lookup).
   - Nuitka may emit cache prompts on the first run; allow them.

8. If any step fails, gather:
   - the full stderr of the failing command
   - `git rev-parse HEAD` (which commit is being tested)
   - the output of `poetry run python tools\doctor.py --mode both`
   and report back. Then either fix in place (small change), or capture the bug and open a separate task.

Out of scope, do not attempt in this validation session: code signing, notarization, Homebrew tap, winget manifest, Linux artifact uploads.

### Recently merged install/package work

See `CHANGELOG.md` (Unreleased section) for the user-facing list of changes.

## Important Modules

- `src/silentfrog/audit_issues.py`
  - Shared issue model: `AuditIssue`, `IssueSeverity`, `IssueCategory`, `IssueEvidence`.
  - Issue extraction from page payloads and site crawl reports.
- `src/silentfrog/audit_recap.py`
  - Recap widgets for action-oriented summaries.
- `src/silentfrog/exporters/action_workbook.py`
  - Action-first workbook sheets.
- `src/silentfrog/site_crawler.py`
  - Sitemap/URL-list Site Crawl engine.
- `src/silentfrog/site_crawl_types.py`
  - Typed Site Crawl config/results/report models.
- `src/silentfrog/site_crawl_gui.py`
  - Site Crawl window and per-URL detail dialog.
- `src/silentfrog/site_crawl_history_gui.py`
  - Local-only history browser opened by **View past scans**.
- `src/silentfrog/crawl_history.py`
  - Local crawl run persistence, diffing, and deletion.
- `src/silentfrog/log_analysis.py`
  - Local/passive log analysis mapped into `AuditIssue`.
- `src/silentfrog/ai_review.py`
  - Evidence-bound AI review foundation. No real provider calls yet.
- `src/silentfrog/remote_sync.py`
  - Explicit remote sync plan/manifest foundation. No real Google Drive integration yet.
- `src/silentfrog/exporters/site_crawl_excel.py`
  - Consolidated detailed Site Crawl Excel export.
- `tools/source_install.py`
  - Single-source-of-truth runtime requirements via `tomllib`, launcher renderers, macOS cert/quarantine helpers, app-data-dir resolver.
- `tools/source_uninstall.py`
  - Cross-platform uninstaller. `--purge` flag for local crawl history.
- `tools/package_app.py`
  - `pyside6-deploy` orchestration, icon staging (`ensure_macos_icns`), spec materialization, DMG via `hdiutil`, ZIP via `shutil.make_archive`.
- `tools/doctor.py`
  - `--mode poetry|venv|both` runtime checks across the dev env and the installer-produced `.venv`.
- `pysidedeploy.spec`
  - Template consumed by `tools/package_app.py`; per-platform copy materialized into `build/package/<os>/` at build time.
- `docs/INSTALL.md`
  - End-user install / uninstall guide for the packaged path (DMG / ZIP) and the source-installer path on macOS and Windows. Linked from `README.md` sections 2 and 3.
- `docs/packaging_preview.md`
  - Maintainer-side rehearsal flow for local builds before each release.

## Site Crawl State

Site Crawl currently supports:

- base URL with automatic sitemap discovery
- sitemap URL
- sitemap index URL
- pasted URL list
- include prefixes
- exclude patterns
- URL cap, default `500`
- gentle crawl by default
- local history saving after completed crawls
- local history browser via **View past scans**
- detailed Site Crawl Excel export with consolidated per-page detail sheets
- cached per-page detail dialogs
- image analysis from the per-page detail dialog

Site Crawl v1 intentionally does not recursively follow all links.

## Local History Browser

The visible local history UX is now implemented.

Entry points:

- Site Crawl setup screen: **View past scans**
- Site Crawl results screen: **View past scans**

Current behavior:

- lists saved runs by site/date
- shows summary and issue counts
- compares selected run to the previous local run for the same site
- exports selected run as JSON
- deletes selected local run

Storage path logic lives in `crawl_history_dir()`.
On Windows this is typically:

```text
%LOCALAPPDATA%\Silentfrog\crawl_history
```

## Privacy And Secrets

Sensitive files must stay local.

Tracked example:

- `secrets.example.json`

Ignored real secrets:

- `.env`
- `.env.*`
- `secrets.local.json`
- `*.secrets.json`

Do not commit API keys, OAuth tokens, crawl history with private data, imported logs, or exported reports.

## Verification Snapshot

Recent successful verification after the local history browser:

- Focused tests:
  - `poetry run pytest -q tests\test_crawl_history.py tests\test_site_crawl_history_gui.py tests\test_site_crawl_gui.py`
  - Result: `19 passed`
- Full doctor:
  - `poetry run python tools\doctor.py`
  - Result: `223 passed`
- Pre-push full doctor also passed:
  - Result: `223 passed`

## Recommended Next Steps

1. Review and commit the install/package overhaul series listed above. Suggested commit grouping:
   - `tools/source_install.py` + `tests/test_source_install_unit.py` + repo-root launcher rerenders (PR 1-5)
   - `tools/source_uninstall.py` + `tests/test_source_uninstall_unit.py` + `uninstall_silentfrog.*` (PR 3)
   - `tools/doctor.py` + `tests/test_doctor_unit.py` + workflow venv-mode step (PR 4)
   - BOM cleanup under `src/silentfrog/` (separate, easy to review)
   - `pysidedeploy.spec` + `tools/package_app.py` + `icon.icns` + `tests/test_package_app_unit.py` (PR 6-7)
   - `docs/packaging_preview.md` + `README.md` Section 2 + `.gitignore` (PR 8)

2. If continuing roadmap work, the next major product milestone is likely M5:

- Google Search Console URL Inspection
- indexing/page state
- crawl stats
- local-only OAuth credentials
- mocked tests by default
- mapped findings into `AuditIssue`

3. Before implementing real GSC, add a typed foundation first:

- `gsc_integration.py` or similar
- local credential config loader
- protocol/client seam
- typed URL inspection/indexing/crawl-stats models
- issue-model mapping
- mocked tests

4. Keep remote sync and AI provider calls as later slices. The foundations exist, but there is no user-facing real integration yet.

## Caution Points

- Do not add new code-shape baseline exceptions.
- Do not weaken code-shape guard thresholds.
- Avoid broad refactors while adding integrations.
- Keep GUI changes cross-platform, especially macOS sizing.
- Do not make network integrations run automatically.
- For any external API integration, tests must use mocks by default.
