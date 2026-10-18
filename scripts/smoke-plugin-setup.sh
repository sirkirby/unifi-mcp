#!/bin/bash
# Invoke the same fixture corpus under the selected Bash (including macOS 3.2).
set -e
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
echo "Running plugin setup fixtures under Bash $BASH_VERSION"
exec python3 "$repo_root/scripts/plugin_setup_fixtures.py" --shell "$BASH"
