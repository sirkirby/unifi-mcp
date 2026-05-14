#!/bin/bash
# Pre-flight check for unifi-* plugin setup.
# Verifies uvx and client-specific setup prerequisites before credentials are collected.
# Bash 3.2 compatible for stock macOS.

set -e

TARGET="claude"

while [ $# -gt 0 ]; do
  case "$1" in
    --target)
      if [ $# -lt 2 ]; then
        echo "ERROR: --target requires claude or codex" >&2
        exit 1
      fi
      TARGET="$2"
      shift 2
      ;;
    --target=*)
      TARGET="${1#--target=}"
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "ERROR: Unknown option '$1'" >&2
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

PLUGIN_NAME="${1:-unifi plugin}"
SETTINGS_FILE=".claude/settings.local.json"

case "$TARGET" in
  claude|codex) ;;
  *)
    echo "ERROR: Unsupported target '$TARGET'. Expected claude or codex." >&2
    exit 1
    ;;
esac

errors=0
warnings=0

echo "Checking prerequisites for $PLUGIN_NAME ($TARGET)..."
echo ""

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

if [ "$TARGET" = "claude" ]; then
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
else
  if command -v codex >/dev/null 2>&1; then
    codex_version=$(codex --version 2>&1 | head -1)
    echo "  [OK]   codex found: $codex_version"
    if codex mcp list >/dev/null 2>&1; then
      echo "  [OK]   codex mcp list succeeded"
    else
      echo "  [WARN] codex is installed, but 'codex mcp list' failed"
      echo "         Setup may still work, but confirm Codex is authenticated."
      warnings=$((warnings + 1))
    fi
  else
    echo "  [FAIL] codex CLI not found on PATH"
    echo "         Codex setup registers the MCP server with 'codex mcp add'."
    echo "         Install or open Codex, then re-run setup."
    errors=$((errors + 1))
  fi
fi

if [ "$(uname -s)" = "Darwin" ] && command -v uv >/dev/null 2>&1; then
  selected_py=$(uv python find --python-preference system 2>/dev/null || true)
  case "$selected_py" in
    */.local/share/uv/python/*)
      echo "  [WARN] uv would fall back to its managed Python on this Mac:"
      echo "           $selected_py"
      echo "         macOS may not grant outbound network to that interpreter,"
      echo "         so controller calls can return 'Not connected to controller'"
      echo "         even though the server starts cleanly."
      echo ""
      echo "         Install a system Python so uvx can use it, e.g."
      echo "           brew install python@3.13"
      echo "         Or pin the interpreter explicitly:"
      echo "           export UV_PYTHON=/opt/homebrew/bin/python3"
      warnings=$((warnings + 1))
      ;;
    "")
      echo "  [INFO] Could not probe uvx's interpreter selection (older uv?)."
      echo "         If tool calls return 'Not connected to controller',"
      echo "         confirm uvx is using a system or Homebrew Python."
      ;;
    *)
      echo "  [OK]   uvx will use system Python: $selected_py"
      ;;
  esac
fi

if [ "$TARGET" = "claude" ]; then
  echo "  [INFO] Reminder: 'installed' is not the same as 'enabled'."
  echo "         After setup, run /plugin and confirm the plugin shows enabled."
else
  echo "  [INFO] After setup, restart Codex so MCP server changes are loaded."
fi

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
