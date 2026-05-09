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

# 3. macOS-only: uv-managed Python lacks the network entitlement
# uvx defaults to a uv-managed standalone Python build that on macOS does NOT
# carry com.apple.security.network.client. The MCP server starts and tools
# register, but every controller call fails with errno 65 (silent from
# Claude Code's view). plugin.json now passes `--python-preference system` to
# uvx, so this only fails when no system Python is installed and uv falls
# back to its managed build. See issue #219.
if [ "$(uname -s)" = "Darwin" ] && command -v uv >/dev/null 2>&1; then
  selected_py=$(uv python find --python-preference system 2>/dev/null || true)
  case "$selected_py" in
    */.local/share/uv/python/*)
      echo "  [WARN] uv would fall back to its managed Python on this Mac:"
      echo "           $selected_py"
      echo "         macOS blocks outbound network from that binary (missing"
      echo "         com.apple.security.network.client entitlement). The MCP"
      echo "         server will appear to start but every tool call returns"
      echo "         'Not connected to controller'. See issue #219."
      echo ""
      echo "         Fix: install a system Python so uvx can use it, e.g."
      echo "           brew install python@3.13"
      echo "         Or pin the interpreter explicitly:"
      echo "           export UV_PYTHON=/opt/homebrew/bin/python3"
      warnings=$((warnings + 1))
      ;;
    "")
      echo "  [INFO] Could not probe which Python uvx will use (older uv?)."
      echo "         If tool calls return 'Not connected to controller', see #219."
      ;;
    *)
      echo "  [OK]   uvx will use system Python: $selected_py"
      ;;
  esac
fi

# 4. plugin enablement — there's no programmatic check, just remind the user
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
