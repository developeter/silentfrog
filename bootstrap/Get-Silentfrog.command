#!/usr/bin/env bash
# One-click installer for Silentfrog on macOS (Intel + Apple Silicon).
#
# Detects whether python3.12 / 3.13 / 3.14 is on PATH. If not, downloads
# the official universal2 .pkg from python.org and installs it via
# `sudo installer` (one password prompt). Then downloads the latest
# published v* Silentfrog release from GitHub (falling back to the dev
# branch's head commit while no release has been published yet), places
# it under ~/Silentfrog/app, and runs install_silentfrog.py so the user
# ends up with a working .venv plus a Silentfrog launcher on the Desktop.
#
# All actions are logged to ~/Library/Logs/Silentfrog-bootstrap.log.

set -euo pipefail

OWNER="developeter"
REPO="silentfrog"
BRANCH="dev"
PYTHON_PKG_URL="https://www.python.org/ftp/python/3.12.7/python-3.12.7-macos11.pkg"

INSTALL_ROOT="$HOME/Silentfrog"
APP_DIR="$INSTALL_ROOT/app"
LOG_DIR="$HOME/Library/Logs"
LOG_FILE="$LOG_DIR/Silentfrog-bootstrap.log"
STAGING="$(mktemp -d -t silentfrog-bootstrap)"

# Best-effort cleanup of the staging dir even on failure.
trap 'rm -rf "$STAGING"' EXIT

mkdir -p "$INSTALL_ROOT" "$LOG_DIR"

log() {
    # Send progress lines to stderr so command substitutions like
    # `sha="$(get_latest_sha ...)"` capture only the function's real return
    # value, not the log noise.
    printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*" | tee -a "$LOG_FILE" >&2
}

fail() {
    log "ERROR: $*"
    printf '\nBootstrap failed. See %s for details.\n' "$LOG_FILE"
    read -r -p "Press Return to close..." _
    exit 1
}

find_python() {
    for v in 3.14 3.13 3.12; do
        if command -v "python$v" >/dev/null 2>&1; then
            printf 'python%s' "$v"
            return 0
        fi
    done
    return 1
}

install_python() {
    local pkg="$STAGING/python-installer.pkg"
    log "Downloading Python installer from $PYTHON_PKG_URL"
    curl -fsSL -o "$pkg" "$PYTHON_PKG_URL"
    log "Installing Python (sudo will prompt for your password)"
    sudo installer -pkg "$pkg" -target /
    log "Python installed"
}

get_latest_release_tag() {
    # Tracks published (non-draft) releases: /releases/latest never
    # returns a draft, so this prints nothing until a release is actually
    # published -- matching what the in-app updater itself polls
    # (src/silentfrog/updater.py::fetch_remote_revision).
    local python_cmd="$1"
    local url="https://api.github.com/repos/$OWNER/$REPO/releases/latest"
    log "Querying $url"
    local response
    if ! response="$(curl -fsSL -H "Accept: application/vnd.github+json" "$url")"; then
        return 1
    fi
    printf '%s' "$response" | "$python_cmd" -c "import sys, json; print(json.load(sys.stdin).get('tag_name') or '')"
}

get_latest_sha() {
    local python_cmd="$1"
    local url="https://api.github.com/repos/$OWNER/$REPO/commits/$BRANCH"
    log "Querying $url"
    curl -fsSL -H "Accept: application/vnd.github+json" "$url" \
        | "$python_cmd" -c "import sys, json; print(json.load(sys.stdin)['sha'])"
}

get_target_revision() {
    # Prefer the latest published v* release; fall back to the dev
    # branch's head commit only while no release exists yet. Without this
    # fallback, a fresh install has nothing to download until the first
    # release is published.
    local python_cmd="$1"
    local tag
    if tag="$(get_latest_release_tag "$python_cmd")" && [ -n "$tag" ]; then
        log "Tracking latest published release: $tag"
        printf '%s' "$tag"
        return 0
    fi
    log "No published release yet; falling back to the '$BRANCH' branch"
    get_latest_sha "$python_cmd"
}

download_archive() {
    local revision="$1"
    local archive="$STAGING/source.zip"
    local url="https://github.com/$OWNER/$REPO/archive/$revision.zip"
    log "Downloading source archive from $url"
    curl -fsSL -o "$archive" "$url"
    printf '%s' "$archive"
}

extract_archive() {
    local archive="$1"
    local extracted="$STAGING/extracted"
    rm -rf "$extracted"
    mkdir -p "$extracted"
    unzip -q "$archive" -d "$extracted"
    local inner
    inner="$(find "$extracted" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
    [ -n "$inner" ] || fail "Archive did not contain a top-level directory"
    printf '%s' "$inner"
}

sync_app_directory() {
    local source_dir="$1"
    log "Syncing source tree into $APP_DIR (preserving .venv)"
    mkdir -p "$APP_DIR"
    # Wipe everything except .venv so install_silentfrog.py can reuse it.
    find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name ".venv" -exec rm -rf {} +
    # Copy with -a to preserve mtimes / permissions; "/." trick copies
    # contents rather than the source directory itself.
    cp -a "$source_dir/." "$APP_DIR/"
}

invoke_installer() {
    local python_cmd="$1"
    local revision="$2"
    log "Running install_silentfrog.py with --revision $revision"
    (
        cd "$APP_DIR"
        "$python_cmd" install_silentfrog.py --revision "$revision"
    )
    log "Installer finished"
}

main() {
    log "Silentfrog bootstrap starting; target install at $APP_DIR"
    local python_cmd
    if ! python_cmd="$(find_python)"; then
        log "No supported Python found; installing"
        install_python
        if ! python_cmd="$(find_python)"; then
            fail "Python installed but no python3.12/3.13/3.14 on PATH. Open a new shell and rerun."
        fi
    fi
    log "Using $python_cmd"

    local revision
    revision="$(get_target_revision "$python_cmd")"
    log "Target revision: $revision"

    local archive
    archive="$(download_archive "$revision")"
    local source_dir
    source_dir="$(extract_archive "$archive")"
    sync_app_directory "$source_dir"
    invoke_installer "$python_cmd" "$revision"

    log "Silentfrog bootstrap complete"
    printf '\nSilentfrog installed. Look for the Silentfrog launcher on your Desktop.\n'
    printf 'If anything went wrong, see %s.\n' "$LOG_FILE"
    read -r -p "Press Return to close..." _
}

main "$@"
