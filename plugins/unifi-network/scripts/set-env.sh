#!/bin/bash
# Bash 3.2-compatible setup. Pipe a JSON env patch with --input-json for secrets.
# Legacy KEY=VALUE arguments accept non-secret settings and provider references.
set -e
set +x
target=claude
flags=()
input_json=false
refresh=false
migrate=false
while [ $# -gt 0 ]; do
  case "$1" in
    --target) [ $# -ge 2 ] || { echo 'ERROR: target is required.' >&2; exit 1; }; target=$2; shift 2 ;;
    --target=*) target=${1#*=}; shift ;;
    --refresh) refresh=true; flags+=(--refresh); shift ;;
    --migrate) migrate=true; flags+=(--migrate); shift ;;
    --dry-run) flags+=(--dry-run); shift ;;
    --input-json) input_json=true; shift ;;
    --) shift; break ;;
    -*) echo 'ERROR: unsupported setup option.' >&2; exit 1 ;;
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
if [ "$refresh" = true ]; then
  [ "$target" = codex ] && [ "$input_json" = false ] && [ $# -eq 0 ] || {
    echo 'ERROR: --refresh requires --target codex and no environment arguments.' >&2; exit 1;
  }
  exec "${runner[@]}" "$script_dir/setup_config.py" --target "$target" "${flags[@]}" </dev/null
fi
if [ "$migrate" = true ]; then
  [ "$target" = claude ] && [ "$input_json" = false ] && [ $# -eq 0 ] || {
    echo 'ERROR: --migrate requires --target claude and no environment arguments.' >&2; exit 1;
  }
  exec "${runner[@]}" "$script_dir/setup_config.py" --target "$target" "${flags[@]}" </dev/null
fi
if [ "$input_json" = true ]; then
  [ $# -eq 0 ] || { echo 'ERROR: JSON input cannot be combined with positional values.' >&2; exit 1; }
  exec "${runner[@]}" "$script_dir/setup_config.py" --target "$target" "${flags[@]}"
fi
[ $# -gt 0 ] || { echo 'ERROR: supply --input-json or non-secret KEY=VALUE settings.' >&2; exit 1; }
# printf is a shell builtin: values never enter a child process argument list.
printf '%s\0' "$@" | "${runner[@]}" "$script_dir/setup_config.py" --target "$target" --pairs "${flags[@]}"
