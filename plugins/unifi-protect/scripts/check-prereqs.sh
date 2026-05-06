#!/bin/bash
# Pre-flight check for unifi-* plugin setup.
# Verifies uvx is installed and any existing settings file is valid JSON.
# Run this BEFORE asking the user for credentials so silent failures get caught early.
# Bash 3.2 compatible (works on stock macOS /bin/bash).

set -e

PLUGIN_NAME="${1:-unifi plugin}"
SETTINGS_FILE=".claude/settings.local.json"

errors=0
warnings=0

echo "Checking prerequisites for $PLUGIN_NAME..."
echo ""

# 1. uvx — required to launch the MCP server
if command -v uvx >/dev/null 2>&1; then
  uvx_version=$(uvx --version 2>&1 | head -1)
  echo "  [OK]   uvx found: $uvx_version"
else
  echo "  [FAIL] uvx not found on PATH"
  echo ""
  echo "         The MCP server is launched via uvx (part of uv)."
  echo "         Install uv with one of:"
  echo "           curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "           brew install uv"
  echo "           pip install --user uv"
  echo ""
  echo "         After installing, restart your shell so PATH refreshes,"
  echo "         then re-run setup."
  echo ""
  errors=$((errors + 1))
fi

# 2. existing settings.local.json must be valid JSON before we touch it
if [ -f "$SETTINGS_FILE" ]; then
  if command -v python3 >/dev/null 2>&1; then
    if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$SETTINGS_FILE" 2>/dev/null; then
      echo "  [OK]   $SETTINGS_FILE is valid JSON"
    else
      echo "  [FAIL] $SETTINGS_FILE exists but is not valid JSON"
      echo "         Fix or move it aside before continuing — setup will not"
      echo "         clobber a malformed settings file."
      errors=$((errors + 1))
    fi
  else
    echo "  [WARN] python3 not available — cannot validate $SETTINGS_FILE"
    warnings=$((warnings + 1))
  fi
else
  echo "  [OK]   $SETTINGS_FILE does not exist yet (will be created)"
fi

# 3. plugin enablement — there's no programmatic check, just remind the user
echo "  [INFO] Reminder: 'installed' is not the same as 'enabled'."
echo "         After setup, run /plugin and confirm the plugin shows enabled."

echo ""
if [ $errors -gt 0 ]; then
  echo "Prerequisite check FAILED with $errors error(s). Resolve the issues above and re-run."
  exit 1
fi

if [ $warnings -gt 0 ]; then
  echo "Prerequisite check passed with $warnings warning(s)."
else
  echo "Prerequisite check passed."
fi
