# Silentfrog Handoff

Last updated: 2026-05-15

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
  - `ca5a90b Add local site crawl history browser`
- Existing uncommitted files observed before creating this handoff:
  - `.github/workflows/package-app.yml`
  - `.github/workflows/python-compat.yml`
- Those workflow edits were not made during this handoff and should not be overwritten without checking with the user.

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

1. Check the current uncommitted workflow edits before any new work:

```powershell
git status --short
git diff -- .github/workflows/package-app.yml .github/workflows/python-compat.yml
```

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
