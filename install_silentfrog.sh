#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"
if [[ "$(uname -s)" == "Darwin" ]]; then
  candidates=("${SILENTFROG_PYTHON:-}" python3.12 /usr/local/bin/python3.12 /opt/homebrew/bin/python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3)
else
  candidates=("${SILENTFROG_PYTHON:-}" python3)
fi
silentfrog_python=""
for candidate in "${candidates[@]}"; do
  [[ -n "$candidate" ]] || continue
  if command -v "$candidate" >/dev/null 2>&1; then
    version="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
    if [[ "$(uname -s)" != "Darwin" || "$version" == "3.12" ]]; then
      silentfrog_python="$candidate"
      break
    fi
  fi
done
if [[ -z "$silentfrog_python" ]]; then
  echo "[install] Python 3.12 was not found."
  echo "[install] On Intel Mac with Homebrew, install it with: brew install python@3.12"
  echo "[install] Or install Python 3.12 from python.org, then run this installer again."
  exit 1
fi
exec "$silentfrog_python" install_silentfrog.py "$@"
