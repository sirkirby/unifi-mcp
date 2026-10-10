#!/bin/bash
# Bash 3.2-compatible, credential-free prerequisite and configuration validation.
set -e
set +x
target=claude
while [ $# -gt 0 ]; do
  case "$1" in
    --target) [ $# -ge 2 ] || { echo 'ERROR: target is required.' >&2; exit 1; }; target=$2; shift 2 ;;
    --target=*) target=${1#*=}; shift ;;
    --) shift; break ;;
    -*) echo 'ERROR: unsupported prerequisite option.' >&2; exit 1 ;;
    *) break ;;
  esac
done
if ! command -v python3 >/dev/null 2>&1; then
  echo 'ERROR: Python 3.11+ is required. Install it and rerun; existing configuration is unchanged.' >&2
  exit 1
fi
script_dir="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$script_dir/setup_config.py" --target "$target" --check
