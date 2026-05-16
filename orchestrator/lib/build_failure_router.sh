#!/usr/bin/env bash
# build_failure_router.sh — Build-failure → Plan re-route engine.
#
# STORY-9.8.3: when an engineer reports "scope unclear" (or another
# surfaced blocker), orchestrator routes back to Plan with the original
# directive + the engineer's feedback so Planner can clarify scope.
# Mirror of `remediation.sh` for the build-fail edge.
# See docs/PRD.md REQ-INIT-9 FR-9; docs/BACKLOG.md EPIC-9.8 (STORY-9.8.3);
# orchestrator/state/phases.yaml `retry_policy.build_plan_loop_max` (3);
# db/flyway/sql/V14__spine_lifecycle_schema.sql.
#
# Architectural rule: dispatch via router.sh route_dispatch_to_subsystem
# (MCP chokepoint); state writes via transition.sh transition_execute.
# This file is the policy layer (valid reasons, directive composition,
# retry-budget enforcement).
#
# CLI:
#   build_failure_router.sh route       <failed_did> <reason> [feedback]
#   build_failure_router.sh check-retry <project_id>
#   build_failure_router.sh surface     <project_id> <reason>

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASES_YAML="${SPINE_PHASES_YAML:-$SCRIPT_DIR/../state/phases.yaml}"
SPINE_DB_URL="${SPINE_DB_URL:-postgresql://spine:spine@localhost:33000/spine}"
ROUTER_SH="${SPINE_ROUTER_SH:-$SCRIPT_DIR/router.sh}"
TRANSITION_SH="${SPINE_TRANSITION_SH:-$SCRIPT_DIR/transition.sh}"

BFR_DIRECTIVE_MAX_CHARS="${SPINE_BFR_DIRECTIVE_MAX_CHARS:-2000}"
BFR_FEEDBACK_MAX_CHARS="${SPINE_BFR_FEEDBACK_MAX_CHARS:-1600}"
BFR_DEFAULT_LOOP_MAX="${SPINE_BFR_DEFAULT_LOOP_MAX:-3}"
BFR_DEFAULT_PLANNER_ROLE="${SPINE_BFR_DEFAULT_PLANNER_ROLE:-planner}"
# Closed-enum reasons — anything else is rejected so this script can't be
# repurposed as a generic back-routing escape hatch.
BFR_VALID_REASONS=(scope_unclear requirements_incomplete blocked_by_dependency needs_decision)

# shellcheck source=router.sh
. "$ROUTER_SH"
# shellcheck source=transition.sh
. "$TRANSITION_SH"

_log() { printf '%s build_failure_router.sh %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${*:2}" >&2; }
_sql_esc() { printf '%s' "$1" | sed "s/'/''/g"; }
_err_b() {
  local code="$1" msg="$2" extra="${3:-{\}}"
  printf '{"ok":false,"code":"%s","message":"%s","extra":%s}\n' \
    "$code" "${msg//\"/\\\"}" "$extra"
  _log ERROR "$code: $msg"
}
_reason_valid() {
  local r="$1" v
  for v in "${BFR_VALID_REASONS[@]}"; do [[ "$v" == "$r" ]] && return 0; done
  return 1
}

# Reads build_plan_loop_max from phases.yaml (yq or awk fallback scoping by
# retry_policy: indentation). Defaults to BFR_DEFAULT_LOOP_MAX.
_phases_yaml_bp_loop_max() {
  local v=""
  if command -v yq >/dev/null 2>&1; then
    v="$(yq -r '.transitions_metadata.retry_policy.build_plan_loop_max // ""' "$PHASES_YAML" 2>/dev/null)"
  fi
  if [[ -z "$v" || "$v" == "null" ]]; then
    v="$(awk '
      /^[[:space:]]*retry_policy:/ { match($0,/^[[:space:]]*/); rp=RLENGTH; in_rp=1; next }
      in_rp {
        match($0,/^[[:space:]]*/)
        if ($0 ~ /^[[:space:]]*[A-Za-z_]/ && RLENGTH <= rp) { in_rp=0; next }
        if ($0 ~ /build_plan_loop_max:/) {
          sub(/.*build_plan_loop_max:[[:space:]]*/,""); sub(/[[:space:]]*#.*/,""); print; exit
        }
      }' "$PHASES_YAML" 2>/dev/null)"
  fi
  v="${v//[[:space:]]/}"; [[ -z "$v" ]] && v="$BFR_DEFAULT_LOOP_MAX"
  printf '%s' "$v"
}

# Counts prior build→plan transitions; no counter column — audit log is
# the source of truth so the budget survives crashes / replays.
bfr_check_retry() {
  local pid="${1:-}"
  [[ -z "$pid" ]] && { _err_b "invalid_input" "check-retry requires <project_id>"; return 2; }
  local cap count
  cap="$(_phases_yaml_bp_loop_max)"
  count="$(_psql -c "SELECT COUNT(*) FROM spine_lifecycle.transition
                      WHERE project_id = $pid
                        AND from_phase = 'build_in_progress'
                        AND to_phase   = 'plan_in_progress';")" \
    || { _err_b "db_error" "loop count failed pid=$pid"; return 6; }
  count="${count//[[:space:]]/}"; count="${count:-0}"
  if (( count >= cap )); then
    _err_b "retry_budget_exceeded" \
      "project $pid hit build_plan_loop_max ($cap) — surface to user" \
      "{\"project_id\":$pid,\"loops\":$count,\"cap\":$cap}"
    return 3
  fi
  printf '{"ok":true,"project_id":%s,"loops":%s,"cap":%s,"remaining":%s}\n' \
    "$pid" "$count" "$cap" "$((cap - count))"
}

# Per-reason guidance pinned to the 4 enums so Planner-side reviewers know
# what to look for. Composes header + guidance + truncated feedback.
_compose_replan_directive() {
  local failed_did="$1" reason="$2" feedback="$3" prior_subsystem="$4" guidance
  case "$reason" in
    scope_unclear)           guidance="Clarify scope boundaries and acceptance criteria; mark what is in / out." ;;
    requirements_incomplete) guidance="List missing requirements; cite which PRD/TRD sections need expansion." ;;
    blocked_by_dependency)   guidance="Identify the blocking dependency; propose unblock plan or sequencing." ;;
    needs_decision)          guidance="Surface the open decision to the user; capture chosen option in the plan." ;;
    *)                       guidance="Re-scope and re-emit a Build directive." ;;
  esac
  local fb="${feedback:0:$BFR_FEEDBACK_MAX_CHARS}" d
  (( ${#feedback} > BFR_FEEDBACK_MAX_CHARS )) && fb+=$'\n(... feedback truncated)'
  d="$(printf 'REPLAN (build-fail) parent=%s reason=%s prior_subsystem=%s\n%s\nEngineer feedback:\n%s' \
         "$failed_did" "$reason" "$prior_subsystem" "$guidance" "$fb")"
  (( ${#d} > BFR_DIRECTIVE_MAX_CHARS )) && d="${d:0:BFR_DIRECTIVE_MAX_CHARS}
(... directive truncated at ${BFR_DIRECTIVE_MAX_CHARS} chars)"
  printf '%s' "$d"
}

# Surface — last-resort when the retry budget is blown. Direct UPDATE on
# project.status; project_status_chk allows {active,paused,terminated,completed}
# so we use 'paused' + a metadata.blocker marker (excessive_replanning).
bfr_surface_to_user() {
  local pid="${1:-}" reason="${2:-build_plan_loop exhausted}"
  [[ -z "$pid" ]] && { _err_b "invalid_input" "surface requires <project_id> <reason>"; return 2; }
  _psql <<SQL || { _err_b "db_error" "could not mark project $pid blocked"; return 6; }
UPDATE spine_lifecycle.project
   SET status   = 'paused',
       metadata = metadata || jsonb_build_object(
                     'blocked',        true,
                     'blocked_reason', '$(_sql_esc "$reason")',
                     'blocked_at',     NOW()::text,
                     'blocked_by',     'orchestrator.build_failure_router',
                     'blocker',        'excessive_replanning')
 WHERE id = $pid;
SQL
  _audit_row "$pid" "$(_current_phase "$pid")" "build_failure_surfaced" "$reason" || true
  printf '{"ok":true,"project_id":%s,"status":"paused","blocker":"excessive_replanning"}\n' "$pid"
}

# Top-level: lookup parent dispatch -> reason check -> retry budget ->
# compose -> router.sh route_dispatch_to_subsystem(plan) ->
# transition.sh transition_execute(build_in_progress -> plan_in_progress).
bfr_route() {
  local failed_did="${1:-}" reason="${2:-}" feedback="${3:-}"
  [[ -z "$failed_did" || -z "$reason" ]] && {
    _err_b "invalid_input" "route requires <failed_did> <reason> [feedback]"; return 2; }
  if ! _reason_valid "$reason"; then
    _err_b "invalid_reason" "reason '$reason' not in {${BFR_VALID_REASONS[*]}}" \
      "{\"allowed\":\"${BFR_VALID_REASONS[*]}\"}"
    return 2
  fi
  # Latest matching dispatch wins (idempotency vs. re-dispatched directives).
  local row pid role subsystem
  row="$(_psql -c "SELECT project_id::text || '|' || role || '|' || subsystem
                     FROM spine_lifecycle.route_history
                    WHERE directive_ref = '$(_sql_esc "$failed_did")'
                    ORDER BY dispatched_at DESC LIMIT 1;")" \
    || { _err_b "db_error" "lookup failed for $failed_did"; return 6; }
  row="${row//[[:space:]]/}"
  [[ -z "$row" ]] && { _err_b "invalid_input" "no route_history row for $failed_did"; return 2; }
  pid="${row%%|*}"; row="${row#*|}"; role="${row%%|*}"; subsystem="${row#*|}"

  # Retry budget BEFORE dispatch — never queue past the cap. `set -e` would
  # abort on non-zero, so capture rc explicitly (mirrors remediation.sh).
  local rc=0
  bfr_check_retry "$pid" >/dev/null || rc=$?
  if (( rc != 0 )); then
    if (( rc == 3 )); then
      bfr_surface_to_user "$pid" \
        "build_plan_loop_max exhausted (failed_directive=$failed_did, reason=$reason)" >/dev/null || true
    fi
    return "$rc"
  fi

  local directive
  directive="$(_compose_replan_directive "$failed_did" "$reason" "$feedback" "$subsystem")"

  # Dispatch back to plan via router.sh (MCP chokepoint). Engineer's role
  # on the original dispatch is preserved via parent_directive_id metadata.
  local resp new_did
  resp="$(route_dispatch_to_subsystem "plan" "$BFR_DEFAULT_PLANNER_ROLE" \
                                       "$directive" "$pid" "$failed_did")" \
    || { _err_b "router_failure" "plan dispatch failed for pid=$pid"; return 4; }
  new_did="$(printf '%s' "$resp" | sed -n 's/.*"directive_id":"\([^"]*\)".*/\1/p')"
  [[ -z "$new_did" ]] && {
    _err_b "router_failure" "router reply missing directive_id" "{\"response\":${resp:-null}}"; return 4; }

  # build_in_progress -> plan_in_progress. Delegated so audit + phase_history
  # match the canonical writers. Rationale string is searchable in the
  # transition table (reason column) for retro reporting.
  if ! transition_execute "$pid" "plan_in_progress" "orchestrator.build_failure_router" \
        "build-failure-replanning reason=$reason parent=$failed_did" >/dev/null; then
    _err_b "transition_failure" \
      "dispatch succeeded but build->plan transition failed for pid=$pid" \
      "{\"new_directive_id\":\"$new_did\"}"
    return 5
  fi

  printf '{"ok":true,"project_id":%s,"new_directive_id":"%s","parent_directive_id":"%s","reason":"%s","role":"%s","prior_subsystem":"%s","target":"plan"}\n' \
    "$pid" "$new_did" "$failed_did" "$reason" "$role" "$subsystem"
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    route)       bfr_route            "$@" ;;
    check-retry) bfr_check_retry      "$@" ;;
    surface)     bfr_surface_to_user  "$@" ;;
    -h|--help|"") sed -n '2,22p' "${BASH_SOURCE[0]}" >&2; exit 0 ;;
    *) _err_b "unknown_command" "no such subcommand: $cmd"; exit 64 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
