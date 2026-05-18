# Installing Silentfrog

Silentfrog is a desktop SEO crawler. There are two ways to install it: a **packaged app** (no Python required) or a **source installer** (needs Python on your machine). The packaged path is the recommended one for end users.

This document is end-user oriented. If you are a developer working on the codebase, see the project [`README.md`](../README.md) section 4 (Poetry) instead.

---

## A. Packaged app (recommended)

Each tagged release on [GitHub Releases](https://github.com/developeter/silentfrog/releases) ships three artifacts:

| File | Target |
| --- | --- |
| `Silentfrog-<version>-macos-arm64.dmg` | macOS Apple Silicon (M1, M2, M3, ...) |
| `Silentfrog-<version>-macos-intel.dmg` | macOS Intel |
| `Silentfrog-<version>-windows-x64.zip` | Windows 10 / 11 (64-bit) |

The bundles are currently **unsigned**, so macOS and Windows show a security warning the first time you launch the app. The workarounds below are standard and only required at first launch.

### macOS (Apple Silicon or Intel)

1. From the Releases page, download the `.dmg` matching your chip.
   - To check your chip: Apple menu → **About This Mac** → look at the line after "Chip" (Apple M1/M2/M3/... = Apple Silicon; Intel Core = Intel).
2. Double-click the `.dmg`. A window opens with `Silentfrog.app` and a shortcut to `Applications`.
3. Drag `Silentfrog.app` onto the `Applications` shortcut.
4. Eject the disk image (right-click → Eject) and delete the `.dmg`.
5. Open `Applications` in Finder.
6. **Right-click** `Silentfrog.app` → **Open**. A dialog says "Apple cannot check it for malicious software" → click **Open** again.
7. From now on you can launch Silentfrog like any other Mac app (Spotlight, Launchpad, dock).

If macOS refuses to open the app even after right-click → Open, run this in Terminal (one line):

```bash
xattr -dr com.apple.quarantine /Applications/Silentfrog.app
```

Then double-click the app again.

### Windows 10 / 11

1. From the Releases page, download `Silentfrog-<version>-windows-x64.zip`.
2. Open the file's properties (right-click the ZIP → **Properties**) and tick **Unblock** if you see the "This file came from another computer" warning, then **Apply**.
3. Right-click the ZIP → **Extract All...** → pick a destination (e.g. `C:\Users\<you>\AppData\Local\Silentfrog`). Avoid `C:\Program Files\` unless you are an administrator.
4. Open the extracted `Silentfrog\` folder. Double-click `Silentfrog.exe`.
5. SmartScreen may say "Windows protected your PC". Click **More info** → **Run anyway**.
6. The app opens. Optionally right-click `Silentfrog.exe` → **Pin to Start** or **Create shortcut**.

### Uninstalling the packaged app

- **macOS**: drag `Silentfrog.app` from `Applications` to the Trash. Local crawl history (in `~/Library/Application Support/Silentfrog`) is left behind on purpose — delete that folder too if you want a full reset.
- **Windows**: delete the folder you extracted the ZIP into. Local crawl history (in `%LOCALAPPDATA%\Silentfrog`) is left behind — delete that folder too if you want a full reset.

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
