# Changelog

## Unreleased

### Install / package
- Source installer reads runtime dependencies directly from `pyproject.toml` via `tomllib`; the duplicated `RUNTIME_WHEEL_REQUIREMENTS` constant is gone, so adding a dep no longer requires editing two files.
- Cross-platform uninstaller: `python -m tools.source_uninstall` plus generated `uninstall_silentfrog.{sh,bat,command}` launchers. Removes `.venv`, Desktop launcher, and repo-root launcher scripts; user crawl history is preserved by default and only purged with `--purge`. Never touches `~/nltk_data`.
- `tools/doctor.py` gained `--mode poetry|venv|both`; `python-compat.yml` workflow now also validates the installer-produced `.venv` after each platform run.
- macOS first-run hardening: `install_silentfrog.command` / `reinstall_silentfrog.command` strip `com.apple.quarantine` silently; on python.org Python builds, `install_silentfrog.py` also runs `Install Certificates.command` automatically so the first HTTPS fetch does not fail with an SSL error.
- New drift-detection test parametric over every committed launcher (`run_*`, `install_*`, `reinstall_*`, `uninstall_*`): catches accidental divergence between the render functions and the on-disk files; eliminates `git status` noise after a fresh install.

### Packaging / distribution
- `pysidedeploy.spec` committed at repo root; `tools/package_app.py` materializes it into `build/package/<os>/pysidedeploy.spec` with platform-specific icon and absolute paths, then invokes `pyside6-deploy` from there.
- macOS app icon (`icon.icns`) generated from `icon.png` via `sips` + `iconutil` and committed alongside `icon.png` / `icon.ico`.
- Nuitka 2.7.11 assertion on `pyRdfa` (from `extruct`'s transitive RDFa parsers) worked around with `--nofollow-import-to=pyRdfa,pyMicrodata,rdflib`.
- UTF-8 BOM stripped from 9 files under `src/silentfrog/` that triggered a `cannot access local variable 'tree'` parser crash in pyside6-deploy's `dependency_util.py`.
- Bundle now ships the non-Python data trees explicitly: `--include-data-dir` for `src/silentfrog/assets` (icons, including the gear in the settings dialog) and `src/silentfrog/resources` (stopwords).
- Build pipeline now produces a `.dmg` on macOS (drag-to-Applications layout via `hdiutil`) and a portable `.zip` on Windows, named `Silentfrog-<version>-{macos-arm64,macos-intel,windows-x64}.<ext>`.
- `.github/workflows/package-app.yml` publishes a draft GitHub Release with those artifacts on `v*` tag pushes (still unsigned: macOS Gatekeeper and Windows SmartScreen show the standard first-launch warning).
- New maintainer doc `docs/packaging_preview.md` documents the build / inspect / Gatekeeper-bypass flow for local rehearsals before each release.

## 1.0.0

- Massive redirect check from Excel input.
- Stable desktop SEO toolkit with single-page crawl (meta, headers, images with loading/fetchpriority, links, redirects, canonical, robots, hreflang, structured data, keywords, AI crawl, performance, SERP preview).
- Export to Excel per tab.
- Gentle crawl mode with presets and optional headers/cookies.
- Cross-platform theme fixes (dark/light), improved settings dialog, and macOS-friendly scrollbars.
- README, contributing, security policy, and issue/PR templates added.