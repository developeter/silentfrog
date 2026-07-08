# Silentfrog Product Plan

> **This is the product north star (direction + privacy policy), not the live
> build queue.** For *where we are today* and *what to do next*, read
> [`HANDOFF.md`](HANDOFF.md) first. The milestones below (M0–M9) were largely
> executed through the V1–V20 build
> ([`docs/v2_beat_screaming_frog_roadmap.md`](docs/v2_beat_screaming_frog_roadmap.md),
> complete) plus the GEO moat; the active track now is the gap analysis in
> [`docs/v3_roadmap.md`](docs/v3_roadmap.md). Statuses here were re-verified
> against the code on 2026-07-08.
>
> ⚠️ Naming note: this plan's **M8 is Remote Sync**; the v3 roadmap's "M8" is
> an unrelated *JS link crawl*. Disambiguate by which doc you are reading.

## Direction

Silentfrog should become a local-first, open-source, action-oriented SEO audit tool.
The goal is not to clone raw-data crawlers. The goal is to turn crawl, GSC, log,
and AI/GEO evidence into clear priorities, explanations, and next actions.

## Product Positioning

- Primary user: SEO operator.
- Main value: action clarity over raw data volume.
- Differentiators:
  - open-source and customizable workflow
  - local-first privacy
  - clear issue reasons, evidence, and recommended fixes
  - Google Search Console integration
  - AI/GEO analysis backed by collected evidence
  - future service/API extensibility

## Operating Principles

- Build by milestone, not all at once.
- Keep local-first behavior as the default.
- Use conservative severity:
  - red only for blockers or high-confidence damage
  - yellow for warnings
  - neutral/blue/gray for informational values
- Lead with prioritized actions, not raw export sheets.
- Keep raw crawl data available as appendix/evidence.
- Do not start GSC, logs, AI, or remote sync before the shared issue model exists.

## Privacy And Secrets Policy

- API keys, OAuth tokens, crawl data, imported logs, and generated reports stay local by default.
- Secrets must never be stored in tracked source files.
- Track example files only, such as `.env.example` or `secrets.example.json`.
- Real local secret files must be ignored by git, for example `.env`, `.env.local`, or `secrets.local.json`.
- Prefer OS/user-local storage for app settings, credentials, crawl history, and report history.
- Remote sync must be optional, explicit, user-authenticated, and clear about what data is uploaded.

## Milestones

### M0 Product Roadmap Document

Status: complete.

Create this `PLAN.md` as the master roadmap and document the local-first privacy
and secrets policy.

### M1 Shared Audit Issue Model

Status: implemented.

Create typed audit issue objects used by GUI, exports, history, GSC, logs, and AI.

Required fields:

- issue id
- category
- severity
- affected URL or site scope
- reason
- evidence
- recommendation
- source area
- confidence where applicable

Expected models include:

- `AuditIssue`
- `IssueSeverity`
- `IssueCategory`
- `IssueEvidence`

### M2 Recap UX

Status: implemented.

Add action-oriented recap views for single-page scans and Site Crawl.

The recap should show:

- overall health summary
- critical blockers
- warnings
- opportunities
- next actions
- clear drill-down to affected rows/details

Color coding must follow the conservative severity model.

### M3 Action Workbook Export

Status: implemented.

Redesign Excel exports around actions first, appendix data second.

Target workbook shape:

- `Read me / Legend`
- `Executive summary`
- `Prioritized issues`
- `Affected URLs`
- `Indexability blockers`
- `Content/meta actions`
- `Technical actions`
- `Images actions`
- `AI/GEO actions`
- `Appendix - raw data`

The workbook must explain why each issue matters, which URLs are affected, what
evidence was found, and what action is recommended.

### M4 Crawl History And Diff

Status: implemented.

Save completed crawl summaries locally and compare runs.

The diff should show:

- fixed issues
- new issues
- worsened issues
- recurring issues
- health trend over time

Visible local UX:

- **View past scans** opens saved Site Crawl runs
- saved runs are listed by site/date
- selecting a run shows summary and diff against the previous local run for that site
- selected runs can be exported as JSON or deleted locally
- **Open scan** (v3) reloads a saved run into the full SQL-paged results table
  with per-page detail dialogs, while its SQLite store is still on disk (stores
  are retained with a rolling prune; deleting a run also unlinks its store)

### M5 Google Search Console Integration

Status: implemented foundation (v2.0 V7/V14).

Shipped: OAuth loopback + keyring token store, Search Analytics metrics, and a
URL Inspection call (rich-results verdict only) feed the AI Visibility checks;
local opt-in creds (`SILENTFROG_GOOGLE_ENABLE`), mocked tests. Not yet shipped:
the full **indexing/page-state** deliverable and **crawl stats**.

Add GSC URL Inspection, indexing/page state, and crawl stats.

Rules:

- credentials stay local
- tests use mocks by default
- GSC findings feed the shared issue model
- GSC data should enhance crawl findings, not create isolated data dumps

### M6 Log File Analysis

Status: partially implemented (needs wiring).

The findings-to-issue-model mapper (`log_analysis.py`, all five target
findings) is complete and unit-tested, but has **no runtime caller** — it is
unreachable from the GUI, CLI, or crawl pipeline. The only wired path,
`silentfrog-cli logs` (the `logs/` package), emits a crawl-budget JSON report
that does **not** feed the shared issue model and lacks orphan / important-page
detection. Closing M6 = wire `log_analysis.issues_for_log_report` into a user
surface (or fold the `logs/` path into it).

Import server logs from local files and map findings into the issue model.

Target findings:

- Googlebot activity
- orphan crawled URLs
- crawl waste
- blocked or redirected bot hits
- important pages not hit by bots

Imported logs remain local.

### M7 AI-Assisted SEO/GEO Review

Status: implemented foundation.

Add optional AI integration for higher-quality recommendations.

Rules:

- user-configured provider/API key
- API keys stay local
- AI works on already-collected evidence
- AI is not the source of truth for deterministic crawl checks
- results include evidence references and confidence

Candidate use cases:

- page recap
- content quality review
- AI/GEO answerability suggestions
- issue prioritization
- client-friendly explanations

Implemented foundation:

- typed AI review inputs, findings, results, and local provider config
- ignored local secrets support through environment variables or `secrets.local.json`
- evidence-bound prompt builder
- provider response parser for mocked JSON responses
- mockable client seam
- mapping from AI findings into the shared `AuditIssue` model

Real provider calls and UI controls remain future slices.

### M8 Remote Save / Import / Sync

Status: implemented foundation.

Explore optional remote report storage and import/export sync.

Candidate target:

- Google Drive first

Rules:

- local-first remains the default
- sync is never automatic
- user must authenticate explicitly
- UI must clearly state what data is uploaded

Implemented foundation:

- provider-neutral sync plans and manifests
- explicit confirmation required before upload or download
- public upload/download summaries that omit local absolute paths
- mockable remote sync client boundary
- local-folder client for tests and future UI prototyping
- local OAuth/remote-sync placeholders in `secrets.example.json`

Real Google Drive OAuth and UI controls remain future slices.

### GEO Extension

The detailed GEO (Generative Engine Optimization) plan lives in
[`docs/geo_roadmap.md`](docs/geo_roadmap.md). It extends the existing AI
Visibility audit to cover Google's AI Optimization Guide signals, E-E-A-T,
SSR parity, and a GEO Score 0–100, across six milestones (M0..M5). It is a
sibling roadmap to the milestones above, not a replacement.

### M9 Future Integrations / APIs

Status: partially shipped.

Explore additional integrations after the issue model, reporting, GSC, logs, and
AI foundations are stable.

Already shipped in v2.0 (real, wired, gated-optional):

- **GA4** — GA4 Data API `runReport`, gated on `SILENTFROG_GOOGLE_ENABLE` (V7)
- **PageSpeed Insights / CrUX** — `perf_crux.fetch_crux` (field CWV) + on-demand
  Lighthouse via PSI (V14)
- **backlink APIs** — Semrush `backlinks_overview`, gated on
  `SILENTFROG_SEMRUSH_ENABLE` (V17)

Still future / unexplored:

- Bing Webmaster Tools
- WordPress / CMS APIs
- rank tracking APIs
- task/project tools

All integrations must feed the shared issue model or report history.

## Acceptance Criteria

- M1 issue model tests cover severity mapping, evidence extraction, duplicate grouping, and conservative color rules.
- M2 GUI tests verify recap cards, issue counts, table coloring, and drill-down behavior.
- M3 export tests verify sheet order, required columns, evidence, recommendations, and appendix behavior.
- Secrets/config tests verify real secret files are ignored and example files contain no real keys.
- AI, GSC, remote sync, and third-party API tests use mocks by default.
- Every milestone must pass:
  - `poetry run python tools/doctor.py --quick`
  - focused tests for touched modules
  - `poetry run python tools/doctor.py`
