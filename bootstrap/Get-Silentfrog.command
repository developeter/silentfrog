#!/usr/bin/env bash
# One-click installer for Silentfrog on macOS (Intel + Apple Silicon).
#
# Detects whether python3.12 / 3.13 / 3.14 is on PATH. If not, downloads
# the official universal2 .pkg from python.org and installs it via
# `sudo installer` (one password prompt). Then downloads the latest
# Silentfrog source from GitHub, places it under ~/Silentfrog/app, and
# runs install_silentfrog.py so the user ends up with a working .venv
# plus a Silentfrog launcher on the Desktop.
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
    printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*" | tee -a "$LOG_FILE"
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

get_latest_sha() {
    local python_cmd="$1"
    local url="https://api.github.com/repos/$OWNER/$REPO/commits/$BRANCH"
    log "Querying $url"
    curl -fsSL -H "Accept: application/vnd.github+json" "$url" \
        | "$python_cmd" -c "import sys, json; print(json.load(sys.stdin)['sha'])"
}

download_archive() {
    local sha="$1"
    local archive="$STAGING/source.zip"
    local url="https://github.com/$OWNER/$REPO/archive/$sha.zip"
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
    local sha="$2"
    log "Running install_silentfrog.py with --revision $sha"
    (
        cd "$APP_DIR"
        "$python_cmd" install_silentfrog.py --revision "$sha"
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

    local sha
    sha="$(get_latest_sha "$python_cmd")"
    log "Target revision: $sha"

    local archive
    archive="$(download_archive "$sha")"
    local source_dir
    source_dir="$(extract_archive "$archive")"
    sync_app_directory "$source_dir"
    invoke_installer "$python_cmd" "$sha"

    log "Silentfrog bootstrap complete"
    printf '\nSilentfrog installed. Look for the Silentfrog launcher on your Desktop.\n'
    printf 'If anything went wrong, see %s.\n' "$LOG_FILE"
    read -r -p "Press Return to close..." _
}

main "$@"
