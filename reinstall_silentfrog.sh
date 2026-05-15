#!/bin/sh
set -eu
script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$script_dir"
silentfrog_python=""
try_silentfrog_python() {
  candidate=$1
  [ -n "$candidate" ] || return 1
  if command -v "$candidate" >/dev/null 2>&1; then
    version=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)
    if [ "$(uname -s)" != "Darwin" ] || [ "$version" = "3.12" ]; then
      silentfrog_python="$candidate"
      return 0
    fi
  fi
  return 1
}
if [ -n "${SILENTFROG_PYTHON:-}" ]; then
  try_silentfrog_python "$SILENTFROG_PYTHON" || true
fi
if [ -z "$silentfrog_python" ] && [ "$(uname -s)" = "Darwin" ]; then
  for candidate in python3.12 /usr/local/bin/python3.12 /opt/homebrew/bin/python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3; do
    try_silentfrog_python "$candidate" && break
  done
fi
if [ -z "$silentfrog_python" ] && [ "$(uname -s)" != "Darwin" ]; then
  try_silentfrog_python python3 || true
fi
if [ -z "$silentfrog_python" ]; then
  echo "[install] Python 3.12 was not found."
  echo "[install] On Intel Mac with Homebrew, install it with: brew install python@3.12"
  echo "[install] Or install Python 3.12 from python.org, then run this installer again."
  exit 1
fi
exec "$silentfrog_python" install_silentfrog.py --recreate-venv "$@"
