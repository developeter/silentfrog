# Packaging preview (maintainer)

Step-by-step to build and try the Silentfrog packaged app locally before each release. Not user-facing — it's the rehearsal of what GitHub Actions does on a tag push.

## Prerequisites

- macOS Apple Silicon or Intel, **or** Windows 10/11.
- Python 3.12, 3.13, or 3.14.
- `poetry install` already run in the repo.
- On macOS only: `sips` and `iconutil` (Xcode Command Line Tools — preinstalled on most macOS).

## Build locally

```bash
poetry run python tools/doctor.py --quick
poetry run python tools/package_app.py --mode standalone --keep-deployment-files
```

This single command does three things in order:

1. Generates `src/silentfrog/assets/icon.icns` from `icon.png` (macOS only, cached if up-to-date).
2. Stages `deploy/main.py` and a platform-specific `pysidedeploy.spec` under `build/package/<os>/`, then invokes `pyside6-deploy`. The spec adds Nuitka `--nofollow-import-to=` flags for `pyRdfa`, `pyMicrodata`, and `rdflib` to work around a Nuitka 2.7.11 assertion triggered by `extruct`'s transitive RDFa parsers.
3. On macOS produces `build/package/darwin/Silentfrog-<version>-macos-<arch>.dmg`; on Windows produces `build/package/windows/Silentfrog-<version>-windows-x64.zip`. The `--skip-artifact` flag stops after step 2; `--artifact-only` re-runs step 3 alone (assumes step 2 output is already present).

## Inspect the macOS app

```bash
open build/package/darwin/deployment/Silentfrog.app
```

First launch on macOS without code signing triggers Gatekeeper:

> "Silentfrog" can't be opened because Apple cannot check it for malicious software.

Workaround for the maintainer preview:

```bash
xattr -dr com.apple.quarantine build/package/darwin/deployment/Silentfrog.app
open build/package/darwin/deployment/Silentfrog.app
```

Compare against the source-installer experience (`./run_silentfrog.sh` after `python install_silentfrog.py`) to spot any sizing / DPI / icon differences. macOS GUI sizing is a known watch-area — call out anything that diverges so it ends up in the GUI tracker rather than slipping into a release.

## Inspect the DMG

```bash
open build/package/darwin/Silentfrog-1.0.0-macos-arm64.dmg
```

The DMG opens with `Silentfrog.app` plus a symlink to `/Applications` (drag-to-Applications layout). Dragging the `.app` to `/Applications` and opening from there is the path a real end-user would take.

## Verify on Windows

Run the same `tools/package_app.py --mode standalone` command. The output `Silentfrog-<version>-windows-x64.zip` contains a `Silentfrog/` folder with `Silentfrog.exe`. SmartScreen will warn on first launch (unsigned), but "More info → Run anyway" gets through.

## Verify on Linux (best-effort)

The packaging matrix does not officially ship Linux, but `tools/package_app.py --mode standalone` still produces a zip locally. Not gated by CI.

## Diagnose a broken build

- `*.iconset` build fails: `sips` or `iconutil` missing. Install Xcode Command Line Tools.
- Nuitka asserts `Must not attempt to locate <ModuleName 'pyRdfa'>`: the `--nofollow-import-to=` flags in `pysidedeploy.spec` got overwritten. Re-check the materialized spec under `build/package/<os>/pysidedeploy.spec`.
- pyside6-deploy fails with `cannot access local variable 'tree'`: a `.py` file in `src/silentfrog/` reintroduced a UTF-8 BOM. Run:
  ```bash
  python3 -c "from pathlib import Path; [print(p) for p in Path('src/silentfrog').rglob('*.py') if p.read_bytes().startswith(b'\\xef\\xbb\\xbf')]"
  ```
  to find offending files, then strip the first three bytes.

## Release flow (what tag push triggers)

`.github/workflows/package-app.yml` runs the same `tools/package_app.py` across Windows, macOS Intel, and macOS Apple Silicon on Python 3.14. On a tag matching `v*` it publishes the resulting DMGs and ZIPs to GitHub Releases as a draft. The maintainer reviews the draft, writes release notes, and clicks Publish.

Code signing and Apple notarization are deliberately out of scope — first-run Gatekeeper / SmartScreen warnings are documented in the release notes until a signing milestone lands.
