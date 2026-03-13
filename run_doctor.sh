#!/usr/bin/env bash
# Run Silentfrog doctor checks from repo root.

set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

poetry run python tools/doctor.py "$@"
