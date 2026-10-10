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
# Prefer a working local interpreter; uv supplies managed Python when needed.
runner=()
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     probe=$("$candidate" -c 'import sys; print("unifi-setup-python-ok") if sys.version_info >= (3, 11) else sys.exit(1)' </dev/null 2>/dev/null) &&
     [ "$probe" = unifi-setup-python-ok ]; then
    runner=("$candidate")
    break
  fi
done
if [ ${#runner[@]} -eq 0 ]; then
  if ! command -v uv >/dev/null 2>&1; then
    echo 'ERROR: No usable setup runtime. Install uv (which supplies Python) and rerun; existing configuration is unchanged.' >&2
    exit 1
  fi
  runner=(uv run --no-project --python '>=3.11' python)
fi
script_dir="$(cd "$(dirname "$0")" && pwd)"
exec "${runner[@]}" "$script_dir/setup_config.py" --target "$target" --check
