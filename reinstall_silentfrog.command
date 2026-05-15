#!/usr/bin/env bash
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"
echo "Reinstalling Silentfrog with a fresh local .venv..."
"$script_dir/reinstall_silentfrog.sh" "$@"
status=$?
echo ""
if [[ "$status" -eq 0 ]]; then
  echo "Silentfrog reinstalled. You can now use the Desktop launcher or run_silentfrog.sh."
else
  echo "Silentfrog reinstall failed with exit code $status."
fi
echo "Press Return to close this window."
read -r _
exit "$status"
