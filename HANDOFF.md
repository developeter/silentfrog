# Silentfrog Handoff

Last updated: 2026-05-21

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
- Latest pushed commit at handoff time: `7351838 Fix three small GUI regressions on theme + tabs + logo` (plus the bootstrap-README Sequoia note in the same series).
- Working tree on the maintainer's Windows machine is clean.
- The bootstrap publish workflow (`.github/workflows/release-bootstrap.yml`) is wired up but has not yet been triggered — no `v*` tag exists yet, so no GitHub Release has the bootstrap files attached.

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

## Install / update story (current)

End-user installs go through the bootstrap scripts in `bootstrap/`,
which detect / install Python and run the source installer. Updates
happen from inside the app via **Help → Check for Updates…**, which
downloads the latest commit on `dev` and swaps source files in place.
The Nuitka-based packaged path has been archived under
`experimental/packaging/`; see that directory's `README.md` for why.

Three install / update layers, by audience:

1. **Bootstrap (colleagues, fresh machines)**
   - `bootstrap/Get-Silentfrog.{ps1,bat,command}` — published as draft
     Release assets by `.github/workflows/release-bootstrap.yml` on
     every `v*` tag push.
   - Detect Python 3.12/3.13/3.14 → silent-install python.org 3.12.7
     if missing → fetch latest commit on `dev` → extract to
     `%LOCALAPPDATA%\Silentfrog\app` (Win) or `~/Silentfrog/app`
     (macOS) → run `install_silentfrog.py --revision <sha>`.
   - Logs to platform-appropriate location, see `bootstrap/README.md`.

2. **In-app updater (everyone after install)**
   - `Help → Check for Updates…` (added by `src/silentfrog/gui.py`).
   - Dialog defined in `src/silentfrog/update_gui.py`.
   - Domain logic in `src/silentfrog/updater.py` (typed dataclasses,
     `aiohttp` for the GitHub commits API, no Qt imports).
   - Apply button launches `tools/update_silentfrog.py --revision <sha>`
     via `QProcess`, then restarts the app via
     `QProcess.startDetached(sys.executable, sys.argv)`.
   - Dev clones (`.git` directory present) are detected and routed to
     a "use `git pull` instead" message — the in-app updater never
     touches a working tree under git control.

3. **Source installer (developers + bootstrap callee)**
   - `install_silentfrog.py` → `tools/source_install.py::main()`.
   - New `--revision <sha>` flag persists `.silentfrog_revision` so
     the in-app updater knows what's installed.
   - Behavior unchanged for dev clones that omit the flag.

### Smoke-test the bootstrap path

Bootstrap scripts are not unit-tested. When you change them, smoke-test
on a clean target.

#### Windows (validated 2026-05-19 on the maintainer's machine)

1. On a Windows machine **without** Python installed, download
   `Get-Silentfrog.bat` and `Get-Silentfrog.ps1` from the latest
   GitHub Release into the same folder (Downloads is fine).
2. Double-click `Get-Silentfrog.bat`. A console window opens.
3. Expect a single UAC prompt for the silent Python install.
4. After ~1 minute total, expect a Silentfrog shortcut on the Desktop
   and the app to be installed at `%LOCALAPPDATA%\Silentfrog\app\`.
5. Open `%LOCALAPPDATA%\Silentfrog\bootstrap.log` — should show
   `[update] Recorded <sha> in .silentfrog_revision` near the end and
   no `ERROR` lines.
6. Double-click the Desktop shortcut → app launches.
7. **Help → Check for Updates…** → "You're on the latest version
   (<sha>)" (because the bootstrap just pinned the latest sha).
8. **Help → About Silentfrog** → version, sha, "User install", repo
   link.

#### macOS Apple Silicon

1. On an Apple Silicon Mac (M1/M2/M3/...) **without** Python
   3.12/3.13/3.14 installed, download `Get-Silentfrog.command`.
2. Right-click → **Open** the first time (Gatekeeper blocks a
   double-click on unsigned `.command` files).
3. Terminal opens with progress lines.
4. Expect a password prompt for `sudo installer` (the python.org pkg
   is universal2, so the same `.pkg` covers Apple Silicon and Intel).
5. After ~1 minute, expect `~/Silentfrog/Silentfrog.command` (the
   Desktop launcher created by `install_silentfrog.py`).
6. Open `~/Library/Logs/Silentfrog-bootstrap.log` — same checks as
   above.
7. Same Help-menu checks as on Windows.

#### macOS Intel

Identical to Apple Silicon. The python.org `python-3.12.7-macos11.pkg`
is universal2 (one binary for both architectures), so the script
detects `uname -m` only for logging — the same `.pkg` URL is used in
both branches and `sudo installer` produces a Python that runs natively
on Intel. The Silentfrog source is pure Python plus PySide6 wheels, and
PySide6 has dedicated Intel and Apple Silicon wheels on PyPI; pip
selects the right one from the running Python's architecture.

If the Intel test reveals an issue not present on Apple Silicon, the
likely culprits are: (a) a runtime dependency wheel that lacks an
`x86_64` mac build (the source installer's wheel-only preflight will
say so), or (b) macOS version compatibility (PySide6 6.11 requires
macOS 11+).

#### macOS / Windows with Python already installed

Same flow on either OS: the bootstrap detects an existing Python via
`py --list` (Windows) or `python3.NN --version` (macOS), skips the
silent installer entirely, and goes straight to the source download.
Expect the install to complete in 15-30 seconds total.

### Smoke-test the in-app updater

On a user-mode install (no `.git`):

1. Edit `.silentfrog_revision` in the install root
   (`%LOCALAPPDATA%\Silentfrog\app\` on Windows,
   `~/Silentfrog/app/` on macOS) to an older sha known to exist on
   `dev` — `git log origin/dev --oneline` gives a list.
2. Launch Silentfrog → **Help → Check for Updates…** → expect
   "Update available". Click **Apply and restart** → expect the app
   to relaunch with the newer revision.
3. Re-open the dialog → expect "You're on the latest version".

On a dev clone:

1. Launch via `poetry run silentfrog` → **Help → Check for Updates…**
   → expect "Developer install. Use `git pull` instead."
2. There is no Apply path; verify the working tree is untouched.

### Upgrading from an old dev clone to the new install/update story

Specific scenario: a colleague (or your second machine) already has
a `git clone` of Silentfrog from before this overhaul. How do they get
the new in-app updater?

- **Option A — stay on the dev clone (recommended for developers)**:
  `git pull` on the existing clone. The new code is on `dev`. The
  `Help → Check for Updates…` menu now exists; in dev mode it shows
  the "use `git pull` instead" message, and that's the end of the
  loop. Future updates: just `git pull` from the terminal as before.
- **Option B — switch to the bootstrap install (for colleagues who
  no longer want to deal with git)**: in a fresh location, run
  `Get-Silentfrog.command` (macOS) or `Get-Silentfrog.bat` (Windows).
  The bootstrap lands in `~/Silentfrog/app` or
  `%LOCALAPPDATA%\Silentfrog\app`, which is separate from the old git
  clone, so both coexist. After this install, **Help → Check for
  Updates → Apply and restart** works as designed, and the old git
  clone can be deleted at the user's convenience (`rm -rf
  ~/old-silentfrog-clone`).

There is no "convert a git clone into a user install in place"
shortcut, by design — the in-app updater never modifies a working
tree under git control, even on the maintainer's machines.

### Continuation guide — Mac smoke test from a fresh chat (2026-05-21)

When you open a new Claude conversation on the Mac (Intel or Apple
Silicon), after a `git pull` on `dev`, brief the new instance with the
following so it has the context.

**Quick context to paste at the top of the new session:**

> Repo: `silentfrog` on branch `dev`, latest commit `7351838` (or
> later — `git log --oneline -1` for current). We're testing the
> macOS side of the install/update overhaul that landed in commits
> `2ef77b1..7351838`. The Windows machine already validated commits
> end-to-end and pushed; this Mac session smoke-tests the bootstrap
> script and the in-app updater. Reply in English; respect
> `AGENTS.md` rules.

**Step-by-step smoke test on Mac:**

1. **Confirm the dev clone is on the latest dev**:
   ```
   cd ~/path/to/silentfrog-clone
   git status      # expect clean working tree
   git pull origin dev
   poetry install  # picks up any test deps
   poetry run python tools/doctor.py --quick   # expect OK
   ```

2. **Visually verify the GUI fixes** (commits `83f4fae` + `7351838`):
   ```
   poetry run silentfrog
   ```
   - Home window opens, frog logo visible.
   - **Help** menu lives in the system menu bar at the top of the
     screen (Apple convention — not in the window). It contains
     **Check for Updates…** and **About Silentfrog**.
   - Help → About → version, revision (your local sha), install
     mode "Developer (git clone)", repo link.
   - Help → Check for Updates → after ~1s shows
     *"You're on a developer install (git clone). Use `git pull` to
     update."* This is the correct dev-mode terminal state.
   - Click the gear icon on the home window → Settings dialog opens.
     The selected theme radio button should have a clearly visible
     filled green circle. Switch themes and click OK → the frog
     logo on the home window stays intact (no clipping).
   - Click **Single Page SEO Check** → the window must fit your
     screen width (used to overflow to 1989px; now caps at ~950).
     The tab labels along the top must sit flush left, not centered.
   - Click **Site Crawl** → on the setup page, the form fields
     (Base URL, Sitemap URL, Include prefixes, etc.) must fill the
     row width. Used to render small and centered on macOS.
   - Close the app.

3. **Smoke-test the bootstrap script**. The bootstrap is meant for
   non-dev colleagues, so the test must simulate what they see —
   downloading the file fresh and hitting the macOS Sequoia
   Gatekeeper dialog. Three paths, depending on what you want to
   validate:

   **3a. Full end-to-end (publish a Release first).** From the
   Windows machine or any GitHub UI, push a `v1.0.1` tag — the
   `release-bootstrap.yml` workflow will create a draft Release with
   `Get-Silentfrog.command`, `Get-Silentfrog.bat`, and
   `Get-Silentfrog.ps1` attached. Publish the draft from the GitHub
   web UI. On the Mac, open the Release page in Safari, download
   `Get-Silentfrog.command` (Safari attaches the quarantine xattr,
   reproducing the colleague experience), then double-click it. See
   `bootstrap/README.md` for the Sequoia Gatekeeper bypass via
   System Settings → Privacy & Security → Open Anyway. After
   bypass, expect the bootstrap to install to `~/Silentfrog/app`
   and create a Desktop launcher.

   **3b. Simulated download (faster, no Release needed).** Copy the
   committed file to a fresh location and manually attach the
   quarantine xattr to reproduce the Gatekeeper experience:
   ```
   cp ~/path/to/silentfrog-clone/bootstrap/Get-Silentfrog.command ~/Desktop/
   xattr -w com.apple.quarantine "0083;00000000;Safari;|local-test" ~/Desktop/Get-Silentfrog.command
   chmod -x ~/Desktop/Get-Silentfrog.command
   ```
   Then double-click in Finder and walk through the same Sequoia
   bypass flow.

   **3c. Bypass Gatekeeper entirely (just validate the script
   logic).** From Terminal:
   ```
   bash ~/path/to/silentfrog-clone/bootstrap/Get-Silentfrog.command
   ```
   Doesn't reproduce the Gatekeeper UX but verifies the install
   path otherwise.

4. **After a successful bootstrap install (3a or 3b)**, the user-mode
   install lives at `~/Silentfrog/app`. Test the in-app updater
   end-to-end on it:
   - Double-click the Desktop **Silentfrog** launcher → app opens.
   - Help → Check for Updates → expect *"You're on the latest
     version (<sha>)."* — install mode "User install" (not
     Developer) because there's no `.git` directory in
     `~/Silentfrog/app`.
   - Force the update path: edit `~/Silentfrog/app/.silentfrog_revision`
     to an older sha known to exist on dev. Restart the app.
     Help → Check for Updates → expect *"Update available"* with an
     **Apply and restart** button. Click it. Expect Terminal-style
     log lines streaming in the dialog while `tools/update_silentfrog.py`
     runs, then the app relaunches at the latest sha.
   - Re-check → back to "latest version".

5. **Tear-down (optional):** if you want to clean the bootstrap
   install after smoke-testing:
   ```
   rm -rf ~/Silentfrog
   rm ~/Desktop/Silentfrog.command   # the launcher created by install_silentfrog.py
   rm ~/Library/Logs/Silentfrog-bootstrap.log   # bootstrap log
   ```
   Your dev clone is untouched.

**Known gotchas on macOS Sequoia (15.x)**

- Right-click → Open *no longer bypasses Gatekeeper* (Apple removed
  it). System Settings → Privacy & Security → Open Anyway is the only
  GUI bypass.
- The first Gatekeeper dialog has only "Sposta nel cestino" / "Fine"
  buttons (no Open). The second one (after Open Anyway in System
  Settings) is the one with the **Open** button.
- `bootstrap/README.md` documents all three Sequoia bypass paths.

**Files NOT to touch in this session**

- `experimental/packaging/*` — archived Nuitka path, kept only for
  history. Don't try to run `package_app.py` or `pysidedeploy.spec`.
- `.github/workflows/package-app.yml` — already deleted in commit
  `00b127f`. Replaced by `release-bootstrap.yml`.

**If something fails**, gather:
- The output of `git rev-parse HEAD` (which commit is being tested)
- `poetry run python tools/doctor.py --mode both` (or `--mode poetry`
  on a dev clone)
- `~/Library/Logs/Silentfrog-bootstrap.log` for bootstrap failures
- `~/Silentfrog/app/.silentfrog_revision` content if testing the updater

Report back here and we either fix in place (small change) or capture
as a separate task.

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
- `src/silentfrog/updater.py`
  - Update-check domain logic: typed dataclasses, dev-vs-user mode detection, GitHub commits API client. Qt-free, fully unit-testable.
- `src/silentfrog/update_gui.py`
  - `AboutDialog` and `UpdateDialog` opened from the Help menu in `HomeWindow`. `UpdateDialog` runs the check on a `QThread`, renders one of five states, and drives the Apply-and-restart subprocess.
- `tools/update_silentfrog.py`
  - CLI executor invoked by the GUI Apply button. Downloads the target sha, swaps source files (preserving `.venv`, `.git`, `.env*`, `secrets.local.json`), refreshes pip when `pyproject.toml` changed, updates `.silentfrog_revision`.
- `tools/source_update.py`
  - Pure-Python file-level helpers used by `update_silentfrog.py`. Separated so the orchestration script reads as prose and the copy/extract logic can be unit-tested without subprocesses.
- `bootstrap/Get-Silentfrog.{ps1,bat,command}`
  - One-click installers for end users. Detect/install Python, download the latest source, run `install_silentfrog.py --revision <sha>`.
- `tools/doctor.py`
  - `--mode poetry|venv|both` runtime checks across the dev env and the installer-produced `.venv`.
- `experimental/packaging/`
  - Archived Nuitka/pyside6-deploy path. Not on any supported install route — kept for historical reference. See its `README.md`.
- `docs/INSTALL.md`
  - End-user install / uninstall guide for the bootstrap path and the source-installer fallback. Linked from `README.md` section 2.
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
   - (Nuitka packaging work has been archived under `experimental/packaging/`; not part of any active PR.)

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
