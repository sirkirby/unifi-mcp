#!/bin/bash
# Bash 3.2-compatible setup. Pipe a JSON env patch with --input-json for secrets.
# Legacy KEY=VALUE arguments accept non-secret settings and provider references.
set -e
set +x
target=claude
flags=()
input_json=false
while [ $# -gt 0 ]; do
  case "$1" in
    --target) [ $# -ge 2 ] || { echo 'ERROR: target is required.' >&2; exit 1; }; target=$2; shift 2 ;;
    --target=*) target=${1#*=}; shift ;;
    --dry-run) flags+=(--dry-run); shift ;;
    --input-json) input_json=true; shift ;;
    --) shift; break ;;
    -*) echo 'ERROR: unsupported setup option.' >&2; exit 1 ;;
    *) break ;;
  esac
done
if ! command -v python3 >/dev/null 2>&1; then
  echo 'ERROR: Python 3.11+ is required. Install it and rerun; existing configuration is unchanged.' >&2
  exit 1
fi
script_dir="$(cd "$(dirname "$0")" && pwd)"
if [ "$input_json" = true ]; then
  [ $# -eq 0 ] || { echo 'ERROR: JSON input cannot be combined with positional values.' >&2; exit 1; }
  exec python3 "$script_dir/setup_config.py" --target "$target" "${flags[@]}"
fi
[ $# -gt 0 ] || { echo 'ERROR: supply --input-json or non-secret KEY=VALUE settings.' >&2; exit 1; }
# printf is a shell builtin: values never enter a child process argument list.
printf '%s\0' "$@" | python3 "$script_dir/setup_config.py" --target "$target" --pairs "${flags[@]}"
