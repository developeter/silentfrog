# Changelog

## 2.0.0

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
  sandboxed, ≤10 rules) — rules configure via Settings and results
  reach the LLM export; no dedicated results tab was built.
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
  wappalyzer.json), new tab.
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