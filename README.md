# Silentfrog - Desktop SEO Toolkit

Silentfrog is a **simple desktop SEO auditor** built with Python 3.11 / 3.12 and PyQt 5.

It lets you quickly:

| Capability                                                                  | Status |
| --------------------------------------------------------------------------- | ------ |
| Bulk-check redirects from Excel                                             | ✅     |
| Single-page SEO analyser (meta, headers, images, links, structured data, performance) | ✅     |
| Export results to Excel                                                     | ✅     |

---

## 1. Prerequisites

|            | Recommended   | Why                                                                 |
| ---------- | ------------- | ------------------------------------------------------------------- |
| **Python** | **3.11 or 3.12** | `extruct 0.16` is pinned to **lxml 4.x** (no wheel for Py 3.13 yet) |
| **Poetry** | >= 1.8        | Reproducible virtual environments                                   |
| **Git**    | any           | Clone updates                                                       |

> On **Windows** enable "Add Python to PATH" during install.  
> On **macOS** use Homebrew (`brew install python@3.12`).

---

## 2. Quick start (recommended: Poetry)

```bash
# clone
$ git clone https://github.com/your-org/silentfrog.git
$ cd silentfrog

# pick the right interpreter
$ poetry env use $(which python3.12)  # or python3.11

# install (pre-built wheels, no compile step; stopwords are bundled locally)
$ poetry install

# run tests
$ poetry run pytest

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
python3 -m pip install --upgrade pip
python3 -m pip install -e .
python3 -m silentfrog
```

Use Python 3.11 or 3.12; PyQt 5.15 wheels are available for those versions.

**macOS first-run notes**
- If `nltk.downloader` fails with `CERTIFICATE_VERIFY_FAILED`, run:  
  `open "/Applications/Python 3.12/Install Certificates.command"` and retry the stopwords download.
- Use `python3.12` (PyQt 5.15 has universal2 wheels); avoid 3.13 until lxml/extruct wheels land.

## Support & project status

- Silentfrog is Open source and currently developed by a single maintainer using GitHub + Codex-style tooling; there is **no commercial or priority support**.
- Use [GitHub issues](https://github.com/developeter/silentfrog/issues) for bugs, feature requests, or security reports. Everything is tracked publicly.
- Code is written from scratch for this project; if you suspect unintentional reuse, open an issue and it will be addressed.
- The `dev` branch reflects ongoing work, while `main` only contains tagged releases.

## Exporting reports

1. Run a page analysis with **Analyze**.
2. Click **Export Excel** and pick a filename (the `.xlsx` extension is appended if missing).
3. Each tab is exported to its own worksheet (Meta, Headers, Images, Links, Redirect, Canonical, Robots, Hreflang, AI crawl, Structured data, Performance, SERP preview/audit, Keywords, Keyword Alerts).
4. Re-run the export after a new crawl to refresh the workbook.

### Keyword analysis & fine tuning

Silentfrog extracts 1/2/3‑grams together with density, heading coverage, title/meta usage, and first-occurrence data. High-density terms are highlighted in the GUI, summarised at the top of the tab, and mirrored in the **Keyword Alerts** sheet inside the Excel export.

Power users can adjust the density warning threshold (default **4 %**) by setting an environment variable before launching the app:

```bash
# Flag density ≥ 6.5 %
export SILENTFROG_KEYWORD_WARN_DENSITY=6.5   # macOS / Linux (bash or zsh)
set SILENTFROG_KEYWORD_WARN_DENSITY=6.5      # Windows Command Prompt
```

Set the value back to blank (or `0`) to disable the warning altogether.

### Performance metrics & open-source guidance

The **Performance** tab (and the corresponding Excel worksheet) displays:

- navigation timings (HTTP status, Time To First Byte, total navigation time, transfer size);
- resource mix (per-type request counts and approximate weights for CSS, JS, images, fonts);
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
* **PyInstaller** – standalone bundles are deferred until the NLTK stopwords dependency is fully packaged; use `poetry run silentfrog` for now.

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

## 3. Running the test suite

```bash
poetry run pytest -q 
```

The first run downloads the NLTK stop-word corpus. If outbound traffic is blocked run:

```bash
poetry run python -m nltk.downloader stopwords
```

---

## 4. Folder layout

```
silentfrog/
├── pyproject.toml
├── README.md
├── docs/
│   └── tests/
│       ├── README.md
│       └── fixtures/
│           ├── example_page.html
│           ├── robots.txt
│           └── schema_product.json
├── src/silentfrog/
│   ├── gui.py            # Launcher / theme switcher
│   ├── seo_gui.py        # Single-page analysis window
│   ├── exporters/
│   │   └── excel.py      # Excel export helpers
│   ├── tabs/             # Per-tab Qt widgets
│   ├── models/           # Table models feeding tabs
│   ├── crawl_types.py    # Typed crawl payloads
│   ├── crawl_constants.py# Shared accept headers, stopwords, density threshold
│   ├── crawl_http.py     # Throttling, robots, backoff helpers
│   ├── parsers_meta.py   # Meta/headers/images/links/hreflang/canonical/SERP helpers
│   ├── schema_extractor.py # Structured data extraction and validators
│   ├── perf_metrics.py   # Resource/weight/opportunity calculation
│   ├── keywords.py       # Keyword tokenization and density analysis
│   ├── workers.py        # Thread helpers wrapping async tasks
│   └── seo_crawler.py    # Orchestrator wiring the modules above
├── tests/
│   ├── test_seo_gui.py
│   ├── test_seo_crawler.py
│   ├── test_export_excel.py
│   ├── test_keywords_unit.py
│   ├── test_schema_extractor_unit.py
│   ├── test_perf_metrics_unit.py
│   ├── test_crawl_http_unit.py
│   ├── ...
└── assets/
    └── icon.png
```

---

## 5. Packaging binaries (optional)

| OS      | Command                                    | Output                |
| ------- | ------------------------------------------ | --------------------- |
| Windows | `poetry run pyinstaller --name Silentfrog --add-data "src/silentfrog/assets;silentfrog/assets" --add-data "src/silentfrog/resources;silentfrog/resources" -w -m silentfrog.gui` | `dist/Silentfrog.exe` |

PyInstaller hints (not a full spec):
- Bundle package data: `silentfrog/assets` and `silentfrog/resources` so icons and stopwords ship with the app.
- Entry point: `silentfrog.gui:main` (or `python -m silentfrog`); sample command above uses `-m silentfrog.gui`.
- No runtime downloads: stopwords are bundled locally; code avoids writing outside the app directory.

---

## 6. Troubleshooting

| Symptom / log snippet                                                        | Root cause                    | Fix                                                                                                   |
| ---------------------------------------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------- |
| `ImportError: cannot import name '_ElementStringResult' from lxml.etree`     | lxml 5.x wheel + extruct 0.16 | Stick to Python 3.11/3.12 – wheel pulls **lxml 4.9.x** automatically, or `poetry add "lxml>=4.9,<5"` |
| **Poetry fails building lxml 4.9 on macOS**                                  | Using Python 3.13 (no wheels) | `brew install python@3.12 && poetry env use $(which python3.12)`                                      |
| GUI crashes when clicking **Analyze** and log shows `TypeError: list found` | Mixed schema row formats      | Upgrade to Silentfrog ≥ 0.1.3 (fix merged 2025-06-04)                                                 |
| `"Cannot load Qt platform plugin 'xcb'"` on Ubuntu                           | Missing Qt runtime libs       | `sudo apt install libxcb-xinerama0`                                                                   |

---

## 7. Compiling on Python 3.13 anyway (macOS / Linux)

```bash
brew install libxml2 libxslt libiconv            # C headers
poetry env use python3.13
poetry add "git+https://github.com/scrapinghub/extruct.git@master#egg=extruct"
poetry add "lxml>=5,<6"    # will build from source
poetry install --sync
```

---

> **Happy crawling!** 🐸 Bugs & PRs welcome.
