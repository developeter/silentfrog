# Get Silentfrog — one-click bootstrap installers

This directory contains the bootstrap scripts attached to each GitHub
Release. They are the recommended way for a teammate (or your own
second machine) to install Silentfrog without manually setting up
Python, virtual environments, or git.

## What the scripts do

Both scripts perform the same five steps:

1. Detect whether a supported Python (3.12 / 3.13 / 3.14) is already on
   the user's machine.
2. If not, download the official installer from python.org and run it
   silently (Windows: per-user, no admin; macOS: `sudo installer`, one
   password prompt).
3. Query the GitHub API for the latest commit on `dev` and download the
   matching source archive.
4. Extract it into the platform-appropriate install location
   (Windows: `%LOCALAPPDATA%\Silentfrog\app`, macOS: `~/Silentfrog/app`).
5. Run `install_silentfrog.py --revision <sha>`, which creates the
   `.venv`, drops a Desktop launcher, and records the revision so the
   in-app "Check for Updates" feature works.

A previous install is upgraded in place: the `.venv` is preserved when
possible, so a repeat run is fast.

## How to run

### Windows

Download both `Get-Silentfrog.bat` and `Get-Silentfrog.ps1` into the
same folder, then double-click `Get-Silentfrog.bat`. The `.bat` is a
thin wrapper that launches PowerShell with `-ExecutionPolicy Bypass`
just for the current process — your system policy is not changed.

Logs land in `%LOCALAPPDATA%\Silentfrog\bootstrap.log`.

### macOS (Intel and Apple Silicon)

Download `Get-Silentfrog.command` and double-click it in Finder. The
first time you run a downloaded `.command` file, macOS Gatekeeper may
warn that the developer is unverified: right-click the file once and
choose **Open** to bypass that warning.

If Finder opens the file in Visual Studio Code (or any other text
editor) instead of running it, see *Troubleshooting* below.

Logs land in `~/Library/Logs/Silentfrog-bootstrap.log`.

## After the install

- A "Silentfrog" launcher is added to the Desktop. Double-click it to
  start the app.
- Updates are one click from inside the app: **Help → Check for
  Updates…**.

## Troubleshooting

If the script reports an error and stops, open the log file mentioned
above and look at the last few lines. The most common causes are:

- **macOS: "permission denied" or "you don't have permission to open"
  when running the script.** Safari and Chrome sometimes strip the
  execute bit on download, and Gatekeeper may also attach a
  `com.apple.quarantine` extended attribute that blocks execution. Run
  the following one-liner in Terminal against the actual download
  path, then double-click again:

  ```
  chmod +x ~/Downloads/Get-Silentfrog.command && xattr -dr com.apple.quarantine ~/Downloads/Get-Silentfrog.command
  ```

  Replace `~/Downloads/` with the real folder if you moved the file.

- **macOS: double-clicking `Get-Silentfrog.command` opens it in Visual
  Studio Code (or another text editor) instead of running it.** This
  happens on developer machines where VS Code has grabbed the default
  file association for `.command`. Three ways to fix it:
    1. *One-time override*: right-click the file → **Open With** →
       **Terminal.app**. If Terminal is not in the submenu, choose
       **Other...** → set the popup to **All Applications** → pick
       `/System/Applications/Utilities/Terminal.app`.
    2. *Permanent fix*: right-click → **Get Info**. Under
       *Open with* pick **Terminal.app**, then click
       **Change All...** and confirm. Every future `.command`
       double-click on this Mac will open in Terminal.
    3. *Run from a shell*: `bash ~/Downloads/Get-Silentfrog.command`
       (typed command; defeats the one-click promise but unblocks
       you immediately).
- **No internet connection** during the Python or source download.
- **Corporate group policy** blocking the silent Python installer on
  Windows. In that case install Python manually from
  [python.org](https://www.python.org/downloads/) and rerun the
  bootstrap.
- **Disk full** — the install needs roughly 200 MB free.

For anything else, file an issue on the
[Silentfrog repo](https://github.com/developeter/silentfrog/issues)
and include the log file.
