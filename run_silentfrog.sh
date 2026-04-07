#!/usr/bin/env bash
# Launch Silentfrog from the local .venv when available.
# Falls back to Poetry for developers.

set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"
export QT_API="${QT_API:-pyside6}"

launcher="$script_dir/.venv/bin/silentfrog"
if [[ -x "$launcher" ]]; then
  exec "$launcher" "$@"
fi

exec poetry run silentfrog "$@"
