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

- **macOS Sequoia (15.x): "<file> non è stato aperto" with only
  *Sposta nel cestino* / *Move to Trash* and *Fine* / *Done* buttons.**
  Apple removed the right-click → Open bypass in Sequoia. The new
  flow is:

  1. Close the dialog (*Fine* / *Done*).
  2. Open **System Settings → Privacy & Security**.
  3. Scroll down to the **Security** section near the bottom.
  4. Find the line *"Get-Silentfrog.command è stato bloccato perché
     non proviene da uno sviluppatore identificato"* (or English
     equivalent) and click **Apri comunque** / **Open Anyway**.
  5. Authenticate with your password or Touch ID.
  6. A new dialog appears with an **Apri** / **Open** button — click
     it. Terminal opens and the bootstrap runs.

  After this one-time approval, double-clicking the same file works
  without further prompts.

- **macOS (any version): "permission denied" or you'd rather skip
  Gatekeeper entirely.** Safari and Chrome sometimes strip the execute
  bit on download, and even when they don't, the quarantine attribute
  triggers Gatekeeper. Strip both at once. Open Terminal, type the
  first part of the command **with the trailing space**, then drag
  the `Get-Silentfrog.command` file from Finder onto the Terminal
  window (it pastes the full path), then press Return:

  ```
  chmod +x <drag file here>
  ```

  Then repeat for the quarantine attribute:

  ```
  xattr -dr com.apple.quarantine <drag file here>
  ```

  Or, if you know the full path (e.g. it's in `~/Downloads/`), paste
  this single line and hit Return:

  ```
  chmod +x ~/Downloads/Get-Silentfrog.command && xattr -dr com.apple.quarantine ~/Downloads/Get-Silentfrog.command
  ```

  Replace `~/Downloads/` with the real folder if you moved the file.

- **macOS: "fully bypass for testing".** A maintainer smoke-testing
  the bootstrap from a dev clone (not a real download) can launch the
  script directly without the Gatekeeper dance:

  ```
  bash <path to Get-Silentfrog.command>
  ```

  This loses the colleague-realistic Gatekeeper experience, so for
  a final test before sharing the script use one of the Open Anyway
  paths above.

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
