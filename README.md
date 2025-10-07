# Silentfrog – Desktop SEO Toolkit

Silentfrog is a **simple desktop SEO auditor** built with Python 3.11 + PyQt 5.

It lets quickly: 

| Capability                                                          | Status     |
| ------------------------------------------------------------------- | ---------- |
| Bulk‑check redirects from Excel                                     | ✅ Done     |
| Single‑page SEO analyser (meta, headers, images, links, Schema.org) | ✅ Done     |
| Export results to Excel                                           | 🚧 Planned |

---

## 1  Prerequisites

|            | Recommended      | Why                                                                 |
| ---------- | ---------------- | ------------------------------------------------------------------- |
| **Python** | **3.11 or 3.12** | `extruct 0.16` is pinned to **lxml 4.x** (no wheel for Py 3.13 yet) |
| **Poetry** | ≥ 1.8            | Reproducible virtual‑envs                                           |
| **Git**    | any              | Clone updates                                                       |

> On **Windows** enable “Add Python to PATH” during install.
> On **macOS** use Homebrew (`brew install python@3.12`).

---

## 2  Quick start

```bash
# clone
$ git clone https://github.com/your‑org/silentfrog.git
$ cd silentfrog

# pick the right interpreter
$ poetry env use $(which python3.12)    # or python3.11

# install (pre‑built wheels, no compile step)
$ poetry install --sync

# run tests
$ poetry run pytest

# launch GUI
$ poetry run silentfrog
```

### macOS first‑run issues

* **Gatekeeper** – if the window won’t open: `xattr -dr com.apple.quarantine silentfrog`
* **lxml build fails** with CPython 3.13 – use Python 3.12 **or** follow the manual‑compile instructions in § 8.

---

## 3  Running the test‑suite

```bash
poetry run pytest -q   # ~4 s, 100 % pass
```

The first run downloads NLTK stop‑word data. If outbound traffic is blocked run:

```bash
poetry run python -m nltk.downloader stopwords
```

---

## 4  Folder layout

```
silentfrog/
│  pyproject.toml
│  README.md
├─ src/silentfrog/
│    gui.py               # Home window + global theme switch
│    redirect*.py         # Redirect‑checker engine & GUI
│    seo_crawler.py       # Async crawler (aiohttp + extruct)
│    seo_gui.py           # Tabbed SEO analyser window
│    assets/              # App & tray icons
└─ tests/                 # pytest suite
```

---

## 5  Packaging binaries (optional)

| OS      | Command                                    | Output                |
| ------- | ------------------------------------------ | --------------------- |
| Windows | `poetry run pyinstaller silentfrog.spec`   | `dist/Silentfrog.exe` |
| macOS   | `poetry run pyinstaller --windowed gui.py` | `dist/Silentfrog.app` |

---

## 6  Troubleshooting

| Symptom / log snippet                                                        | Root cause                    | Fix                                                                                                   |
| ---------------------------------------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------- |
| `ImportError: cannot import name '_ElementStringResult' from lxml.etree`     | lxml 5.x wheel + extruct 0.16 | Stick to Python 3.11/3.12 → wheel pulls **lxml 4.9.x** automatically.  Or `poetry add "lxml>=4.9,<5"` |
| **Poetry fails building lxml 4.9 on macOS**                                  | Using Python 3.13 (no wheels) | `brew install python@3.12 && poetry env use $(which python3.12)`                                      |
| GUI crashes when clicking **Analizza** and log shows `TypeError: list found` | Mixed schema row formats      | Upgrade to Silentfrog ≥ 0.1.3 (fix merged 2025‑06‑04)                                                 |
| `“Cannot load Qt platform plugin 'xcb'”` on Ubuntu                           | Missing Qt runtime libs       | `sudo apt install libxcb‑xinerama0`                                                                   |

---

## 7 Compiling on Python 3.13 anyway (macOS / Linux)

```bash
brew install libxml2 libxslt libiconv            # C headers
poetry env use python3.13
poetry add "git+https://github.com/scrapinghub/extruct.git@master#egg=extruct"
poetry add "lxml>=5,<6"    # will build from source
poetry install --sync
```


---

> **Happy crawling!**🐸  Bugs & PRs welcome.
