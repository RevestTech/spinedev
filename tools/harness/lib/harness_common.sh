# shellcheck shell=bash
# Shared helpers for Harness Lite CLI and loop-bridge.

_harness_die() {
  printf 'harness: error: %s\n' "$*" >&2
  exit "${HARNESS_EXIT:-1}"
}

_harness_repo_root() {
  local start="${1:-.}"
  local dir
  dir="$(cd "$start" && pwd)"
  while [[ "$dir" != "/" ]]; do
    if [[ -d "$dir/.git" || -f "$dir/.spine/harness/state.json" ]]; then
      printf '%s\n' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  printf '%s\n' "$(cd "$start" && pwd)"
}

_harness_now_utc() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

_harness_state_dir() {
  printf '%s/.spine/harness\n' "${HARNESS_PROJECT_ROOT:?}"
}

_harness_state_file() {
  printf '%s/state.json\n' "$(_harness_state_dir)"
}

_harness_loops_dir() {
  printf '%s/loops\n' "$(_harness_state_dir)"
}

_harness_findings_dir() {
  printf '%s/findings\n' "$(_harness_state_dir)"
}

_harness_reports_dir() {
  printf '%s/reports\n' "$(_harness_state_dir)"
}

_harness_py() {
  if [[ -n "${HARNESS_PYTHON:-}" ]]; then
    printf '%s\n' "$HARNESS_PYTHON"
    return 0
  fi
  if [[ -n "${SPINE_HOME:-}" && -x "${SPINE_HOME}/.venv/bin/python3" ]]; then
    printf '%s\n' "${SPINE_HOME}/.venv/bin/python3"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  _harness_die "python3 required for harness state I/O"
}

_harness_valid_mode() {
  case "$1" in
    bootstrap|feature|sprint-close|release-gate|watch) return 0 ;;
    *) return 1 ;;
  esac
}

_harness_parse_interval() {
  # Accept 30s, 5m, 2h, 1d → seconds
  local raw="$1"
  local num unit
  if [[ ! "$raw" =~ ^([0-9]+)([smhd])$ ]]; then
    _harness_die "invalid interval '$raw' (use 30s, 5m, 2h, 1d)"
  fi
  num="${BASH_REMATCH[1]}"
  unit="${BASH_REMATCH[2]}"
  case "$unit" in
    s) printf '%s\n' "$num" ;;
    m) printf '%s\n' "$(( num * 60 ))" ;;
    h) printf '%s\n' "$(( num * 3600 ))" ;;
    d) printf '%s\n' "$(( num * 86400 ))" ;;
  esac
}
