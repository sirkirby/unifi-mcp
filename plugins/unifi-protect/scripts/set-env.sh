#!/bin/bash
# Configure UniFi MCP client environment.
# Usage:
#   set-env.sh [--target claude|codex] [--dry-run] KEY1=VALUE1 KEY2=VALUE2 ...
#
# Claude target: merges environment variables into .claude/settings.local.json.
# Codex target: registers/replaces the MCP server with `codex mcp add --env`.
#
# Bash 3.2 compatible for stock macOS.

set -e

TARGET="claude"
DRY_RUN="false"

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
    --dry-run)
      DRY_RUN="true"
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

if [ $# -eq 0 ]; then
  echo "Usage: set-env.sh [--target claude|codex] [--dry-run] KEY1=VALUE1 KEY2=VALUE2 ..." >&2
  exit 1
fi

case "$TARGET" in
  claude|codex) ;;
  *)
    echo "ERROR: Unsupported target '$TARGET'. Expected claude or codex." >&2
    exit 1
    ;;
esac

for arg in "$@"; do
  if [[ "$arg" != *"="* ]]; then
    echo "ERROR: Invalid argument '$arg'. Expected KEY=VALUE format." >&2
    exit 1
  fi
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGIN_NAME="$(basename "$PLUGIN_ROOT")"

detect_package_pin() {
  for manifest in "$PLUGIN_ROOT/.claude-plugin/plugin.json" "$PLUGIN_ROOT/.mcp.json"; do
    if [ -f "$manifest" ]; then
      pin=$(grep -Eo 'unifi-[a-z]+-mcp==[0-9][^"]*' "$manifest" | head -1 || true)
      if [ -n "$pin" ]; then
        echo "$pin"
        return
      fi
    fi
  done

  case "$PLUGIN_NAME" in
    unifi-network) echo "unifi-network-mcp@latest" ;;
    unifi-protect) echo "unifi-protect-mcp@latest" ;;
    unifi-access) echo "unifi-access-mcp@latest" ;;
    *)
      echo "ERROR: Could not infer MCP package for $PLUGIN_NAME" >&2
      exit 1
      ;;
  esac
}

mask_value() {
  key="$1"
  value="$2"
  if [ ${#value} -gt 4 ] && [[ ! "$key" =~ _(HOST|PORT|SITE)$ ]] && [ "$value" != "true" ] && [ "$value" != "false" ]; then
    echo "${value:0:2}***${value: -2}"
  else
    echo "$value"
  fi
}

print_values() {
  for arg in "$@"; do
    key="${arg%%=*}"
    value="${arg#*=}"
    display="$(mask_value "$key" "$value")"
    echo "  $key = $display"
  done
}

write_claude_settings() {
  SETTINGS_FILE=".claude/settings.local.json"

  if [ "$DRY_RUN" = "true" ]; then
    echo "Would merge these values into $SETTINGS_FILE:"
    print_values "$@"
    return
  fi

  mkdir -p "$(dirname "$SETTINGS_FILE")"

  if [ -f "$SETTINGS_FILE" ] && command -v python3 >/dev/null 2>&1; then
    if ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$SETTINGS_FILE" 2>/dev/null; then
      echo "ERROR: $SETTINGS_FILE is not valid JSON. Fix or move it aside, then re-run." >&2
      exit 1
    fi
  fi

  if [ -f "$SETTINGS_FILE" ]; then
    existing=$(cat "$SETTINGS_FILE")
  else
    existing='{ "env": {} }'
  fi

  if ! echo "$existing" | grep -q '"env"'; then
    existing=$(echo "$existing" | sed 's/}[[:space:]]*$/,\n  "env": {}\n}/')
  fi

  for arg in "$@"; do
    key="${arg%%=*}"
    value="${arg#*=}"
    escaped_value=$(printf '%s' "$value" | sed 's/\\/\\\\/g; s/"/\\"/g; s/&/\\&/g')

    if echo "$existing" | grep -q "\"$key\""; then
      existing=$(echo "$existing" | sed "s|\"$key\"[[:space:]]*:[[:space:]]*\"[^\"]*\"|\"$key\": \"$escaped_value\"|")
    else
      existing=$(echo "$existing" | sed "s|\"env\"[[:space:]]*:[[:space:]]*{|\"env\": {\n    \"$key\": \"$escaped_value\",|")
    fi
  done

  existing=$(echo "$existing" | sed 's/,[[:space:]]*}/\n  }/g')

  tmp_file="${SETTINGS_FILE}.tmp.$$"
  echo "$existing" > "$tmp_file"

  if command -v python3 >/dev/null 2>&1; then
    if ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$tmp_file" 2>/dev/null; then
      echo "ERROR: produced invalid JSON. Bad output left at $tmp_file for inspection." >&2
      echo "       Original $SETTINGS_FILE was not modified." >&2
      exit 1
    fi
  fi

  mv "$tmp_file" "$SETTINGS_FILE"
  print_values "$@"
  echo ""
  echo "Saved to $SETTINGS_FILE"
}

write_codex_config() {
  package_pin="$(detect_package_pin)"

  if ! command -v codex >/dev/null 2>&1; then
    echo "ERROR: codex CLI not found on PATH. Install or open Codex, then re-run setup." >&2
    exit 1
  fi

  if ! command -v uvx >/dev/null 2>&1; then
    echo "ERROR: uvx not found on PATH. Install uv, then re-run setup." >&2
    exit 1
  fi

  cmd=(mcp add "$PLUGIN_NAME")
  for arg in "$@"; do
    cmd+=(--env "$arg")
  done
  cmd+=(-- uvx --python-preference system "$package_pin")

  if [ "$DRY_RUN" = "true" ]; then
    echo "Would replace Codex MCP server '$PLUGIN_NAME' with:"
    printf '  codex mcp add %q' "$PLUGIN_NAME"
    for arg in "$@"; do
      key="${arg%%=*}"
      value="${arg#*=}"
      display="$(mask_value "$key" "$value")"
      printf ' --env %q' "$key=$display"
    done
    printf ' -- uvx --python-preference system %q' "$package_pin"
    echo ""
    echo ""
    echo "Environment values:"
    print_values "$@"
    return
  fi

  codex mcp remove "$PLUGIN_NAME" >/dev/null 2>&1 || true
  codex "${cmd[@]}"
  echo ""
  echo "Configured Codex MCP server '$PLUGIN_NAME' with $package_pin."
  echo "Restart Codex so the updated MCP server configuration is loaded."
}

case "$TARGET" in
  claude) write_claude_settings "$@" ;;
  codex) write_codex_config "$@" ;;
esac
