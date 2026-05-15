# Silentfrog - Desktop SEO Toolkit

Silentfrog is a **desktop SEO auditor** built with **Python** and **Qt for Python**.

The current GUI runtime targets:

- **QtPy** as the abstraction layer
- **PySide6** as the primary Qt backend
- **PyQt5** only as an optional temporary transition fallback

It lets you quickly:

| Capability | Status |
| --- | --- |
| Bulk-check redirects from Excel | ✅ |
| Single Page SEO Check (meta, headers, images, social, links, canonical, robots, hreflang, structured data, keywords, performance, SERP) | ✅ |
| Site Crawl mode for sitemap/branch/URL-list audits | ✅ |
| Single-page AI / GEO support (AI crawl audit + AI Visibility heuristics) | ✅ |
| Export results to Excel | ✅ |

---

## 1. Prerequisites

|            | Recommended   | Why                                                                 |
| ---------- | ------------- | ------------------------------------------------------------------- |
| **Python** | **3.12**      | Current tested baseline for local development and the macOS source installer |
| **Poetry** | >= 1.8        | Development workflow only                                           |
| **Git**    | any           | Clone updates                                                       |

> On **Windows** enable "Add Python to PATH" during install.  
> On **macOS** use **Python 3.12** (`brew install python@3.12` or the python.org 3.12 installer). The installer path is not supported on Python 3.14 yet.

---

## 2. Packaged app path (recommended for end users)

This is the intended long-term install path for normal users.

The repository now includes:

- a packaging helper based on **`pyside6-deploy`**
- a GitHub Actions packaging workflow for **macOS** and **Windows**
- a Python compatibility workflow for **3.12 / 3.13 / 3.14**

If packaged release artifacts are available for your platform, use those first.

If you are working from source before packaged artifacts are published, use the fallback source installer in **Section 3**.

---

## 3. Source install (developers / advanced users)

This path is still supported, but it is no longer the preferred end-user story.

You only need Python installed manually:

- **Windows**: Python **3.12+**
- **macOS**: Python **3.12** for now

The installer will:

- create a local `.venv`
- upgrade `pip`, `setuptools`, and `wheel`
- install Silentfrog into that `.venv`
- refresh the launcher scripts
- default the GUI runtime to `QT_API=pyside6`
- create a Desktop launcher:
  - Windows: `Silentfrog.lnk`
  - macOS: `Silentfrog.command`

### Install

On macOS, the no-terminal source install path is:

1. Double-click `install_silentfrog.command`.
2. If macOS asks for confirmation, right-click it and choose **Open**.
3. The installer will look for Python 3.12, including the Intel Homebrew path `/usr/local/bin/python3.12`.

```bash
# Windows
py install_silentfrog.py

# macOS terminal fallback
./install_silentfrog.sh
```

If Python is missing, too old, or unsupported for the installer path, the installer stops with a clear message instead of failing later.

### Launch after install

```bash
# Windows
run_silentfrog.bat

# macOS
./run_silentfrog.sh
```

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

For Intel Macs using Homebrew, install the supported interpreter with:

```bash
brew install python@3.12
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

# pick the right interpreter
$ poetry env use $(which python3.12)

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

The project metadata now allows **Python 3.12 / 3.13 / 3.14** (`<3.15`) because the GUI runtime targets `PySide6 + QtPy`, but the tested local baseline remains **3.12** until the compatibility matrix stays green.

**macOS first-run notes**
- The supported installer path is **Python 3.12** on macOS. Do not use Python 3.14 for first-time installs yet.
- For one-click source install, use `install_silentfrog.command`. It detects `python3.12`, `/usr/local/bin/python3.12` on Intel Homebrew, `/opt/homebrew/bin/python3.12` on Apple Silicon Homebrew, and the python.org 3.12 framework path.
- If `pip`/HTTPS certificate validation fails with the python.org installer build, run:  
  `open "/Applications/Python 3.12/Install Certificates.command"` and retry the install.
- The packaged app path is the preferred way to avoid local Python/bootstrap issues on macOS.

## Support & project status

- Silentfrog is Open source and currently developed by a single maintainer using GitHub + Codex-style tooling; there is **no commercial or priority support**.
- Use [GitHub issues](https://github.com/developeter/silentfrog/issues) for bugs, feature requests, or security reports. Everything is tracked publicly.
- Code is written from scratch for this project; if you suspect unintentional reuse, open an issue and it will be addressed.
- The `dev` branch reflects ongoing work, while `main` only contains tagged releases.
- The runtime migration targets **QtPy + PySide6**. `PyQt5` remains available only as an optional fallback backend while the transition stabilizes.

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

The **Single Page SEO Check** window currently includes these tabs:

- `Meta tag`
- `Header H1-H6`
- `Images`
- `Social`
- `Link`
- `Redirect`
- `Canonical`
- `Indexability`
- `Robots`
- `Hreflang`
- `Structured data`
- `Content quality`
- `Keywords`
- `AI crawl`
- `AI Visibility`
- `Performance`
- `SERP`

### Site Crawl mode

The **Site Crawl** window audits multiple URLs without recursively following every link on the page.

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
- recursive link discovery: **off** in v1

Leaving the sitemap field empty lets Silentfrog auto-detect sitemaps from the base URL. If no sitemap yields URLs, Silentfrog falls back to auditing the base URL only.

The setup form and results table are separate screens. After **Start crawl**, the setup form is hidden and the results screen shows the discovered URL count, filters, table, export action, and crawl progress.

Completed Site Crawls are saved locally and can be opened from **View past scans**. The history browser lists saved runs by site/date, shows a summary and diff against the previous local run for the same site, and lets you export or delete selected local history files. This is local-only; it does not sync to Google Drive or any remote service.

Rows in the results table keep cached page payloads. Double-click a successful row to open the same detailed tab report used by the single-page checker, without re-crawling the URL. Detail windows also include **Analyze images** so image dimensions, size, type, and cache headers can be fetched for that page snapshot.

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
├── deploy/
│   └── main.py           # Packaging entrypoint for pyside6-deploy
├── tools/
│   ├── source_install.py  # Local .venv installer and launcher generation
│   ├── doctor.py          # Env/dependency/resource/compile/test checks
│   ├── code_shape_guard.py # AST-based complexity/nesting guard
│   ├── code_shape_baseline.json # Temporary allowlist for legacy exceptions (currently empty)
│   ├── install_hooks.py   # Configures git to use .githooks/
│   └── package_app.py     # Wrapper around pyside6-deploy
├── .githooks/
│   ├── pre-commit         # Runs doctor --quick automatically
│   └── pre-push           # Runs full doctor automatically
├── .github/
│   └── workflows/
│       ├── python-compat.yml # Windows/macOS compatibility matrix
│       └── package-app.yml   # Packaged app workflow
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
│   ├── gui.py             # Home launcher / theme switcher
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
│   ├── redirect.py       # Redirect export / parsing helpers
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
│   ├── test_package_app_unit.py
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

## 6. Packaging binaries (preferred release path)

| OS      | Command                                    | Output                |
| ------- | ------------------------------------------ | --------------------- |
| Windows / macOS | `poetry run python tools/package_app.py --mode standalone` | Packaged desktop artifact |

--- 

## 7. Troubleshooting

| Symptom / log snippet                                                        | Root cause                    | Fix                                                                                                   |
| ---------------------------------------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------- |
| `ImportError: cannot import name '_ElementStringResult' from lxml.etree`     | lxml 5.x wheel + extruct 0.16 | Stick to Python 3.11/3.12 – wheel pulls **lxml 4.9.x** automatically, or `poetry add "lxml>=4.9,<5"` |
| **Poetry fails building lxml 4.9 on macOS**                                  | Using Python 3.13 (no wheels) | `brew install python@3.12 && poetry env use $(which python3.12)`                                      |
| GUI crashes when clicking **Analyze** and log shows `TypeError: list found` | Mixed schema row formats      | Upgrade to Silentfrog ≥ 0.1.3 (fix merged 2025-06-04)                                                 |
| `"Cannot load Qt platform plugin 'xcb'"` on Ubuntu                           | Missing Qt runtime libs       | `sudo apt install libxcb-xinerama0`                                                                   |

---

## 8. Compiling on Python 3.13 anyway (macOS / Linux)

```bash
brew install libxml2 libxslt libiconv            # C headers
poetry env use python3.13
poetry add "git+https://github.com/scrapinghub/extruct.git@master#egg=extruct"
poetry add "lxml>=5,<6"    # will build from source
poetry install --sync
```

---

> **Happy crawling!** 🐸 Bugs & PRs welcome.
