#!/usr/bin/env bash
# roles.sh — single source of truth for SpineDevelopment team role IDs.
#
# Every role has: teams/<id>/directive.md, manager daemon, workers 01–10,
# watchdog supervision. IDs use lowercase and hyphens only (daemon-safe paths).
#
# Source this file after resolving SCRIPT_DIR to the scripts/ directory:
#   source "$SCRIPT_DIR/roles.sh"

# shellcheck disable=SC2034 # array consumed by callers
SPINE_TEAM_ROLES=(
  product
  planner
  architect
  conductor
  researcher
  engineer
  engineering-backend
  engineering-frontend
  ux
  qa
  operator
  datawright
  seer
  auditor
  memory
)

spine_role_valid() {
  local r="$1"
  local x
  for x in "${SPINE_TEAM_ROLES[@]}"; do
    [[ "$x" == "$r" ]] && return 0
  done
  return 1
}

spine_roles_csv() {
  (IFS=,; echo "${SPINE_TEAM_ROLES[*]}")
}
