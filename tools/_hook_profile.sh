#!/usr/bin/env bash
# tools/_hook_profile.sh — bash counterpart to shared/runtime/hook_profile.py
# (V3 B7 borrow). Source this from any shell script that wants profile-gated
# hook execution.
#
# Env vars:
#   SPINE_HOOK_PROFILE    minimal | standard | strict (default standard)
#   SPINE_DISABLED_HOOKS  csv of hook names to always skip
#
# Functions:
#   spine_hook_profile_level                  -> echoes integer level
#   spine_hook_active_profile                 -> echoes normalised profile name
#   spine_hook_is_active <name> [<min_profile>] -> exit 0 if active, 1 otherwise
#   spine_hook_explain <name> [<min_profile>] -> echoes a human-readable line
#
# Designed for `set -u` / `set -e` callers; functions never exit > 1.

# Avoid double-sourcing.
if declare -F spine_hook_active_profile >/dev/null 2>&1; then return 0; fi

_spine_hook_profile_level_for() {
  case "$1" in
    minimal)  printf '1' ;;
    standard) printf '2' ;;
    strict)   printf '3' ;;
    *)        printf '0' ;;
  esac
}

spine_hook_active_profile() {
  local raw="${SPINE_HOOK_PROFILE:-}"
  raw="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  case "$raw" in
    minimal|standard|strict) printf '%s' "$raw" ;;
    *)                       printf 'standard' ;;
  esac
}

spine_hook_profile_level() {
  _spine_hook_profile_level_for "$(spine_hook_active_profile)"
}

_spine_hook_in_disabled() {
  local needle="$1" csv="${SPINE_DISABLED_HOOKS:-}"
  [[ -z "$csv" ]] && return 1
  local IFS=','
  # shellcheck disable=SC2206
  local -a items=( $csv )
  local item
  for item in "${items[@]}"; do
    # trim whitespace
    item="${item#"${item%%[![:space:]]*}"}"
    item="${item%"${item##*[![:space:]]}"}"
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

spine_hook_is_active() {
  local name="$1" min_profile="${2:-standard}"
  if [[ -z "${name// /}" ]]; then return 1; fi
  if _spine_hook_in_disabled "$name"; then return 1; fi
  local min_level active_level
  min_level="$(_spine_hook_profile_level_for "$min_profile")"
  active_level="$(spine_hook_profile_level)"
  [[ "$min_level" == "0" ]] && return 1
  (( active_level >= min_level ))
}

spine_hook_explain() {
  local name="$1" min_profile="${2:-standard}"
  if [[ -z "${name// /}" ]]; then printf 'hook_name empty\n'; return; fi
  if _spine_hook_in_disabled "$name"; then
    printf 'hook %q disabled via SPINE_DISABLED_HOOKS\n' "$name"
    return
  fi
  local active; active="$(spine_hook_active_profile)"
  if ! spine_hook_is_active "$name" "$min_profile"; then
    printf 'hook %q skipped — minimum profile %q, active %q\n' \
      "$name" "$min_profile" "$active"
    return
  fi
  printf 'hook %q active (profile=%q)\n' "$name" "$active"
}
