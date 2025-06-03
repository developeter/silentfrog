# Silentfrog – Desktop SEO Toolkit 🇬🇧
simple python seo web crawler

Silentfrog is a cross-platform desktop application (PyQt5) that helps SEO
specialists audit redirect maps and individual web pages.  
It is developed entirely in **Python 3.11+** with **Poetry** for reproducible
dependencies and **pytest** for tests.

| Feature                                                           | Status |
                                                     
| Mass-check redirects (XLSX in → styled XLSX out)                   ✔
| Web-page SEO analyser (meta, headers, images, links, schema …)     ✔ 
| Image deep-analysis (real WxH, weight, W/H ratio)                  ✔
| Export results to Excel                                            X (TBD) 
| Pause / resume tasks                                               ✔ 

---

## 1.  Prerequisites


| Python ≥ 3.11 | <https://www.python.org/downloads/windows/>       |
| Poetry ≥ 1.8  | `pip install poetry` **or** official installer    |
| Git           |   |

> **Python in PATH** – make sure `python --version` returns ≥ 3.11  
> On Windows you can enable “❑ Add Python to PATH” in the installer.

---

## 2.  Clone & install

```bash
# 1. Clone the repo (replace URL with your Git remote)
git clone https://github.com/your-org/silentfrog.git
cd silentfrog

# 2. Install dependencies in an isolated virtual-env
poetry install
````

Poetry will:

* create a venv under `%APPDATA%\pypoetry\` (Win) or `~/.cache/pypoetry/`
* install all runtime deps (PyQt5, aiohttp, pillow, humanize …)
* install all dev/test deps in the `--with dev` group

---

## 3.  First run

```bash
# Activate the venv & launch the GUI
poetry run silentfrog
```

* **Windows** – an **Installer prompt** (“Windows protected your PC”) may
  appear the very first time because the app is unsigned; click **More info → Run anyway**.
* **macOS** – if Gatekeeper blocks Qt, run
  `xattr -dr com.apple.quarantine silentfrog` once inside the repo.

---

## 4.  Running the test-suite

```bash
poetry run pytest -q     # 5 tests, all green
```

> The first run downloads NLTK stop-word corpora; if outbound traffic is
> blocked, run
> `python -m nltk.downloader stopwords` manually inside the venv.

---

## 5.  Updating / adding dependencies

```bash
poetry add <package>
poetry lock             # regenerate lockfile
```

Dev-only packages:

```bash
poetry add --group dev types-pillow types-humanize
```

---

## 6.  Packaging (optional)

| Target      | Command                                    | Output                |
| ----------- | ------------------------------------------ | --------------------- |
| Windows EXE | `poetry run pyinstaller silentfrog.spec`   | `dist/Silentfrog.exe` |
| macOS app   | `poetry run pyinstaller --windowed gui.py` | `dist/Silentfrog.app` |

> A pre-built **icon** is available in `src/silentfrog/assets/icon.*`
> feel free to replace it with your agency branding.

---

## 7.  Folder structure (tl;dr)

```
silentfrog/
├─ src/
│  └─ silentfrog/
│      ├─ gui.py            # Home window
│      ├─ redirect*.py      # Redirect checker engine + GUI
│      ├─ seo_crawler.py    # Async crawler
│      ├─ seo_gui.py        # SEO analyser GUI
│      └─ assets/
│          ├─ icon.png
│          └─ icon.ico
├─ tests/                   # pytest suite
└─ pyproject.toml           # Poetry config
```

---

## 8.  Common issues & fixes

| Symptom                                              | Fix                                                       |
| ---------------------------------------------------- | --------------------------------------------------------- |
| **“Cannot load Qt platform plugin”** on Ubuntu 22.04 | `sudo apt install libxcb-xinerama0`                       |
| NLTK `stopwords` missing                             | `poetry run python -m nltk.downloader stopwords`          |
| PyQt5 import error on M1 Mac                         | `brew install qt@5 && poetry add PyQt5-Qt5-macos==5.15.*` |

> Still stuck? Open an issue or ping `@your-name` on Slack.

---

Happy crawling! 🐸

```
