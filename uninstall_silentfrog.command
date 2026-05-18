#!/bin/sh
script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$script_dir"
echo "Uninstalling Silentfrog..."
"$script_dir/uninstall_silentfrog.sh" "$@"
status=$?
echo ""
if [ "$status" -eq 0 ]; then
  echo "Silentfrog uninstalled. Local crawl history was preserved unless --purge was used."
else
  echo "Silentfrog uninstall failed with exit code $status."
fi
echo "Press Return to close this window."
read -r _
exit "$status"
