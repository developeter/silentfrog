#!/usr/bin/env bash
# Launch Silentfrog via Poetry (macOS/Linux, Intel or Apple Silicon).
# Usage: double-click if your OS opens shell scripts with Terminal, or run:
#   bash run_silentfrog.sh

set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

poetry run python -m silentfrog.gui
