# Installing Silentfrog

Silentfrog is a desktop SEO crawler. There are two ways to install it:
a **one-click bootstrap** (recommended — installs Python for you if
needed) or a **manual source installer** (you bring your own Python).

This document is end-user oriented. If you are a developer working on
the codebase, see the project [`README.md`](../README.md) section 4
(Poetry) instead.

---

## A. One-click bootstrap (recommended)

Each tagged release on [GitHub Releases](https://github.com/developeter/silentfrog/releases) ships three bootstrap files:

| File | Target |
| --- | --- |
| `Get-Silentfrog.bat` + `Get-Silentfrog.ps1` | Windows 10 / 11 (64-bit) |
| `Get-Silentfrog.command` | macOS (Intel and Apple Silicon) |

Each script does the same thing end-to-end: detects whether a supported
Python is already installed, downloads it silently from python.org if
not, fetches the latest Silentfrog source, sets up a local `.venv`,
and drops a Desktop launcher.

After the first install, updates happen from inside the app via
**Help → Check for Updates…** — no need to download bootstrap files
again.

### macOS (Apple Silicon or Intel)

1. From the Releases page, download `Get-Silentfrog.command`.
2. Open Finder, navigate to your Downloads folder, and **right-click**
   `Get-Silentfrog.command` → **Open**. macOS shows a dialog
   ("Apple cannot check it for malicious software") — click **Open**.
   You only need to do this the first time.
3. A Terminal window appears with progress output.
4. If Python isn't installed yet, macOS prompts for your password to
   run the silent Python installer (one prompt, ~30 seconds).
5. After ~1 minute total, a `Silentfrog` launcher appears on your
   Desktop. Double-click it to start the app.

Logs land at `~/Library/Logs/Silentfrog-bootstrap.log`.

### Windows 10 / 11

1. From the Releases page, download **both** `Get-Silentfrog.bat` and
   `Get-Silentfrog.ps1` into the same folder (Downloads is fine).
2. Double-click `Get-Silentfrog.bat`.
3. A console window appears with progress output.
4. If Python isn't installed yet, accept the UAC prompt from the
   silent Python installer (one click, ~30 seconds).
5. After ~1 minute total, a Silentfrog shortcut appears on your
   Desktop. Double-click it to start the app.

Logs land at `%LOCALAPPDATA%\Silentfrog\bootstrap.log`.

### Uninstalling

The repo ships a cross-platform uninstaller. Run it from the install
directory:

- **macOS**: `~/Silentfrog/app/uninstall_silentfrog.sh` (or
  double-click `~/Silentfrog/app/uninstall_silentfrog.command`)
- **Windows**: `%LOCALAPPDATA%\Silentfrog\app\uninstall_silentfrog.bat`

By default the uninstaller preserves your local crawl history. Pass
`--purge` to wipe everything including history.

---

## B. Source installer (developers, fallback)

Use this path if a packaged release is not yet available for your platform, or if you want a Python-driven `.venv` instead of a self-contained app.

### Prerequisites

- Python **3.12**, **3.13**, or **3.14**.
- Git (only if cloning; you can also download a ZIP of the repo).
- About 1 GB of free disk space (`.venv` + PySide6 wheels).
- Internet access on first run (the installer downloads runtime dependencies from PyPI as binary wheels — no compilers needed).

### macOS

1. Install Python from [python.org/downloads](https://www.python.org/downloads/) or via Homebrew (`brew install python@3.12`).
2. Open Terminal, clone or download the repo, then `cd` into it:

   ```bash
   git clone https://github.com/developeter/silentfrog.git
   cd silentfrog
   ```

3. Run the one-click installer. Two equivalent ways:

   **Double-click flow** (no Terminal once cloned): in Finder, double-click `install_silentfrog.command`. If macOS refuses, right-click → **Open**.

   **Terminal flow**:

   ```bash
   ./install_silentfrog.sh
   ```

4. The installer:
   - finds your Python (tries 3.14, then 3.13, then 3.12 — including Homebrew and python.org framework paths);
   - creates a local `.venv` inside the repo;
   - installs Silentfrog from binary wheels;
   - on python.org Python: auto-runs `Install Certificates.command` so HTTPS fetches work later;
   - places a `Silentfrog.command` launcher on your Desktop.

5. Launch Silentfrog any of three ways:
   - Double-click `Silentfrog.command` on your Desktop.
   - From the repo: `./run_silentfrog.sh`
   - From the repo: `./.venv/bin/silentfrog`

### Windows 10 / 11

1. Install Python from [python.org/downloads](https://www.python.org/downloads/). During install, tick **Add python.exe to PATH**.
2. Clone or download the repo:

   ```cmd
   git clone https://github.com/developeter/silentfrog.git
   cd silentfrog
   ```

3. Run the installer. Two equivalent ways:

   **Double-click flow**: in File Explorer, double-click `install_silentfrog.bat`.

   **Command Prompt flow**:

   ```cmd
   py install_silentfrog.py
   ```

4. The installer:
   - validates that Python is 3.12, 3.13, or 3.14;
   - creates a local `.venv` inside the repo;
   - installs Silentfrog from binary wheels;
   - creates `Silentfrog.lnk` on your Desktop.

5. Launch Silentfrog any of three ways:
   - Double-click `Silentfrog.lnk` on your Desktop.
   - From the repo: `run_silentfrog.bat`
   - From the repo: `.venv\Scripts\silentfrog.exe`

### Reinstalling / wiping the local .venv

If something looks wrong with the installed environment, recreate it from scratch:

- macOS: `./reinstall_silentfrog.sh` (or double-click `reinstall_silentfrog.command`)
- Windows: `py install_silentfrog.py --recreate-venv`

### Uninstalling the source install

The repo ships a cross-platform uninstaller:

- macOS: `./uninstall_silentfrog.sh` (or double-click `uninstall_silentfrog.command`)
- Windows: `uninstall_silentfrog.bat`

By default the uninstaller removes:

- `.venv/` inside the repo;
- the Desktop launcher (`Silentfrog.command` or `Silentfrog.lnk`);
- all generated launcher scripts at the repo root (`run_*`, `install_*`, `reinstall_*`, `uninstall_*` except the one currently running).

Your **local crawl history is preserved** (`~/Library/Application Support/Silentfrog` on macOS, `%LOCALAPPDATA%\Silentfrog` on Windows). To also remove it, add `--purge`:

```bash
./uninstall_silentfrog.sh --purge    # macOS
uninstall_silentfrog.bat --purge     # Windows
```

The uninstaller never touches the shared `~/nltk_data` cache (used by other NLTK projects on your machine).

---

## Troubleshooting

### macOS

- **"Silentfrog can't be opened because Apple cannot check it..."** → first-launch Gatekeeper. Right-click the app → Open, then Open again. Or run `xattr -dr com.apple.quarantine /Applications/Silentfrog.app`.
- **"Python was not found"** when running `install_silentfrog.sh` → install Python 3.12/3.13/3.14 from python.org or Homebrew, then retry.
- **HTTPS fetch errors after a python.org install** → the installer normally handles this. If it slipped through: `open "/Applications/Python 3.12/Install Certificates.command"` (adjust version number).

### Windows

- **"Python is not recognized..."** → reinstall Python from python.org with **Add to PATH** ticked, or run `py install_silentfrog.py` instead of `python install_silentfrog.py`.
- **SmartScreen blocks Silentfrog.exe** → click **More info** → **Run anyway**. This is normal for unsigned apps.
- **`run_silentfrog.bat` flashes and disappears** → run it from an open Command Prompt to see the error. Most often `.venv` was not created yet — re-run the installer.

### Both platforms

- **"Silentfrog requires binary wheels..."** → your Python version is not supported (currently 3.12 / 3.13 / 3.14) or your CPU is unusual (32-bit, etc.). Install one of the supported Python versions and retry.
- **The Desktop launcher does not appear** → the installer is best-effort about Desktop files. You can launch via `run_silentfrog.sh` / `run_silentfrog.bat` from the repo, the app works identically.

---

## Getting help

- Bugs / feature requests: [GitHub issues](https://github.com/developeter/silentfrog/issues).
- Security reports: see [`SECURITY.md`](../SECURITY.md).
- Project status: see [`README.md`](../README.md) "Support & project status".
