# Silentfrog - Desktop SEO Toolkit

Silentfrog is a **desktop SEO auditor** built with **Python** and **Qt for Python**.

The current GUI runtime targets:

- **QtPy** as the abstraction layer
- **PySide6** as the primary Qt backend
- **PyQt5** only as an optional temporary transition fallback

It lets you quickly:

| Capability | Status |
| --- | --- |
| Bulk-check redirects from Excel or CSV (per-hop chain, loop and wrong-target detection) | ✅ |
| Single Page SEO Check (meta, headers, images, social, links, canonical, robots, hreflang, structured data, keywords, performance, SERP) | ✅ |
| Site Crawl mode for sitemap/branch/URL-list audits | ✅ |
| Single-page AI / GEO support (AI crawl audit + AI Visibility heuristics) | ✅ |
| Export results to Excel | ✅ |

---

## 1. Prerequisites

|            | Recommended   | Why                                                                 |
| ---------- | ------------- | ------------------------------------------------------------------- |
| **Python** | **3.12 / 3.13 / 3.14** | End users do not need to install Python manually — the one-click bootstrap (Section 2) installs Python 3.12 if missing. Developers running the source install need Python on PATH. |
| **Poetry** | >= 1.8        | Development workflow only                                           |
| **Git**    | any           | Developer workflow only — end users do not need git (the bootstrap downloads source via HTTPS) |

> On **Windows** enable "Add Python to PATH" during source installs.
> On **macOS** (Intel and Apple Silicon), the one-click bootstrap installs Python 3.12 from python.org if no supported version is present. Both architectures are supported by the same `Get-Silentfrog.command` script.

---

## 2. Quick install (one-click bootstrap, recommended for end users)

Each GitHub Release ships three small bootstrap scripts that handle
everything end-to-end: they install Python 3.12 if it's missing,
download the latest source, set up a local `.venv`, and create a
Desktop launcher. After install, updates are one click from inside the
app via **Help → Check for Updates…**.

Releases live on [GitHub Releases](https://github.com/developeter/silentfrog/releases).

### Install on Windows

1. Download both `Get-Silentfrog.bat` and `Get-Silentfrog.ps1` from the
   latest release into the same folder.
2. Double-click `Get-Silentfrog.bat`.
3. If Python isn't already installed, accept the UAC prompt from the
   silent Python installer (one click).
4. After ~1 minute, a Silentfrog shortcut appears on your Desktop.

Logs land at `%LOCALAPPDATA%\Silentfrog\bootstrap.log`.

### Install on macOS (Intel or Apple Silicon)

1. Download `Get-Silentfrog.command` from the latest release.
2. Right-click the file in Finder and choose **Open** (only the first
   time — Gatekeeper blocks unsigned `.command` files on double-click).
3. If Python isn't already installed, enter your password when prompted
   for the silent Python installer.
4. After ~1 minute, a Silentfrog launcher appears on your Desktop.

Logs land at `~/Library/Logs/Silentfrog-bootstrap.log`.

### Updating

Open Silentfrog and go to **Help → Check for Updates…**. The in-app
updater installs only a **signed GitHub Release**: it downloads that
release's `manifest.json` and `manifest.json.minisig`, verifies the
signature against the minisign public key pinned in
`src/silentfrog/update_trust.py`, checks the source archive's SHA-256
against the signed manifest, and only then offers **Apply and restart**.
Verification **fails closed** — a missing, unsigned, or tampered release
is refused and nothing is swapped. Updates target signed release tags,
never an unsigned `dev` commit. If a signed release cannot be retrieved,
no update is offered. **No key is pinned in 2.0.0**, so today this
always refuses — see *Releasing* below for how a maintainer signs a
release and pins the key that makes this active.

Developer clones (machines with a `.git` directory) see a "Use
`git pull` instead" message — the in-app updater never touches a working
tree under git control.

For maintainers: see *6. Releasing* below for the signing flow, and
`tools/update_silentfrog.py` for the executor the Apply button drives.

---

## 3. Source install (developers / advanced users)

> **For end users:** **[`docs/INSTALL.md`](docs/INSTALL.md)** documents this path as a step-by-step too, including troubleshooting for both macOS and Windows. The reference below stays in this README for developers.

This path is still supported, but it is no longer the preferred end-user story.

You only need Python installed manually:

- **Windows**: Python **3.12 / 3.13 / 3.14**
- **macOS**: Python **3.12 / 3.13 / 3.14**

The installer will:

- create a local `.venv`
- upgrade `pip`, `setuptools`, `wheel`, and `poetry-core`
- preinstall runtime dependencies from binary wheels
- install Silentfrog into that `.venv` without compiling dependency source packages
- refresh the launcher scripts
- default the GUI runtime to `QT_API=pyside6`
- create a Desktop launcher:
  - Windows: `Silentfrog.lnk`
  - macOS: `Silentfrog.command`

### Install

On macOS, the no-terminal source install path is:

1. Double-click `install_silentfrog.command`.
2. If macOS asks for confirmation, right-click it and choose **Open**.
3. The installer will look for Python 3.14, then 3.13, then 3.12, including Homebrew and python.org framework paths.

```bash
# Windows
py install_silentfrog.py

# macOS terminal fallback
./install_silentfrog.sh
```

If Python is missing, too old, too new, or dependency wheels are not available for your OS/CPU, the installer stops with a clear message instead of trying to compile desktop dependencies from source.

### Launch after install

```bash
# Windows
run_silentfrog.bat

# macOS
./run_silentfrog.sh
```

On Windows, `run_silentfrog.bat` starts the windowed app detached and its own
console window closes immediately — it does not stay open for the session.
(If no `.venv` is found yet, it falls back to `poetry run silentfrog` for
developers, which keeps its console open to show output.)

The installer also creates a Desktop launcher automatically:

- **Windows**: double-click `Silentfrog.lnk`
- **macOS**: double-click `Silentfrog.command`

Convenience wrappers are also available:

```bash
# Windows
install_silentfrog.bat

# macOS
./install_silentfrog.sh
```

For Intel Macs using Homebrew, install a supported interpreter with:

```bash
brew install python@3.14
```

If a previous macOS install failed, retry with a clean local environment:

- double-click `reinstall_silentfrog.command`, or
- run `./reinstall_silentfrog.sh` from Terminal.

This removes only Silentfrog's local `.venv` inside the project folder and rebuilds it. It does not delete scans, exports, or macOS system Python.

---

## 4. Developer setup (Poetry)

This section is for contributors and local development.

If you only want to run the app, prefer packaged artifacts from **Section 2**, or use the fallback source installer from **Section 3**.

```bash
# clone
$ git clone https://github.com/developeter/silentfrog.git
$ cd silentfrog

# pick a supported interpreter
$ poetry env use $(which python3.14)

# install (pre-built wheels, no compile step; stopwords are bundled locally)
$ poetry install

# run tests
$ poetry run pytest

# run doctor (env + compile + tests)
$ poetry run python tools/doctor.py

# launch GUI (preferred)
$ poetry run silentfrog
# or, from the project root:
$ poetry run python -m silentfrog
```

`doctor` also runs the repository **code-shape guard**, which blocks new deeply nested or branch-heavy functions. The baseline is intentionally kept empty after the latest cleanup, so new violations should be refactored instead of silently allowed.

### Entry points (explicit)

- Preferred: `poetry run silentfrog`
- Alternative: `poetry run python -m silentfrog`

### MCP server

`silentfrog-mcp serve` runs a local [Model Context Protocol](https://modelcontextprotocol.io/) server over stdio (JSON-RPC 2.0, newline-delimited) so AI clients such as Claude Desktop or Claude Code can drive Silentfrog audits directly. It exposes three tools:

- `audit_page` — audit one URL and return an LLM-ready Markdown + JSON summary (same formatter as `silentfrog-cli export`).
- `list_crawls` — list saved Site Crawl runs from local history.
- `get_crawl_summary` — counts, health score, top hints, and health-score trend for one saved run.

Every tool runs through the same TLS-verified / SSRF-guarded audit path as the GUI and CLI, and every optional integration (Google, Semrush, AI providers, stealth fetching, embeddings) stays off unless you've separately enabled it — the MCP server adds no new opt-in surface of its own.

Add it to Claude Desktop's config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "silentfrog": {
      "command": "silentfrog-mcp",
      "args": ["serve"]
    }
  }
}
```

Run `poetry run silentfrog-mcp serve` (or `silentfrog-mcp serve` from a source install) to start it manually and confirm it is on your `PATH`.

### Scheduled crawls & alerts

`silentfrog-cli crawl <base_url> [options]` runs one full Site Crawl, saves it to crawl history (the same history "View past scans" reads), and prints a change digest vs the previous run for that host. There is no bundled scheduler — per the repo's supply-chain policy (see `watch_mode.py`), scheduling is delegated to the OS: point Windows Task Scheduler or cron at the command and let it run on its own interval.

```bash
silentfrog-cli crawl https://example.com \
  --limit 500 --timeout 10 \
  --out-report report.html \
  --digest
```

Key options: `--sitemap URL`, `--url-list FILE` (one URL per line), `--limit N` (default 500), `--timeout N` (default 10 seconds), `--out-report PATH` (also writes the v3 G8 HTML report), `--digest` (send the digest via the configured transports below).

Every scheduled run is saved under the crawl's own on-disk SQLite store (`<data dir>/cli_crawls/`, newest 10 kept) and lands in crawl history exactly like a GUI-run crawl, so it appears in **View past scans** with a working "Open scan" button.

#### Alert delivery (`--digest`)

`--digest` is your consent to send; each transport additionally needs its own env config below, and an unconfigured transport is skipped silently (a note goes to stderr, exit code is unaffected).

| Env var | Purpose |
|---|---|
| `SILENTFROG_ALERT_WEBHOOK_URL` | POST the digest JSON to this URL (Slack/Teams/generic webhook receiver). |
| `SILENTFROG_SMTP_HOST` | SMTP server host — required to enable email. |
| `SILENTFROG_SMTP_PORT` | SMTP port (default `587`). |
| `SILENTFROG_SMTP_USER` | SMTP username (omit for an anonymous relay). |
| `SILENTFROG_SMTP_FROM` | From address. |
| `SILENTFROG_SMTP_TO` | `;`-separated recipient list. |
| `SILENTFROG_SMTP_PASSWORD` | SMTP password, env fallback (see keyring note). |

Keyring note: with the optional `keyring` package installed, store the SMTP password instead of a plaintext env var: `keyring.set_password("silentfrog-smtp", "password", "...")`. Password resolution tries keyring first, then falls back to `SILENTFROG_SMTP_PASSWORD`.

Windows Task Scheduler (daily at 03:00):

```bat
schtasks /create /tn "Silentfrog nightly crawl" /tr "C:\path\to\.venv\Scripts\silentfrog-cli.exe crawl https://example.com --digest" /sc daily /st 03:00
```

cron (daily at 03:00):

```cron
0 3 * * * /path/to/.venv/bin/silentfrog-cli crawl https://example.com --digest >> /var/log/silentfrog-crawl.log 2>&1
```

### Running without Poetry

This is a manual developer alternative. For normal end-user installation, prefer **Section 2**.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install .
.venv/bin/python -m silentfrog
```

On Windows the equivalent is:

```bash
py -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\python.exe -m silentfrog
```

The project metadata allows **Python 3.12 / 3.13 / 3.14** (`<3.15`) because the GUI runtime targets `PySide6 + QtPy`. Release support is CI-gated across Windows, macOS Intel, and macOS Apple Silicon.

**macOS first-run notes**
- For one-click source install, use `install_silentfrog.command`. It detects Python 3.14, 3.13, and 3.12 across Homebrew and python.org framework paths.
- If `pip`/HTTPS certificate validation fails with the python.org installer build, run:  
  `open "/Applications/Python 3.14/Install Certificates.command"` and retry the install. Adjust the version folder if you installed Python 3.13 or 3.12.
- For end users, the one-click `Get-Silentfrog.command` (Section 2) handles Python detection, install, and certificate setup automatically — no manual steps required.

## Support & project status

- Silentfrog is Open source and currently developed by a single maintainer; there is **no commercial or priority support**, no response-time SLA, and no bug-bounty program.
- Use [GitHub issues](https://github.com/developeter/silentfrog/issues) for bugs and feature requests (tracked publicly).
- **Security issues go through private reporting, not public issues** — see [`SECURITY.md`](SECURITY.md).
- Code is written from scratch for this project; if you suspect unintentional reuse, open an issue and it will be addressed.
- This is the **2.0.0** source tree, on `feature/v2.0`; `dev` holds the shipped v1.1 line. Tagging `v*` creates a **draft** GitHub Release carrying the bootstrap installers, so no published release exists yet — see *Releasing* below and `docs/RELEASING.md` for how a fully signed one is produced.
- The runtime migration targets **QtPy + PySide6**. `PyQt5` remains available only as an optional fallback backend while the transition stabilizes.

## Security & privacy

Silentfrog runs locally and crawls URLs you provide. The v2.0 hardening work set these defaults:

- **TLS verification is on by default** (certifi CA bundle, OpenSSL security level ≥ 2). Skipping certificate checks is an explicit, off-by-default per-crawl opt-in for trusted self-signed / intranet hosts.
- **SSRF protection is on by default**: crawled addresses that resolve to loopback, private, link-local, or reserved ranges are refused, the connection is pinned to the vetted IP, and redirects are re-validated. Reaching private/intranet hosts is an explicit, off-by-default opt-in.
- **Signed-update verification** — the in-app updater checks a minisign-signed release manifest against a public key pinned in `src/silentfrog/update_trust.py` (see *Updating*).
- **Known limitation:** no key is pinned in 2.0.0 (`PINNED_PUBLIC_KEY = ""`) — the previously pinned key had no known private counterpart, so it was removed rather than trusted. The updater therefore fails closed and refuses every update until a real keypair is generated and a release is signed; see `docs/RELEASING.md`.
- **Known limitation:** the first-time bootstrap installers download source over HTTPS but are **not yet signature-verified**; signature verification currently covers in-app updates only (see `bootstrap/README.md`).

Integrations (Google, Semrush, AI providers) are off by default and never run on a stock audit. Full policy: [`SECURITY.md`](SECURITY.md). See *Settings & optional features* below for how to turn each one on.

## Settings & optional features

Everything here is **off by default**. Open **Settings** from the gear icon on any window to enable it.

### Advanced tools

- **Stealth fetching** (Settings → *Advanced headers* group → "Stealth fetching (evade bot/WAF detection)") — routes requests through `curl_cffi` TLS impersonation and, if that still fails, a stealth headless browser that can solve a Cloudflare Turnstile challenge. Needs the `silentfrog[stealth]` extra; the checkbox is disabled with a tooltip explaining that when the extra isn't installed. Use it only against sites you're authorized to crawl.
- **Robots.txt simulator** (Settings → *Advanced headers* group → "Test a URL against robots.txt…") — opens a dialog that checks whether a given URL is allowed for a chosen user-agent, either against the live `robots.txt` (fetched through the same guarded, TLS/SSRF-checked path as a crawl) or against pasted robots.txt text.

### AI citation tracking

The AI Visibility check for cross-engine AI citations (`ai_citations.py`) is gated on environment variables rather than a Settings checkbox:

```bash
export SILENTFROG_AI_CITATIONS_ENABLE=1     # turns the check on at all
export SILENTFROG_BRAVE_API_KEY=<your key>  # optional: adds the Brave Search fresh-signal probe
```

Without `SILENTFROG_AI_CITATIONS_ENABLE=1` the check is skipped entirely (`info`, never a false warning). This is separate from the Settings → *"AI share of voice (BYO keys)"* group, which samples ChatGPT/Perplexity/Gemini directly with your own API keys.

### Google Search Console & Analytics 4 (bring your own credentials)

Silentfrog never ships or requests a shared Google client — you connect your own Google Cloud OAuth client, and only the *path* to your `client_secret.json` is stored (never its contents). To connect:

1. In [Google Cloud Console](https://console.cloud.google.com/), create (or reuse) a project, enable the **Search Console API** and **Google Analytics Data API**, and create an **OAuth client ID** of type **Desktop app**.
2. Download that client's `client_secret.json`.
3. In Silentfrog, open **Settings** and click **Connect Google…** (enabled once the `silentfrog[google]` extra is installed).
4. Browse to your `client_secret.json`, then click **Connect…** next to Search Console and/or Analytics 4 — each opens your system browser for a normal Google sign-in (RFC 8252 loopback flow; no embedded webview). Tokens are stored in the OS keychain via `keyring`.
5. Pick your property: the Search Console combo is editable (Search Console property strings must match exactly, e.g. `sc-domain:example.com` vs `https://example.com/`) and can be filled from **Refresh** (lists your verified sites), or typed by hand. Enter the GA4 property ID as free text.
6. Tick **"Use Google data in audits"** to actually pull real GSC impressions/clicks and GA4 engagement into audits — it starts unchecked, matching the app's default-off policy.
7. Click **Test connection** to confirm before running a real audit, then **Disconnect** any time to revoke local tokens (this does not revoke Google's own grant — do that at [myaccount.google.com/permissions](https://myaccount.google.com/permissions)).

If your Google Cloud OAuth consent screen is still in **Testing**, refresh tokens expire after **7 days** and the connection silently stops returning data — the dialog warns about this; set the consent screen to **In production** in Google Cloud Console to keep it working. For headless/CI use instead of the dialog, set `SILENTFROG_GOOGLE_ENABLE=1` plus `SILENTFROG_GSC_SITE_URL` / `SILENTFROG_GA4_PROPERTY_ID`.

## Server log analysis

The **Server Log Analysis** home-screen button opens a window over the same engine `silentfrog-cli logs` uses (`log_analysis.py`) — nothing is parsed twice, and GUI and CLI report identical counts for the same file.

1. **Load log file…** — accepts Common Log Format, Combined Log Format (with referer/user-agent), or JSON access logs (Apache/Nginx).
2. **Load known URLs (optional)…** — one URL per line; unlocks orphan-crawl and important-URL-not-hit findings. Skip it to get bot/status/crawl-budget findings only.
3. **Analyse** — runs the shared `log_analysis` findings model and lists issues in a results table (bot vs. human traffic, wasted 4xx/3xx, and 40+ classified AI-agent crawlers with vendor/kind).

Equivalent from the command line: `poetry run silentfrog-cli logs <access.log> [--base-url URL] [--known-urls FILE] [--out report.json]`. There is no remote/log-shipping integration — see *Known limitations* in `CHANGELOG.md` for the unwired `remote_sync.py` module.

## Exporting reports

1. Run a Single Page SEO Check with **Analyze**.
2. Click **Export Excel** and pick a filename (the `.xlsx` extension is appended if missing).
3. Silentfrog exports the current analysis into dedicated worksheets, including:
   - `Meta`
   - `Headers`
   - `Images`
   - `Social`
   - `Links`
   - `Redirect`
   - `Canonical`
   - `Indexability`
   - `Robots`
   - `Hreflang`
   - `AI crawl`
   - `AI Visibility`
   - `Structured summary`
   - `Structured eligibility`
   - `Structured data`
   - `Content quality`
   - `Keywords`
   - `Performance`
   - `SERP Preview`
   - `SERP Audit`
4. Re-run the export after a new crawl to refresh the workbook.

### Single Page SEO Check tabs

The **Single Page SEO Check** window groups its checks into a top-level
**Recap** (Overview) plus five user-goal buckets. Every individual tab is
still present — now nested under the bucket that matches its purpose:

- **Indexability** — `Indexability`, `Robots`, `Canonical`, `Redirect`, `Hreflang`, `Link`
- **Content** — `Meta tag`, `Header H1-H6`, `Images`, `Content quality`, `Keywords`
- **Speed** — `Performance`
- **Trust** — `Structured data`, `Social`, `SERP`, `Accessibility`
- **AI/GEO** — `Bot Matrix`, `AI Visibility`

The Site Crawl per-page detail view (double-click a result row) uses the same
bucketed layout.

The `Accessibility` tab (axe-core, WCAG 2.1/2.2) is opt-in: enable
"Accessibility audit (axe-core, WCAG)" under Settings → *GEO checks*
group. It
renders the page with headless Chromium and reports keyboard, contrast,
ARIA, and labeling violations, so it needs the `silentfrog[geo-render]`
extra (`playwright install chromium`) and a **Deep** audit profile —
disabled with an explanatory tooltip when Playwright isn't installed.
Results also feed the recap and the site-wide Excel export.

### Site Crawl mode

The **Site Crawl** window audits multiple URLs. By default (Auto mode, base URL only) it recursively follows same-host links via a hybrid sitemap+spider crawl; pass an explicit URL list or sitemap to audit only those URLs without following links.

Supported crawl sources:

- base URL, with automatic sitemap detection from `robots.txt` and common sitemap paths
- sitemap URL
- sitemap index URL
- pasted URL list
- include prefixes such as `/design/`, `/news/`, `/en/design/`
- exclude patterns such as `?store=`, `/privacy`, `/cookies`

Defaults are intentionally conservative:

- URL cap: **500**
- speed: **Gentle crawl**
- per-host concurrency: **2**
- robots crawl-delay: respected when available
- recursive link discovery: **on** by default when only a base URL is given (Hybrid mode); off when you supply an explicit URL list or sitemap

Leaving the sitemap field empty lets Silentfrog auto-detect sitemaps from the base URL. If no sitemap yields URLs, Silentfrog falls back to auditing the base URL only.

#### Site Crawl hardening (v2.0)

Recent v2.0 work hardened large-site crawling:

- **Storage:** production Site Crawls are SQLite-backed; results stream from the store rather than being held in RAM.
- **Audit profiles:** a **Lightweight / Standard / Deep** selector gates per-page *network* cost (extra HTTP probes, rendering, integrations) — local HTML parsing always runs. Site crawls default to **Standard**, single-page audits use **Deep**, and very large URL lists auto-suggest **Lightweight**.
- **Resume:** a crawl that is cancelled or interrupted can resume and re-run only the unfinished URLs (the SQLite frontier tracks per-URL state).
- **Results table:** sorting, filtering, and paging run in SQL against the store, so the GUI stays responsive on large runs.
- **Overview charts (optional):** with the optional `silentfrog[charts]` extra (PyQtGraph) installed, the results screen shows small HTTP-status, indexability, and GEO-score distribution charts once a crawl completes; without the extra the same figures render as a compact text summary. Chart data comes from read-only store aggregates, so it never re-materialises the crawl in RAM.
- **Link graph:** the **Link graph** button visualises the crawl tree (nodes coloured by GEO Score, edges from the page that first linked to each URL, orphan pages flagged). Large graphs are sampled to the most-central nodes; scroll to zoom, drag to pan, and use **Fit all** / **Reset zoom**.
- **Topic map:** the **Topic map** button (`content_clusters.py`) plots crawled pages as a content-cluster scatter — one dot per page, colour by topic cluster, position from stored topic-embedding vectors. Needs the opt-in "Topic embeddings (local model)" crawl setting, which requires the `silentfrog[embeddings]` extra (downloads a small sentence-transformers model locally on first use; no network calls for page content).
- **Map redirects:** the **Map redirects** button (`redirect_mapping.py`) is a site-migration helper — it suggests old→new URL redirects by matching pages that vanished or went 404/410 since the previous crawl against this crawl's indexable pages (topic-embedding similarity when both crawls have one, text/path matching otherwise), and exports the suggestions as a CSV you can feed straight into the Massive Redirect Check.
- **Generate llms.txt:** the **Generate llms.txt** button (`exporters/llms_txt.py`) drafts an [llms.txt](https://llmstxt.org) file from the crawl — a title, a summary, and H2 sections of links to the pages that were actually crawled and indexable. Review it before publishing; it's a starting draft, not a validated policy file. The same module also backs the `access_llms_txt_conformance` check, which flags a present-but-malformed `llms.txt` (an absent one stays silent).
- **Scale:** memory is measured against a synthetic gate up to **100k URLs**. **~1M-URL crawling is a future, post-gate goal — it is not a verified or supported production scale yet.**

The setup form and results table are separate screens. After **Start crawl**, the setup form is hidden and the results screen shows the discovered URL count, filters, table, export action, and crawl progress.

Completed Site Crawls are saved locally and can be opened from **View past scans**. The history browser lists saved runs by site/date, shows a summary and diff against the previous local run for the same site, and lets you export or delete selected local history files. This is local-only; it does not sync to Google Drive or any remote service.

Rows in the results table keep cached page payloads. Double-click a successful row to open the same detailed tab report used by the single-page checker (grouped into the same five buckets), without re-crawling the URL. Detail windows also include **Analyze images** so image dimensions, size, type, and cache headers can be fetched for that page snapshot.

Bulk export creates a workbook with high-level sheets:

- `Summary`
- `Indexability issues`
- `Meta issues`
- `Structured data`
- `Images`
- `AI Visibility`
- `Errors`

The same workbook also includes consolidated per-page detail sheets such as `Meta detail`, `Images detail`, `Links detail`, `Structured detail`, `AI Visibility detail`, `Performance detail`, and `SERP detail`. These sheets use `Page URL` as the first column so hundreds of pages remain filterable without creating one worksheet per URL.

For Cloudflare/WAF-protected sites, start slowly and use approved headers/cookies or allowlisting from the site owner when needed. Silentfrog does not impersonate verified bots or attempt to bypass protections.

### Keyword analysis & fine tuning

Silentfrog extracts 1/2/3‑grams together with density, heading coverage, title/meta usage, and first-occurrence data. High-density terms are highlighted in the GUI, summarised at the top of the tab, and exported in the **Keywords** worksheet.

Power users can adjust the density warning threshold (default **4 %**) by setting an environment variable before launching the app:

```bash
# Flag density ≥ 6.5 %
export SILENTFROG_KEYWORD_WARN_DENSITY=6.5   # macOS / Linux (bash or zsh)
set SILENTFROG_KEYWORD_WARN_DENSITY=6.5      # Windows Command Prompt
```

Set the value back to blank (or `0`) to disable the warning altogether.

### Performance-for-SEO metrics & open-source guidance

The **Performance** tab (and the corresponding Excel worksheet) displays:

- navigation timings (HTTP status, Time To First Byte, total navigation time, transfer size);
- a verdict (`Good`, `Needs work`, or `High performance risk`);
- resource mix (per-type request counts and approximate weights for HTML, CSS, JS, images, fonts, and other resources);
- SEO-relevant issue rows such as heavy page weight, blocking JavaScript, large image payloads, and third-party overhead;
- opportunity hints whenever payloads look heavy or script/stylesheet counts climb.

Silentfrog can also suggest **open-source learning resources** (HTTP Archive Web Almanac, Google's RAIL model, Web Vitals patterns). Toggle them with:

```bash
export SILENTFROG_PERF_GUIDES=0     # macOS / Linux
set SILENTFROG_PERF_GUIDES=0        # Windows CMD
```

Unset the variable (or set it to `1`) to re-enable the guidance.

### macOS first-run issues

* **Gatekeeper** – if the window will not open: `xattr -dr com.apple.quarantine silentfrog`
* **lxml build fails** with CPython 3.13 – use Python 3.12 **or** follow the manual-compile instructions in §7.
* **HTTPS fetch failures** after a python.org install – run `Install Certificates.command`, then retry.
* **Packaged apps** – if a packaged artifact is available for your platform, prefer it over manual source installation.

---

## Gentle crawl mode

Silentfrog includes a **gentle crawl mode** for fragile staging sites or whenever you need to behave politely.

### What it does

* Caps concurrent requests per host (default 4 when off, 2 when gentle mode is on).
* Respects `Crawl-delay` directives from `robots.txt`.
* Serialises link-status checks so you don’t hammer servers with HEAD requests.
* Retries politely on HTTP 403/429 with a short backoff.

### How to use it

1. Click **Crawl settings…** in the main window.
2. Tick **Enable gentle crawl mode** to switch on polite throttling.
3. Pick a preset or fine-tune:
   * **Standard** – fast crawl, gentle features off.
   * **Gentle** – safe defaults (2 parallel requests, retries on 403/429, crawl-delay respected).
   * **Custom** – enable gentle mode but customise the `Max parallel requests` spinner and optional headers/cookies.
4. Advanced users can supply headers (e.g. `Authorization: Bearer …`) or cookies; these are merged into every request while the crawl runs.

> Unchecking the box resets the preset to **Standard** (parallel = 4) so the UI always reflects the active profile.

---

## 4. Running the test suite

```bash
poetry run pytest -q 
```

For a full quality gate (environment checks + compile + tests), use:

```bash
poetry run python tools/doctor.py
```

For the faster local loop, use:

```bash
poetry run python tools/doctor.py --quick
```

Install automatic hooks once if you want tests to run on commit/push:

```bash
poetry run python tools/install_hooks.py
```

---

## 5. Folder layout

```
silentfrog/
├── AGENTS.md
├── install_silentfrog.py
├── install_silentfrog.bat
├── install_silentfrog.command
├── install_silentfrog.sh
├── pyproject.toml
├── README.md
├── reinstall_silentfrog.command
├── reinstall_silentfrog.sh
├── run_silentfrog.bat
├── run_silentfrog.sh
├── bootstrap/
│   ├── Get-Silentfrog.bat       # Windows double-click wrapper
│   ├── Get-Silentfrog.ps1       # Windows installer logic
│   ├── Get-Silentfrog.command   # macOS (Intel + Apple Silicon) installer
│   └── README.md
├── deploy/
│   └── main.py           # Source-installer entrypoint
├── tools/
│   ├── source_install.py     # Local .venv installer and launcher generation
│   ├── source_uninstall.py   # Cross-platform uninstaller
│   ├── source_update.py      # File-copy helpers for the in-app updater
│   ├── update_silentfrog.py  # In-app updater executor (driven by Help → Check for Updates)
│   ├── doctor.py             # Env/dependency/resource/compile/test checks
│   ├── code_shape_guard.py   # AST-based complexity/nesting guard
│   ├── code_shape_baseline.json # Temporary allowlist for legacy exceptions (currently empty)
│   └── install_hooks.py      # Configures git to use .githooks/
├── experimental/packaging/   # Archived Nuitka path (not used; kept for history)
├── .githooks/
│   ├── pre-commit         # Runs doctor --quick automatically
│   └── pre-push           # Runs full doctor automatically
├── .github/
│   └── workflows/
│       ├── python-compat.yml      # Windows/macOS compatibility matrix
│       └── release-bootstrap.yml  # Attaches bootstrap files to GitHub Releases
├── docs/
│   ├── site_crawl_feature_spec.md
│   ├── site_crawl_roadmap.md
│   └── tests/
│       ├── README.md
│       └── fixtures/
│           ├── example_page.html
│           ├── robots.txt
│           └── schema_product.json
├── src/silentfrog/
│   ├── __main__.py        # Enables `python -m silentfrog`
│   ├── ai_visibility.py   # AI Visibility heuristics and tooltip text
│   ├── content_quality.py # Content quality heuristics for single-page analysis
│   ├── crawl_options.py   # Typed crawl/gentle-mode settings
│   ├── crawler_api.py     # Public crawler-facing helpers
│   ├── crawler_utils.py   # Shared crawler utility helpers
│   ├── gui.py             # Home launcher, theme switcher, Help menu (Check for Updates, About)
│   ├── update_gui.py      # In-app updater + About dialogs
│   ├── updater.py         # Update-check domain logic (no Qt)
│   ├── image_diagnostics.py # Shared image-table schema and diagnostics helpers
│   ├── indexability.py   # Indexability verdict helpers
│   ├── seo_gui.py        # Single-page analysis window
│   ├── site_crawler.py   # Scoped sitemap/URL-list site crawler
│   ├── site_crawl_gui.py # Site Crawl window
│   ├── site_crawl_history_gui.py # Local Site Crawl history browser
│   ├── site_crawl_types.py # Typed Site Crawl config/results
│   ├── exporters/
│   │   ├── excel.py      # Single-page Excel export helpers
│   │   └── site_crawl_excel.py # Site Crawl Excel export helpers
│   ├── tabs.py           # Per-tab Qt widgets
│   ├── models/           # Table models feeding tabs
│   ├── crawl_types.py    # Typed crawl payloads
│   ├── crawl_constants.py# Shared accept headers, stopwords, density threshold
│   ├── crawl_http.py     # Throttling, robots, backoff helpers
│   ├── http_client.py    # Async page fetch wrapper
│   ├── parsers_meta.py   # Meta/headers/images/links/hreflang/canonical/SERP helpers
│   ├── perf_guides.py    # Optional open-source performance learning resources
│   ├── schema_extractor.py # Structured data extraction and validators
│   ├── perf_metrics.py   # Resource/weight/opportunity calculation
│   ├── keywords.py       # Keyword tokenization and density analysis
│   ├── redirect.py       # Bulk redirect chain walker (hops, loops, verdicts)
│   ├── redirect_gui.py   # Massive redirect check window
│   ├── nltk_data/        # Bundled tokenization/stopword resources
│   ├── resources/        # Bundled stopword lists
│   ├── assets/           # Bundled icons and UI assets
│   ├── settings_dialog.py # Crawl settings dialog
│   ├── theme.py          # Shared theme helpers
│   ├── workers.py        # Thread helpers wrapping async tasks
│   └── seo_crawler.py    # Orchestrator wiring the modules above
├── tests/
│   ├── conftest.py
│   ├── test_qt_runtime_smoke.py
│   ├── test_updater_unit.py
│   ├── test_update_gui.py
│   ├── test_update_silentfrog_unit.py
│   ├── test_source_update_unit.py
│   ├── test_ai_visibility_unit.py
│   ├── test_source_install_unit.py
│   ├── test_image_diagnostics_unit.py
│   ├── test_seo_gui.py
│   ├── test_seo_crawler.py
│   ├── test_export_excel.py
│   ├── test_keywords_unit.py
│   ├── test_schema_extractor_unit.py
│   ├── test_social_extract.py
│   ├── test_perf_metrics_unit.py
│   ├── test_crawl_http_unit.py
│   ├── ...
```

---

## 6. Releasing

The in-app updater only trusts a **signed** GitHub Release. The signing key is held offline by the maintainer and never enters CI or the repo; only the matching **public** key is pinned (`src/silentfrog/update_trust.py`). **No key is pinned as of 2.0.0** — see [`docs/RELEASING.md`](docs/RELEASING.md) for the exact keygen/manifest/signing procedure this table summarizes.

| Step | Command / action |
| --- | --- |
| Tag the release | `git tag v<version> && git push --tags` |
| CI attaches bootstrap files | `.github/workflows/release-bootstrap.yml` runs on the tag (or manually via **Actions → Run workflow**) and attaches `Get-Silentfrog.{ps1,bat,command}` to a Release — **draft** by default, overridable per-run from the manual `workflow_dispatch` input. |
| Sign the manifest (offline) | Build `manifest.json` (release tag + source/installer SHA-256) and sign it with the minisign private key, producing `manifest.json.minisig`. The private key never touches CI. |
| Attach signed assets | Add the source archive, `manifest.json`, and `manifest.json.minisig` to the draft Release. |
| Publish | Publish the Release. The in-app updater verifies it against the pinned key and offers the update. |
| End-user gets updates after install | **Help → Check for Updates…** inside Silentfrog. |

Until a release is signed and published, the updater fails closed (offers no update). The Nuitka packaging path has been retired; see `experimental/packaging/README.md` for the rationale.

---

## 7. Troubleshooting

| Symptom / log snippet                                                        | Root cause                    | Fix                                                                                                   |
| ---------------------------------------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------- |
| Source installer says `Dependency wheel preflight failed`                    | A dependency wheel is unavailable for that Python/OS/CPU combination | Try another supported Python version: 3.12, 3.13, or 3.14 |
| `pip` tries to compile Pillow/lxml/aiohttp from source                       | Dependency wheel was not selected | Use the source installer instead of manual `pip install`, because it enforces binary wheels |
| GUI crashes when clicking **Analyze** and log shows `TypeError: list found` | Mixed schema row formats      | Upgrade to Silentfrog ≥ 0.1.3 (fix merged 2025-06-04)                                                 |
| `"Cannot load Qt platform plugin 'xcb'"` on Ubuntu                           | Missing Qt runtime libs       | `sudo apt install libxcb-xinerama0`                                                                   |

---

> **Happy crawling!** 🐸 Bugs & PRs welcome.
