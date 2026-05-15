#!/bin/sh
# Launch Silentfrog from the local .venv when available.
# Falls back to Poetry for developers.

set -eu
script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$script_dir"
export QT_API="${QT_API:-pyside6}"

launcher="$script_dir/.venv/bin/silentfrog"
if [ -x "$launcher" ]; then
  exec "$launcher" "$@"
fi

exec poetry run silentfrog "$@"
