# Changelog

## Unreleased

### Install / update story

The user-facing install path has shifted from a frozen Nuitka binary
to a small bootstrap script that installs Python on demand and runs
the source installer. Updates happen from inside the running app via
the new "Check for Updates" menu item, which downloads the latest
commit and swaps source files in place. Developer clones (`.git`
directory present) keep working unchanged.

#### New
- `bootstrap/Get-Silentfrog.{ps1,bat,command}` — one-click installers
  for Windows and macOS (Intel + Apple Silicon). Detect Python
  3.12/3.13/3.14, silent-install python.org 3.12.7 if missing, fetch
  the latest source from GitHub, run `install_silentfrog.py` with the
  recorded revision. Published per `v*` tag by the new
  `.github/workflows/release-bootstrap.yml`.
- **In-app updates**: `Help → Check for Updates…` and
  `Help → About Silentfrog`. Dialogs in
  `src/silentfrog/update_gui.py`; domain logic in
  `src/silentfrog/updater.py` (typed dataclasses, `aiohttp` for the
  GitHub commits API, fully unit-testable). Apply-and-restart drives
  `tools/update_silentfrog.py`, which downloads the target archive,
  swaps source files (preserving `.venv`, `.git`, `.env*`,
  `secrets.local.json`), refreshes pip when `pyproject.toml` changed,
  and updates `.silentfrog_revision`.
- `install_silentfrog.py --revision <sha>` records the active revision
  for the in-app updater. Dev clones omit the flag and the updater
  falls back to `git rev-parse HEAD`.
- `silentfrog.__version__` read once via `importlib.metadata` so the
  About dialog and any future telemetry share a single source.

#### Earlier source-installer hardening (carried over)
- Source installer reads runtime dependencies directly from
  `pyproject.toml` via `tomllib`; the duplicated
  `RUNTIME_WHEEL_REQUIREMENTS` constant is gone.
- Cross-platform uninstaller: `python -m tools.source_uninstall` plus
  generated `uninstall_silentfrog.{sh,bat,command}` launchers. Local
  crawl history is preserved by default; opt-in `--purge` wipes it.
- `tools/doctor.py` gained `--mode poetry|venv|both`;
  `python-compat.yml` validates the installer-produced `.venv` after
  each platform run.
- macOS first-run hardening: `install_silentfrog.command` strips
  `com.apple.quarantine`; python.org Python builds auto-run
  `Install Certificates.command`.
- Parametric drift test across all `run_*`, `install_*`, `reinstall_*`,
  `uninstall_*` launchers.

#### Removed / archived
- The Nuitka + pyside6-deploy packaged path is no longer supported
  and has been moved to `experimental/packaging/` for reference. The
  build was slow (60–90 min per platform), unsigned (so still showed
  Gatekeeper / SmartScreen warnings on first launch), and broke the
  "git pull → see updates" loop the team relies on. See
  `experimental/packaging/README.md` for the full rationale.
- `.github/workflows/package-app.yml` deleted.
- `tests/test_package_app_unit.py` excluded from default `pytest`
  discovery via a new `testpaths = ["tests"]` setting.

## 1.0.0

- Massive redirect check from Excel input.
- Stable desktop SEO toolkit with single-page crawl (meta, headers, images with loading/fetchpriority, links, redirects, canonical, robots, hreflang, structured data, keywords, AI crawl, performance, SERP preview).
- Export to Excel per tab.
- Gentle crawl mode with presets and optional headers/cookies.
- Cross-platform theme fixes (dark/light), improved settings dialog, and macOS-friendly scrollbars.
- README, contributing, security policy, and issue/PR templates added.