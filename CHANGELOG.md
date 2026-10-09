# Changelog

## 2.0.0

### Crawl settings are remembered, and their results are visible

Ticked checks used to reset every time a Single Page or Site Crawl window was
opened, the label next to "Crawl settings..." said "Standard crawl" with
everything ticked, and two checks (tech stack, custom extraction) had no result
view at all.

#### Changed
- The opt-in ticks (SSR parity, per-bot SSR, JS links, accessibility, tech
  stack, custom extraction rules, embeddings, stealth, gentle mode and its
  parallelism) persist across restarts and are shared by both windows. The Site
  Crawl profile is remembered separately; Single Page stays Deep. A tick whose
  optional extra is no longer installed loads unticked. Insecure TLS,
  private-network access, custom headers and cookies are never stored. Nothing
  stored means today's all-off defaults.
- The label next to "Crawl settings..." (and the Site Crawl results page and
  saved-scan history) now lists the active checks, and marks render checks
  "(skipped: needs Deep)" when the profile will not run them. "max N/host" only
  shows while gentle mode is on.
- New **Trust > Tech & extraction** tab (Single Page and the Site Crawl
  per-page detail) plus "Tech & extraction" Excel sheets. The AI-export page
  JSON now also carries `tech_stack`, `accessibility`, `lighthouse`,
  `rich_results` and `integrations`.
- The Site Crawl results table has a tooltip pointing at the double-click
  per-page audit.

### Security: custom headers and cookies no longer reach third-party sites

The Cookie, Authorization and custom headers typed into Crawl settings were
attached to the whole probing session, so every link-status, canonical,
hreflang and redirect probe sent them to whatever site the page linked to, and
a redirect off-site carried them along. They are now sent only to the origin
being audited.

#### Fixed
- Custom headers / Cookie are added per request and only when the target's
  origin (scheme + host + port, exact) equals the audited page's origin. A
  sibling subdomain, another port, or an http/https switch is a different
  origin and gets none. Sessions otherwise carry only User-Agent / Accept /
  Accept-Language.
- Canonical and hreflang probes follow redirects one hop at a time so a
  redirect to another origin drops the headers; the redirect trace re-scopes
  every hop; the shared transport also strips every non-identification
  request header on any cross-origin redirect (aiohttp alone only drops
  Cookie / Authorization, so a custom `X-Api-Key` used to survive the hop).
- robots.txt `Sitemap:` and sitemap-index entries on a third-party origin are
  fetched without the credentials; discovery files do the same.
- robots.txt fetches (single page, site crawl spider gate, crawl-delay) now
  send the configured User-Agent and the origin-scoped headers instead of
  aiohttp's default User-Agent and nothing else, so a cookie-gated
  `Disallow:` is honoured.

### Installer feedback: window stays open, clear summary, CRLF `.bat`

Double-clicking `install_silentfrog.bat` opened a console that downloaded
packages and then vanished, so there was no way to tell whether the install
worked or whether the Chromium download had failed.

#### Changed
- `install_silentfrog.bat` / `uninstall_silentfrog.bat` keep the exit code,
  print a final success or `FAILED (exit code N)` line, and `pause` so the
  window stays open, then exit with the preserved code. `SILENTFROG_NO_PAUSE`
  or `CI` skips the pause so automation never hangs. `run_silentfrog.bat` is
  unchanged (it still launches detached).
- `tools/source_install.py` prints a `Step N/M: ...` label before each install
  command and ends with one summary block (version, venv, extras, Chromium
  `OK` / `FAILED - run: <python> -m playwright install chromium` / `not
  requested`, Desktop launcher path). Fail-hard errors end with
  `Install FAILED: <reason>`. `render_install_summary()` is the pure helper;
  `_run_chromium_post_step()` now returns a `ChromiumStatus`.

#### Fixed
- Launchers written with `*.bat` are now CRLF (cmd.exe parses labels and
  `goto` unreliably with LF) and `.gitattributes` pins `*.bat text eol=crlf`,
  so an install no longer leaves the three `.bat` files showing as modified
  with an empty diff under `core.autocrlf=true`.
- `uninstall_silentfrog.bat` now passes `--keep-launcher uninstall_silentfrog.bat`
  to the uninstaller, so the running batch file is no longer deleted underneath
  cmd (which printed "batch file cannot be found" and returned exit code 1
  even after a successful uninstall). The real exit code is preserved.

### AI review: Gemini free tier, provider picker, real error reasons

The "AI review" button silently picked local Ollama when nothing else was
configured, so on a machine without Ollama running it just showed
`error: empty response` — the underlying failure (connection refused, bad
key, rate limit) was swallowed. There was also no way to pick a provider or
type a key from the GUI.

#### New
- `src/silentfrog/ai_review_providers.py` — `GeminiReviewClient` (Google's
  free tier, `resolve_api_key("gemini")` shared with the AI share-of-voice
  keyring entry); `auto_config(preferred=...)` replaces `default_config()`
  (explicit env/`secrets.local.json` config wins, else the caller's
  preferred provider, else the first of gemini/openai/anthropic with a
  resolvable key, else Ollama); `provider_remedy(provider)` and
  `PROVIDER_CHOICES`/`DEFAULT_MODELS` for the GUI/CLI picker.
- `src/silentfrog/ai_review_dialog.py` (new module, moved out of
  `seo_gui.py`) — `AiReviewSetupDialog` (provider/key/model picker, a free
  Gemini-key help link, keys persisted to the OS keychain) and
  `AiReviewResultDialog` (renders a failed review as a headline + remedy +
  raw reason, or findings grouped by severity, with a Copy button).
  Threading copies `google_connect_dialog`'s `_JobHolder` + polling
  `QTimer` pattern instead of `QMetaObject.invokeMethod` on a live widget,
  since a provider call can run long enough to make that a real
  use-after-free risk.
- `silentfrog-cli review` gained `--provider {gemini,openai,anthropic,ollama}`
  and `--model NAME`.

#### Changed
- `ai_review_providers._post_json` now returns the real failure reason
  (`HTTP <status>: <body>`, `connection refused / not reachable at <url>`,
  `timed out after Ns`) instead of swallowing it — every client's
  `raw_summary` carries that reason instead of a generic empty-response
  message when the POST itself fails.
- `AnthropicReviewClient` now also checks the shared ai-engines keyring
  (`resolve_api_key("anthropic")`) before its direct env-var read.

### Full evidence dossier in "Export for AI analysis"

The AI export dropped almost everything the audit measured — only the
warning/critical AI-visibility rows survived a compact export, alongside a
score line, title/description, word count, and a handful of optional
one-liners. Both "Export for AI analysis" buttons (single page + Site Crawl)
now write a self-contained Markdown/JSON dossier an AI assistant can act on
without asking for more context.

#### Changed
- `src/silentfrog/exporters/llm_export.py` rewritten: the page dossier now
  covers identity/redirects/canonical/indexability, the GEO score with a
  per-area breakdown, the prioritised issue list with evidence
  (`audit_issues.issues_for_payload`), every AI-visibility check by area,
  content (headings outline, SERP, content quality, text glitches, top
  keywords, structure/citation/E-E-A-T/SEO-basics), links/images
  (broken links, missing alt, oversized images, pseudo-links), hreflang/
  structured data/social, performance (CWV lab + field, heaviest resources,
  third-party hosts), the AI-bot access matrix + SSR/per-bot render diffs,
  and optional integrations (GSC, GA4, Semrush, AI SOV, brand mentions,
  topic embeddings, tech stack, accessibility) when measured. The Site
  Crawl dossier adds a crawl summary, site-wide hints
  (`hints.build_hints`), duplicate titles/descriptions, error/redirecting
  pages, the most common failing checks, site-wide discovery facts, a full
  page index, and worst-N page detail. An optional signal that was never
  run is always marked "Not measured (feature off)" — never silently
  dropped, never presented as a failure (CLAUDE.md §1.5).
- Both GUI buttons now pass `mode="full"`; the CLI/MCP default stays
  `"compact"`. The completion dialogs now mention pasting the export into
  "Claude / ChatGPT / Gemini" rather than only Claude.

### Built-in Google OAuth app (bring-your-own stays as an override)

Connecting Search Console / Analytics 4 required every user to create their
own Google Cloud project and OAuth client before v2.0.0 could ship. The
maintainer now ships a maintainer-owned Google OAuth *Desktop app* client so
end users just click Connect and sign into their own Google account — data
flows from Google straight to the user's machine, never through the
maintainer. A Desktop-app client secret is not a confidential credential
(Google's own docs, RFC 8252 §8.5): it only identifies the app, and access
always requires the user's own browser consent. Scopes stay read-only
(`webmasters.readonly`, `analytics.readonly`).

#### New
- `src/silentfrog/integrations/google/app_client.py` — `BUILTIN_CLIENT_ID`
  / `BUILTIN_CLIENT_SECRET` (empty placeholders; see `docs/RELEASING.md`
  for the pre-tag checklist), with a `SILENTFROG_GOOGLE_CLIENT_ID` /
  `SILENTFROG_GOOGLE_CLIENT_SECRET` env override so the flow is testable
  before the real credentials are pasted in.
- `connect.resolve_client_secrets`: an explicit BYO `client_secret.json`
  path always overrides the built-in app; an empty path falls back to it,
  or fails with a README pointer when this build has neither.
- The Connect Google dialog's credentials group is now "Google app": a
  status line (built-in available vs. not), the existing path field
  relabelled as an advanced override, and "Google hasn't verified this
  app" click-through guidance shown only while the built-in app is in use.

#### Fixed
- The BYO Testing/7-day consent-screen warning now reads as applying to a
  user's own OAuth client specifically — the built-in app's consent screen
  is the maintainer's responsibility, not something a user configures.

### Reinstall regression: GEO checks and Connect Google disabled

A reinstalled machine found most GEO checkboxes and the "Connect
Google…" button greyed out. Root cause: the source installer only ever
installed `[project].dependencies`, never any `[project.optional-
dependencies]` extra, so a fresh `.venv` had none of playwright,
google-auth-oauthlib, or pyqtgraph.

#### Fixed
- `tools/source_install.py` now bundles the `geo-render`, `google`, and
  `charts` extras by default (`DEFAULT_EXTRAS`), and best-effort
  downloads the Chromium browser `geo-render` needs
  (`post_install_plan`) as a separate, non-fatal post-install step — a
  blocked/slow download prints the manual `playwright install chromium`
  command instead of failing the install. `stealth` and `embeddings`
  stay opt-in (heavier: curl_cffi/scrapling and the torch stack,
  respectively). New `--extras <list|none>` CLI flag on
  `install_silentfrog.py` overrides the bundle; an unknown extra name
  stops the installer with the valid names.
- **Settings → GEO checks** (Site Crawl only): ticking a rendering
  check (SSR parity, per-bot SSR, JS-rendered links, accessibility
  audit) under a non-Deep profile now switches the profile to Deep and
  explains why, instead of silently doing nothing (H4 already gated
  these checks on Deep; nothing surfaced that in the dialog). Lowering
  the profile again afterwards shows a warning that the ticked checks
  will be skipped, without auto-unticking them.

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
- `keyring` is now a base dependency (was behind the `[semrush]`/`[google]`
  extras) so a stock install can store the optional Semrush/Google API
  keys from Settings without installing an extra first; the keys
  themselves stay off by default. The now-redundant `semrush` extra
  (it shipped nothing but `keyring`) was removed.

#### Fixed
- `bootstrap/Get-Silentfrog.{ps1,command}` now track the latest
  published `v*` GitHub Release, falling back to the `dev` branch only
  when no release exists yet. Previously both scripts always pulled
  `dev`, which also fed a commit SHA into the in-app updater's
  tag-based comparison — a permanent false "update available" once
  releases start shipping.
- `.github/workflows/release-bootstrap.yml` gained a `workflow_dispatch`
  `draft` input (default `true`, unchanged behaviour) instead of a
  hardcoded value, so a signed release can later be published
  deliberately.

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
- `update_trust.py`'s pinned update-signing key was removed
  (`PINNED_PUBLIC_KEY = ""`). The key had no known private
  counterpart, so no release could ever be signed against it and its
  provenance was unverifiable — a supply-chain risk with no upside.
  Empty is the module's own documented fail-closed default: the
  updater now refuses every update until a real minisign keypair is
  generated and its public half is pinned here (see
  `docs/RELEASING.md`).

### Reachability fixes

Three v2.0 milestones had working, tested code with no way for a user
to reach it. All three are now wired to a GUI entry point:

#### Fixed
- **V1 stealth fetcher** — Settings → Advanced gained a stealth
  checkbox (TLS impersonation / Cloudflare Turnstile via `scrapling`),
  disabled with an explanatory tooltip when the `stealth` extra isn't
  installed. Previously only an undocumented env var set
  `use_stealth`.
- **V16 robots simulator** — Settings → Advanced gained "Test a URL
  against robots.txt…", opening `robots_sim_dialog.py` which runs
  `simulate_robots()` against a live fetch (through the guarded
  `fetch_page`) or pasted robots.txt text. Previously `simulate_robots`
  had zero callers outside its own tests.
- **V7 Google connect flow** — the OAuth loopback flow
  (`integrations/google/oauth.py`) is now reachable from a new
  "Connect Google…" button in Settings (`google_connect_dialog.py`):
  bring your own `client_secret.json`, an editable GSC property field,
  "Use Google data in audits" off by default, a Test Connection
  button, and a 7-day Testing-consent-screen warning.
  `connection.from_env` falls back to the stored config, with an env
  var still taking priority for headless use. Previously
  `run_loopback_flow` and `save_token` had zero callers and the app's
  own recommendation text pointed at a menu that didn't exist.
- **M6 server-log analysis GUI** — a new 4th home-screen button opens
  `log_gui.py`, a window over the existing `log_analysis` engine.
  Previously `log_analysis` was CLI-only (`silentfrog-cli logs`).
  Remote sync (M8, `remote_sync.py`) remains unwired — see Known
  limitations below.

### Site Crawl release audit

An eight-lens audit of the Site Crawl surface against the 2.0.0
candidate (runtime smoke, engine safety, store/history, threading,
exports, recap/table, docs-vs-code, CLI parity); every item below was
independently reproduced before being fixed and carries a regression
test. Full list: `docs/site_crawl_2_0_readiness.md`.

#### Fixed
- **Compare with previous / Map redirects** never had a previous run
  to compare against: `_start_crawl` cleared the latest report before
  `_handle_report` copied it into "previous", so both buttons failed on
  every genuine second crawl. The previous run is now captured at
  start.
- **`silentfrog-cli crawl --limit N`** was a no-op for the default
  Hybrid/Spider modes: the cap the frontier actually enforces is
  `spider.max_urls`, which `SiteCrawlConfig.from_text` left at its
  100 000 default for callers that don't pass an explicit spider
  config. It now follows `limit`.
- **`silentfrog-cli crawl` exit code** — a malformed URL or an
  unreachable host produced a "completed" report with zero reachable
  pages and exit 0, so cron / Task Scheduler could never notice. It
  now exits 1 when nothing was discovered or every page failed.
- **CLI audit profile** — CLI and scheduled crawls silently ran the
  `DEEP` profile while the GUI's Site Crawl defaults to `STANDARD`;
  the same nominal crawl was unconditionally heavier from the CLI.
  Both default to `STANDARD` now.
- **`--allow-private-network` / `--allow-insecure-tls`** CLI flags —
  the GUI could audit intranet, loopback or self-signed targets; the
  CLI had no way to opt in.
- **robots.txt fetched once per origin per crawl** instead of once per
  page: the crawl-delay check (`respect_crawl_delay`, on by default)
  re-fetched it uncached for every URL, unlike every other discovery
  file. `robots_fetch_scope` now mirrors `discovery_scope`.
- **Crawl-delay pacing** — the delay was slept in full before every
  sub-request of a page audit (main fetch, canonical probe, redirect
  trace, link-status probes) instead of once against elapsed time per
  host, multiplying a 2 s crawl-delay several-fold per page. Requests
  to a host are now paced by a shared next-allowed clock.
- **Sitemap discovery scope** — the three hard-coded common sitemap
  paths were probed even when `robots.txt` already named a sitemap,
  so an unrelated sitemap at a common path could widen the crawl.
  Common paths are now a fallback only.
- **Opening a saved scan during a live crawl** silently hid Stop and
  re-enabled Start while the crawl thread kept running; a second Start
  could then overlap the first. The history browser refuses while a
  crawl is active, and Start is guarded.
- **Link graph on a reopened past scan** opened the store read-write
  (running schema creation on a history file) just to read edges, and
  any failure surfaced as the wrong "no links" message. It reads
  read-only via `crawl_run_repository.read_graph_inputs` now.
- **Recap hint click with an active filter** — clicking a hint whose
  row was hidden by the status / indexability filter did nothing;
  the filters are reset before the row is selected.
- **Export buttons** always export the full crawl, never the filtered
  view; their tooltips now say so instead of leaving it ambiguous.
- **Sitemap-only crawl with nothing discoverable** completed as a
  "successful" run of 0 URLs with no explanation. The report now
  carries a warning naming the base URL and suggesting Auto mode or a
  corrected sitemap URL; no silent fallback is added, since the mode
  was an explicit choice.
- **Site Crawl docs** — `docs/site_crawl_feature_spec.md`,
  `docs/site_crawl_roadmap.md` and the README described the v1
  feature set as current: three home actions (there are four), no
  recursive link discovery (Hybrid mode follows links by default), JS
  rendering and crawl history/diff as out of scope (both shipped),
  and an absolute "never bypasses WAF" promise that the opt-in
  stealth fetcher contradicts. All corrected and pinned by
  `tests/test_docs_consistency.py`.
- **Closing a Site Crawl window mid-crawl** left the ETA timer
  running and the cross-thread progress/report/error signals
  connected, safe only because the window was never actually
  destroyed: nothing set `WA_DeleteOnClose`, so `_forget_child` never
  fired and every close+reopen grew `HomeWindow._child_windows`
  forever. `closeEvent` now stops the timer and disconnects the
  signals first, and `_spawn_child` sets `WA_DeleteOnClose` for
  `SiteCrawlWindow` / `LogWindow` so the home window reclaims the
  child once it's safely detached.
- **Detail dialogs outlived their parent** — `SiteCrawlDetailDialog`
  is an independent top-level `QDialog`, so closing the Site Crawl
  window left any open detail dialog fully visible with its worker
  still wired to the now-hidden parent. `closeEvent` now closes every
  tracked detail dialog first.
- **The status filter dropdown** was a fixed, curated list that was
  never exhaustive of every status the crawler can emit, with no
  other way to isolate one it didn't list. It's now rebuilt from the
  statuses actually present in the run's own distribution, for both a
  live crawl and a reopened past scan.
- **`render_js` / SSR parity** launched and tore down a fresh
  Chromium per crawled page instead of reusing one, the exact
  at-crawl-scale cost the shared `RenderPool` exists to avoid. Both
  now share one pool per crawl via `render_pool_scope()` in
  `site_crawler.py`; a crawl with neither enabled never starts the
  pool's worker thread.
- **A crawl store written by a newer schema** was silently stamped
  back to this build's `PRAGMA user_version`, downgrading its
  recorded schema. `crawl_store_schema.apply_schema()` now refuses
  with `NewerSchemaError` instead of touching the file.
- **Performance resource detail didn't survive reopening a past
  scan** — `heaviest_resources` / `third_party_hosts` were computed
  for a live audit but had no field on `PerformanceMetrics`, so a
  reopened stored run lost both tables. They're now persisted
  add-only (an old blob with neither key loads as `[]`).
- **`resolve_site_urls`** (`site_crawler.py`) was dead code — a
  public, tested function with zero production callers, superseded
  by the path `crawl_site()` actually uses. Removed, along with its
  `__all__` export and its own now-pointless tests.

### Settings and desktop polish

Four problems reported from real use of the 2.0.0 candidate.

#### Fixed
- **`run_silentfrog.bat`** ran the windowed exe inside its own
  console and then paused, so a cmd window stayed open for the whole
  session. It now starts the app detached and exits immediately; the
  developer `poetry run` fallback still keeps its console open.
- **Every dropdown lost its arrow** — styling `QComboBox::drop-down`
  suppressed the native arrow with no `::down-arrow` rule to replace
  it (a plain CSS triangle paints a solid block under the Windows Qt
  style), so e.g. the past-scans list on the Single Page URL box was
  invisible. Two small SVG assets now supply the arrow.
- **The Performance tab** reported third-party weight as a bare count
  and byte total. It now lists the heaviest individual resources and
  third-party hosts with sizes, and the issue text names the top
  offending hosts.
- **Semrush key / enable / max-calls settings never reached a
  crawl** — the API key was written to keyring inside a silent
  `except` (keyring is absent on a stock install), and the crawler
  gated only on an env var, so the Settings checkbox and "Max Semrush
  calls per day" spinbox had no effect. Enablement and max-calls now
  live in a pure `SemrushConfig` the crawler reads (env still wins
  when set); a missing keyring disables the API-key field with a
  tooltip naming the install command instead of silently discarding
  what was typed; Test connection no longer stores the key without
  an explicit OK.

### v2.0 feature waves (V1–V20)

The full v2.0 milestone catalogue, landed since the last changelog
entry (some already documented above under Install / update story or
Reachability fixes):

#### New
- **V1** Fetcher strategy — `fetchers/` package, 3-stage fallback
  (curl_cffi → stealth browser → aiohttp), optional `stealth` extra.
- **V2** Streaming SQLite crawl store (`crawl_store.py`) — zlib payload
  blobs, flat RAM, resumable, verified to 100k URLs.
- **V3** True hybrid spider crawl — `frontier.py` + `robots_matcher.py`,
  `CrawlMode` (sitemap/list/spider/hybrid, default hybrid), same-host
  link following instead of sitemap-only auditing.
- **V4** Concurrent Playwright render pool (`render_pool.py`) —
  long-lived browsers recycled every N pages.
- **V5** LLM-friendly export (`exporters/llm_export.py`) — compact
  Markdown + JSON with a self-describing prompt preamble.
- **V6** Custom CSS/XPath/regex extraction (`custom_extraction.py`,
  sandboxed, ≤10 rules) — rules configure via Settings; results show in
  Trust > Tech & extraction, the Excel exports and the AI export.
- **V7** GSC + GA4 integration (`integrations/google/`, system-browser
  OAuth, `keyring`) — see Reachability fixes above for the connect UI.
- **V8** Crawl comparison / diff view (`crawl_diff.py`), new Diff tab.
- **V9** Link graph + sitemap visualisation (`link_graph/`), sampled at
  scale, new Graph tab.
- **V10** Per-bot SSR rendering via the V4 pool, 19 checks, off by
  default.
- **V11** Per-agent ai.json + llms.txt parsing, per-bot llms.txt
  column.
- **V12** Common Crawl backlink harvest — dropped in favour of the V17
  Semrush integration; never built.
- **V13** Server log parser + crawl-budget audit (`log_analysis.py`).
- **V14** Lighthouse + Rich Results API checks
  (`integrations/google/`).
- **V15** Tech-stack detection (`tech_stack.py`, vendored
  wappalyzer.json) — opt-in; results show in Trust > Tech & extraction,
  the Excel exports and the AI export.
- **V16** Robots.txt simulator + hreflang depth
  (`robots_simulator.py`, `hreflang_validator.py`) — see Reachability
  fixes above for the simulator dialog.
- **V17** Semrush API integration (`integrations/semrush/`),
  keyring-stored key, per-user rate cap.
- **V18** Silentfrog MCP server — superseded by G6's hand-rolled
  `mcp_server.py` (`silentfrog-mcp serve` console script), no new
  deps.
- **V19** GUI redesign, Stage A — PyQtGraph charts + tab regroup.
  Stage B (QML) is out of scope for v2.0.
- **V20** Topic embeddings + brand-mention time-series
  (`embeddings/`, `brand_mentions/`), local sentence-transformers, no
  network calls for content.

### v3 gap-catalogue waves (G1–G15)

The full v3 gap-analysis catalogue (`docs/v3_roadmap.md`) also landed:

#### New
- **G1** Prioritized hints engine (`hints.py`) — severity + plain-
  English why/how-to-fix per finding, feeds the Site Crawl recap.
- **G2** Audit health score + per-issue trend history
  (`crawl_trends.py`) in the past-scans dialog.
- **G3** AI citation share-of-voice (`integrations/ai_engines/`) —
  opt-in, BYO-key sampling of ChatGPT/Perplexity/Gemini with
  mention/citation/sentiment scoring.
- **G4** Accessibility auditing (`accessibility_audit.py`, vendored
  axe-core 4.10.3) — opt-in flag, DEEP profile, new Accessibility tab.
- **G5** Topic map (`content_clusters.py`) — per-page embedding
  clustering (KMeans+PCA), cluster-scatter dialog.
- **G6** Silentfrog MCP server (`mcp_server.py`) — stdio JSON-RPC,
  zero new deps.
- **G7** Custom AI prompts over crawl data (`ai_review_providers.py`)
  — BYO-key Ollama/OpenAI/Anthropic, on-demand "AI review" button +
  `silentfrog-cli review`.
- **G8** Client-ready HTML report export
  (`exporters/html_report.py`) — self-contained inline-CSS HTML with
  SVG charts.
- **G9** Scheduled runs + alert digests — one-shot
  `silentfrog-cli crawl` + `alert_transport.py` (webhook/email),
  driven by the OS scheduler (Task Scheduler/cron), no daemon.
- **G10** llms.txt generator/validator
  (`exporters/llms_txt.py` + a conformance check).
- **G11** AI-agent log analytics — bot taxonomy widened to 48
  signatures (30 AI); CLI-only until R4 added the `log_gui.py` window
  above.
- **G12** "Blocked from AI Search" rollup — delivered via G1: AI-access
  issues flow into `build_hints`'s "AI crawler blocked" grouping; a
  separate AI-readiness score would duplicate the existing GEO Score
  and was deliberately not added.
- **G13** Semantic redirect mapping (`redirect_mapping.py`) —
  embedding + fallback matching of gone pages to migration candidates,
  feeds the existing Redirect checker.
- **G14** Uncrawlable-link detection — always-on `pseudo_links` payload
  group (onclick/span/div pseudo-links) + `links.uncrawlable` issue.
- **G15** Text-glitch detection — language-agnostic duplicate-word /
  doubled-punctuation checks (`content.text_glitches`).

### Redirect checker rewrite

- The bulk redirect checker now walks chains hop by hop instead of
  resolving them in one shot, keeps HTTP connections pooled across
  rows instead of reconnecting per URL, and has been tuned for speed
  while a run is in flight.

### Known limitations

- The in-app updater ("Check for Updates…") cannot install anything
  yet: no signed GitHub Release exists, and `PINNED_PUBLIC_KEY` is now
  empty (see Removed / archived above), so verification fails closed
  by design. See `docs/RELEASING.md` for the procedure once a real
  signing key exists.
- Server-log analysis got a GUI window in 2.0 (`log_gui.py`), but
  remote sync (M8, `remote_sync.py`) is still not wired to any
  caller — log files must be supplied locally.

## 1.0.0

- Massive redirect check from Excel input.
- Stable desktop SEO toolkit with single-page crawl (meta, headers, images with loading/fetchpriority, links, redirects, canonical, robots, hreflang, structured data, keywords, AI crawl, performance, SERP preview).
- Export to Excel per tab.
- Gentle crawl mode with presets and optional headers/cookies.
- Cross-platform theme fixes (dark/light), improved settings dialog, and macOS-friendly scrollbars.
- README, contributing, security policy, and issue/PR templates added.