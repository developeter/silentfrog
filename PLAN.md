# Silentfrog Product Plan

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

### M5 Google Search Console Integration

Add GSC URL Inspection, indexing/page state, and crawl stats.

Rules:

- credentials stay local
- tests use mocks by default
- GSC findings feed the shared issue model
- GSC data should enhance crawl findings, not create isolated data dumps

### M6 Log File Analysis

Status: implemented.

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

Explore optional remote report storage and import/export sync.

Candidate target:

- Google Drive first

Rules:

- local-first remains the default
- sync is never automatic
- user must authenticate explicitly
- UI must clearly state what data is uploaded

### M9 Future Integrations / APIs

Explore additional integrations after the issue model, reporting, GSC, logs, and
AI foundations are stable.

Candidate integrations:

- GA4
- PageSpeed Insights / CrUX
- Bing Webmaster Tools
- WordPress / CMS APIs
- rank tracking APIs
- backlink APIs
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
