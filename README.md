# Silentfrog - Desktop SEO Toolkit

Silentfrog is a **simple desktop SEO auditor** built with Python 3.11 + PyQt 5.

It lets quickly: 

| Capability                                                          | Status |
| ------------------------------------------------------------------- | ------ |
| Bulk-check redirects from Excel                                     | ✅     |
| Single-page SEO analyser (meta, headers, images, links, Structured data) | ✅     |
| Export results to Excel                                             | ✅     |

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

## 2. Quick start

```bash
# clone
$ git clone https://github.com/your-org/silentfrog.git
$ cd silentfrog

# pick the right interpreter
$ poetry env use $(which python3.12)  # or python3.11

# install (pre-built wheels, no compile step)
$ poetry install --sync

# run tests
$ poetry run pytest

# launch GUI
$ poetry run silentfrog
```

## Exporting reports

1. Run a page analysis with `Analizza`.
2. Click `Esporta Excel` and pick a filename and destination folder (the `.xlsx` extension is appended if missing).
3. Each tab is exported to its own worksheet (Meta, Headers, Images, Links, Redirect, Canonical, Robots, Hreflang, AI crawl, Schema, SERP preview/audit, Keywords).
4. Re-run the export any time after a new crawl to refresh the workbook.


### macOS first-run issues

* **Gatekeeper** - if the window won't open: `xattr -dr com.apple.quarantine silentfrog`
* **lxml build fails** with CPython 3.13 - use Python 3.12 **or** follow the manual-compile instructions in § 8.

---

## 3. Running the test suite

```bash
poetry run pytest -q  # ~4 s, 100 % pass
```

The first run downloads NLTK stop-word data. If outbound traffic is blocked run:

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
│   ├── gui.py              # Launcher / theme switcher
│   ├── seo_gui.py          # Single-page analysis window
│   ├── exporters/
│   │   └── excel.py        # Excel export helpers
│   ├── tabs/               # Per-tab Qt widgets
│   ├── models/             # Table models feeding tabs
│   ├── crawl_types.py      # Typed crawl payloads
│   ├── workers.py          # Thread helpers wrapping async tasks
│   └── seo_crawler.py      # Async crawler (aiohttp + BeautifulSoup)
├── tests/
│   ├── test_seo_gui.py
│   ├── test_seo_crawler.py
│   ├── test_export_excel.py
│   └── ...
└── assets/
    └── icon.png
```
---

## 5. Packaging binaries (optional)

| OS      | Command                                    | Output                |
| ------- | ------------------------------------------ | --------------------- |
| Windows | `poetry run pyinstaller silentfrog.spec`   | `dist/Silentfrog.exe` |
| macOS   | `poetry run pyinstaller --windowed gui.py` | `dist/Silentfrog.app` |

---

## 6. Troubleshooting

| Symptom / log snippet                                                        | Root cause                    | Fix                                                                                                   |
| ---------------------------------------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------- |
| `ImportError: cannot import name '_ElementStringResult' from lxml.etree`     | lxml 5.x wheel + extruct 0.16 | Stick to Python 3.11/3.12 → wheel pulls **lxml 4.9.x** automatically, or `poetry add "lxml>=4.9,<5"` |
| **Poetry fails building lxml 4.9 on macOS**                                  | Using Python 3.13 (no wheels) | `brew install python@3.12 && poetry env use $(which python3.12)`                                      |
| GUI crashes when clicking **Analizza** and log shows `TypeError: list found` | Mixed schema row formats      | Upgrade to Silentfrog ≥ 0.1.3 (fix merged 2025-06-04)                                                 |
| `“Cannot load Qt platform plugin 'xcb'”` on Ubuntu                           | Missing Qt runtime libs       | `sudo apt install libxcb-xinerama0`                                                                   |

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

