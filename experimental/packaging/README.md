# Experimental: Nuitka-based packaging (archived)

This directory keeps the previous Nuitka + pyside6-deploy packaging path
around for reference. It is **no longer supported** and is not part of
any CI workflow.

## Why it's archived

The packaged path was intended to produce a signed `.exe` / `.dmg` that
users could install without thinking about Python. In practice:

- Nuitka standalone builds with PySide6 take 60–90 minutes per
  platform on GitHub Actions, with high failure rates around
  third-party imports.
- Without code signing, both Windows SmartScreen and macOS Gatekeeper
  still warn on first launch, so the promised "frictionless install"
  never materialised.
- The maintainer pushes updates continuously; a packaged build
  freezes users at the version they downloaded, breaking the
  "git pull → see updates" loop the team relies on.
- The target audience (the maintainer's two machines plus a handful
  of mostly technical colleagues) does not justify the build /
  maintain cost.

The supported install paths are now:

1. **One-click bootstrap** for end users via `bootstrap/Get-Silentfrog.{ps1,bat,command}`
   (downloads/installs Python if missing, fetches the source archive,
   runs the source installer). See `bootstrap/README.md`.
2. **Source install** for developers via `install_silentfrog.py`,
   which creates a local `.venv`. See section 3 of the top-level
   `README.md`.

Updates land via the in-app **Help → Check for Updates…** feature,
which downloads the latest commit on `dev` and swaps source files
in place. See `tools/update_silentfrog.py`.

## What's here

| File | Purpose |
|---|---|
| `package_app.py` | The original orchestrator: `pyside6-deploy` + Nuitka, with the Windows hardening from commit `2ef77b1`. |
| `pysidedeploy.spec` | The pyside6-deploy spec template, including `--assume-yes-for-downloads` for headless builds. |
| `tests/test_package_app_unit.py` | 32 unit tests — these are excluded from default `pytest` discovery via `testpaths` in `pyproject.toml`. |
| `README_legacy.md` | The original maintainer-side rehearsal doc. |

## If you ever revive this

1. Move `package_app.py`, `pysidedeploy.spec`, and the test file back
   to their original locations (`tools/`, repo root, `tests/`).
2. Add the corresponding paths back to `pyproject.toml`'s `testpaths`.
3. Restore the `.github/workflows/package-app.yml` workflow.
4. Consider paying for Authenticode (Windows) and Apple Developer ID
   notarization — without those, the unsigned warning UX is the same
   as today's source-install path with extra friction.
