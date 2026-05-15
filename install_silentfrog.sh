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
    case "$version" in
      3.12|3.13|3.14)
        silentfrog_python="$candidate"
        return 0
        ;;
    esac
  fi
  return 1
}
if [ -n "${SILENTFROG_PYTHON:-}" ]; then
  try_silentfrog_python "$SILENTFROG_PYTHON" || true
fi
if [ -z "$silentfrog_python" ] && [ "$(uname -s)" = "Darwin" ]; then
  for candidate in python3.14 python3.13 python3.12 /usr/local/bin/python3.14 /opt/homebrew/bin/python3.14 /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 /usr/local/bin/python3.13 /opt/homebrew/bin/python3.13 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 /usr/local/bin/python3.12 /opt/homebrew/bin/python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3; do
    try_silentfrog_python "$candidate" && break
  done
fi
if [ -z "$silentfrog_python" ] && [ "$(uname -s)" != "Darwin" ]; then
  for candidate in python3.14 python3.13 python3.12 python3; do
    try_silentfrog_python "$candidate" && break
  done
fi
if [ -z "$silentfrog_python" ]; then
  echo "[install] Python 3.12, 3.13, or 3.14 was not found."
  echo "[install] Install one supported Python version, then run this installer again."
  exit 1
fi
exec "$silentfrog_python" install_silentfrog.py "$@"
