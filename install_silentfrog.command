#!/usr/bin/env bash
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"
echo "Installing Silentfrog..."
"$script_dir/install_silentfrog.sh" "$@"
status=$?
echo ""
if [[ "$status" -eq 0 ]]; then
  echo "Silentfrog installed. You can now use the Desktop launcher or run_silentfrog.sh."
else
  echo "Silentfrog installation failed with exit code $status."
fi
echo "Press Return to close this window."
read -r _
exit "$status"
