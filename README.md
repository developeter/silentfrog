# Silentfrog - Desktop SEO Toolkit

Silentfrog is a **desktop SEO auditor** built with **Python 3.12** and **PyQt 5**.

It lets you quickly:

| Capability | Status |
| --- | --- |
| Bulk-check redirects from Excel | ✅ |
| Single-page SEO analysis (meta, headers, images, social, links, canonical, robots, hreflang, structured data, keywords, performance, SERP) | ✅ |
| Single-page AI / GEO support (AI crawl audit + AI Visibility heuristics) | ✅ |
| Export results to Excel | ✅ |

---

## 1. Prerequisites

|            | Recommended   | Why                                                                 |
| ---------- | ------------- | ------------------------------------------------------------------- |
| **Python** | **3.12**      | Matches `pyproject.toml` and the tested dependency set              |
| **Poetry** | >= 1.8        | Development workflow only                                           |
| **Git**    | any           | Clone updates                                                       |

> On **Windows** enable "Add Python to PATH" during install.  
> On **macOS** use Homebrew (`brew install python@3.12`).

---

## 2. One-command install (from source)

You only need **Python 3.12+** installed manually.

The installer will:

- create a local `.venv`
- upgrade `pip`, `setuptools`, and `wheel`
- install Silentfrog into that `.venv`
- refresh the launcher scripts
- create a Desktop launcher:
  - Windows: `Silentfrog.lnk`
  - macOS: `Silentfrog.command`

### Install

```bash
# Windows
py install_silentfrog.py

# macOS
python3 install_silentfrog.py
```

If Python is missing or too old, the installer stops with a clear message instead of failing later.

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

---

## 3. Quick start (recommended: Poetry for development)

```bash
# clone
$ git clone https://github.com/your-org/silentfrog.git
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

### Entry points (explicit)

- Preferred: `poetry run silentfrog`
- Alternative: `poetry run python -m silentfrog`

### Running without Poetry

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

Use Python 3.12; that is the tested baseline for this repository.

**macOS first-run notes**
- If `pip`/HTTPS certificate validation fails with the python.org installer build, run:  
  `open "/Applications/Python 3.12/Install Certificates.command"` and retry the install.
- Use `python3.12` (PyQt 5.15 has universal2 wheels); avoid 3.13 until lxml/extruct wheels land.

## Support & project status

- Silentfrog is Open source and currently developed by a single maintainer using GitHub + Codex-style tooling; there is **no commercial or priority support**.
- Use [GitHub issues](https://github.com/developeter/silentfrog/issues) for bugs, feature requests, or security reports. Everything is tracked publicly.
- Code is written from scratch for this project; if you suspect unintentional reuse, open an issue and it will be addressed.
- The `dev` branch reflects ongoing work, while `main` only contains tagged releases.

## Exporting reports

1. Run a page analysis with **Analyze**.
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

### Single-page analysis tabs

The **SEO webpage analysis** window currently includes these tabs:

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
* **Standalone bundles** – packaged binaries are not a supported release path right now; use the local source installer or run via Poetry.

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
├── install_silentfrog.sh
├── pyproject.toml
├── README.md
├── run_silentfrog.bat
├── run_silentfrog.sh
├── tools/
│   ├── source_install.py  # Local .venv installer and launcher generation
│   ├── doctor.py          # Env/dependency/resource/compile/test checks
│   └── install_hooks.py   # Configures git to use .githooks/
├── .githooks/
│   ├── pre-commit         # Runs doctor --quick automatically
│   └── pre-push           # Runs full doctor automatically
├── docs/
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
│   ├── gui.py            # Home launcher / theme switcher
│   ├── image_diagnostics.py # Shared image-table schema and diagnostics helpers
│   ├── indexability.py   # Indexability verdict helpers
│   ├── seo_gui.py        # Single-page analysis window
│   ├── exporters/
│   │   └── excel.py      # Excel export helpers
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
│   ├── resources/        # Bundled stopword lists
│   ├── assets/           # Bundled icons and UI assets
│   ├── settings_dialog.py # Crawl settings dialog
│   ├── theme.py          # Shared theme helpers
│   ├── workers.py        # Thread helpers wrapping async tasks
│   └── seo_crawler.py    # Orchestrator wiring the modules above
├── tests/
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

## 6. Packaging binaries (optional)

| OS      | Command                                    | Output                |
| ------- | ------------------------------------------ | --------------------- |
| Windows / macOS | Standalone packaging is currently not a supported release path; use `install_silentfrog.py` for a local `.venv` install or run `poetry run silentfrog` during development. | Local source install |

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
