#!/bin/bash
# Merge environment variables into .claude/settings.local.json
# Usage: set-env.sh KEY1=VALUE1 KEY2=VALUE2 ...
#
# Creates .claude/settings.local.json if it doesn't exist.
# Merges into existing "env" object without overwriting other keys.
# Pure bash + sed — no python3, jq, or other dependencies required.
# Compatible with bash 3.2 (the version shipped on macOS).

set -e

SETTINGS_FILE=".claude/settings.local.json"

if [ $# -eq 0 ]; then
  echo "Usage: set-env.sh KEY1=VALUE1 KEY2=VALUE2 ..." >&2
  exit 1
fi

# Validate every argument up front so we fail fast on bad input.
for arg in "$@"; do
  if [[ "$arg" != *"="* ]]; then
    echo "ERROR: Invalid argument '$arg'. Expected KEY=VALUE format." >&2
    exit 1
  fi
done

mkdir -p "$(dirname "$SETTINGS_FILE")"

# Refuse to clobber a malformed settings file — fix it first.
if [ -f "$SETTINGS_FILE" ] && command -v python3 >/dev/null 2>&1; then
  if ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$SETTINGS_FILE" 2>/dev/null; then
    echo "ERROR: $SETTINGS_FILE is not valid JSON. Fix or move it aside, then re-run." >&2
    exit 1
  fi
fi

# Read existing settings or start with an empty env object
if [ -f "$SETTINGS_FILE" ]; then
  existing=$(cat "$SETTINGS_FILE")
else
  existing='{ "env": {} }'
fi

# Ensure "env" key exists — if the file has no env block, wrap it
if ! echo "$existing" | grep -q '"env"'; then
  existing=$(echo "$existing" | sed 's/}[[:space:]]*$/,\n  "env": {}\n}/')
fi

# For each KEY=VALUE arg, either update the existing key or insert it
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

# Clean up any trailing commas before closing braces (invalid JSON)
existing=$(echo "$existing" | sed 's/,[[:space:]]*}/\n  }/g')

# Write atomically via a temp file so a malformed result never replaces a good file.
tmp_file="${SETTINGS_FILE}.tmp.$$"
echo "$existing" > "$tmp_file"

# Validate the result before swapping in. If python3 isn't available, skip validation —
# the user can still recover from .tmp file if something goes wrong.
if command -v python3 >/dev/null 2>&1; then
  if ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$tmp_file" 2>/dev/null; then
    echo "ERROR: produced invalid JSON. Likely cause: a special character in a value broke" >&2
    echo "       sed-based escaping. Bad output left at $tmp_file for inspection." >&2
    echo "       Original $SETTINGS_FILE was not modified." >&2
    exit 1
  fi
fi
mv "$tmp_file" "$SETTINGS_FILE"

# Report what was set (mask sensitive values)
for arg in "$@"; do
  key="${arg%%=*}"
  value="${arg#*=}"
  if [ ${#value} -gt 4 ] && [[ ! "$key" =~ _(HOST|PORT|SITE)$ ]] && [ "$value" != "true" ] && [ "$value" != "false" ]; then
    display="${value:0:2}***${value: -2}"
  else
    display="$value"
  fi
  echo "  $key = $display"
done

echo ""
echo "Saved to $SETTINGS_FILE"
