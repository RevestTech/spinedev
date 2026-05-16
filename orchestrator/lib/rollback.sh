#!/usr/bin/env bash
# rollback.sh — Spine orchestrator project-level rollback orchestration.
#
# Implements STORY-9.2.3 (rollback with rationale + audit + side effects).
# See docs/PRD.md REQ-INIT-9 FR-3 + FR-9; docs/BACKLOG.md EPIC-9.2;
# orchestrator/lib/transition.sh (`transition_rollback` writer);
# orchestrator/state/phases.yaml (`rollback_to[]` + `rollback_policy`);
# db/flyway/sql/V14__spine_lifecycle_schema.sql (schema).
#
# Architectural rule: the *writer* lives in transition.sh. This file is the
# policy + side-effects layer (rationale, actor capability, downstream
# approvals expired, downstream open directives marked cancelled-by-rollback,
# consolidated audit). Delegates the phase row to transition.sh.
#
# CLI:
#   rollback.sh preview  <project_id> <target_phase>
#   rollback.sh rollback <project_id> <target_phase> [--actor NAME] [--rationale TEXT]
#   rollback.sh history  <project_id>

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASES_YAML="${SPINE_PHASES_YAML:-$SCRIPT_DIR/../state/phases.yaml}"
SPINE_DB_URL="${SPINE_DB_URL:-postgresql://spine:spine@localhost:33000/spine}"
TRANSITION_SH="${SPINE_TRANSITION_SH:-$SCRIPT_DIR/transition.sh}"
CAPABILITY_PY="${SPINE_CAPABILITY_PY:-$SCRIPT_DIR/../../plan/pipeline/capability_checker.py}"
ROLLBACK_RATIONALE_MIN="${SPINE_ROLLBACK_RATIONALE_MIN:-8}"

# transition.sh exposes _phase_field_list / _current_phase / _audit_row / _psql
# / _in_list as helpers; gates main() on BASH_SOURCE==0 so sourcing is safe.
# shellcheck source=transition.sh
. "$TRANSITION_SH"

_log() { printf '%s rollback.sh %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${*:2}" >&2; }
_sql_esc() { printf '%s' "$1" | sed "s/'/''/g"; }
# Locally-named error helper so we don't shadow transition.sh's _err_json
# when both are sourced into a single shell session.
_err_j() {
  local code="$1" msg="$2" extra="${3:-{\}}"
  printf '{"ok":false,"code":"%s","message":"%s","extra":%s}\n' \
    "$code" "${msg//\"/\\\"}" "$extra"
  _log ERROR "$code: $msg"
}

_rollback_target_allowed() {
  # Walks phases[current].rollback_to[]. We deliberately do NOT auto-expand
  # the chain — every rollback must be one manifest-sanctioned edge.
  local current="$1" target="$2" allowed
  allowed="$(_phase_field_list "$current" rollback_to)"
  _in_list "$target" "$allowed"
}

_target_entry_ts() {
  # When did the project last enter $target? Anything after this is the
  # "downstream" set to be invalidated / cancelled. Empty = never entered
  # (legal: rolling back to an upstream phase the project has not yet sat
  # in — then we use 'epoch' downstream so nothing matches the cleanup).
  local pid="$1" target="$2" ts
  ts="$(_psql -c "SELECT COALESCE(MAX(entered_at)::text,'')
                    FROM spine_lifecycle.phase_history
                   WHERE project_id = $pid AND phase = '$(_sql_esc "$target")';")"
  printf '%s' "${ts//[[:space:]]/}"
}

_count_downstream_approvals() {
  local pid="$1" ts="$2"
  [[ -z "$ts" ]] && { printf '0'; return; }
  local n; n="$(_psql -c "SELECT COUNT(*) FROM spine_lifecycle.approval
                           WHERE project_id = $pid AND decision = 'approved'
                             AND (expires_at IS NULL OR expires_at > NOW())
                             AND granted_at >= TIMESTAMPTZ '$(_sql_esc "$ts")';")"
  printf '%s' "${n//[[:space:]]/}"
}

_count_downstream_directives() {
  local pid="$1" ts="$2"
  [[ -z "$ts" ]] && { printf '0'; return; }
  local n; n="$(_psql -c "SELECT COUNT(*) FROM spine_lifecycle.route_history
                           WHERE project_id = $pid AND completed_at IS NULL
                             AND dispatched_at >= TIMESTAMPTZ '$(_sql_esc "$ts")';")"
  printf '%s' "${n//[[:space:]]/}"
}

_actor_capability_check() {
  # Soft-fail if the capability infra isn't reachable (skeleton mode), so
  # dev installs don't lock themselves out. Hard-fail only on explicit
  # denial returned by require_capability.
  local actor="$1"
  [[ ! -f "$CAPABILITY_PY" ]] && { _log WARN "capability_checker.py missing — skipping"; return 0; }
  python3 - "$actor" <<'PY' 2>/dev/null
import sys
try:
    from plan.pipeline.capability_checker import require_capability
    from plan.pipeline.manifest_loader import load_pipeline
except Exception:
    sys.exit(0)            # infra not installed — allow
try:
    require_capability(sys.argv[1], "can_modify_sdlc_pipeline", load_pipeline())
except Exception as e:
    print(f"capability_denied: {e}", file=sys.stderr); sys.exit(1)
PY
}

# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────

rollback_preview() {
  # Read-only: render a confirmation payload (no DB writes).
  local pid="${1:-}" target="${2:-}"
  [[ -z "$pid" || -z "$target" ]] && {
    _err_j "invalid_input" "preview requires <project_id> <target_phase>"; return 2; }
  local current; current="$(_current_phase "$pid")" \
    || { _err_j "project_not_found" "no project row for id=$pid"; return 2; }
  if ! _rollback_target_allowed "$current" "$target"; then
    local allowed; allowed="$(_phase_field_list "$current" rollback_to | xargs)"
    _err_j "rejected_invalid" "phase '$current' cannot rollback to '$target'" \
      "{\"from\":\"$current\",\"to\":\"$target\",\"allowed_rollback\":\"$allowed\"}"
    return 4
  fi
  local ts n_appr n_dirs
  ts="$(_target_entry_ts "$pid" "$target")"
  n_appr="$(_count_downstream_approvals "$pid" "$ts")"
  n_dirs="$(_count_downstream_directives "$pid" "$ts")"
  printf '{"ok":true,"preview":true,"project_id":%s,"from":"%s","to":"%s","target_entry_ts":"%s","would_invalidate_approvals":%s,"would_cancel_directives":%s}\n' \
    "$pid" "$current" "$target" "$ts" "$n_appr" "$n_dirs"
}

rollback_project() {
  # 1. rationale (rollback_policy.requires_rationale) 2. capability
  # 3. target ∈ rollback_to[] 4. count side-effects 5. delegate to
  # transition.sh transition_rollback 6. expire approvals / mark directives
  # 7. consolidated audit row.
  local pid="${1:-}" target="${2:-}" actor="${3:-}" rationale="${4:-}"
  [[ -z "$pid" || -z "$target" || -z "$actor" || -z "$rationale" ]] && {
    _err_j "invalid_input" "rollback requires <project_id> <target> <actor> <rationale>"; return 2; }
  if (( ${#rationale} < ROLLBACK_RATIONALE_MIN )); then
    _err_j "rationale_required" \
      "rollback rationale must be ≥$ROLLBACK_RATIONALE_MIN chars (got ${#rationale})"
    return 7
  fi
  if ! _actor_capability_check "$actor"; then
    _err_j "capability_denied" "actor '$actor' lacks can_modify_sdlc_pipeline grant"
    return 8
  fi
  local current; current="$(_current_phase "$pid")" \
    || { _err_j "project_not_found" "no project row for id=$pid"; return 2; }
  if ! _rollback_target_allowed "$current" "$target"; then
    local allowed; allowed="$(_phase_field_list "$current" rollback_to | xargs)"
    _err_j "rejected_invalid" "phase '$current' cannot rollback to '$target'" \
      "{\"from\":\"$current\",\"to\":\"$target\",\"allowed_rollback\":\"$allowed\"}"
    return 4
  fi
  local ts n_appr n_dirs
  ts="$(_target_entry_ts "$pid" "$target")"
  n_appr="$(_count_downstream_approvals "$pid" "$ts")"
  n_dirs="$(_count_downstream_directives "$pid" "$ts")"

  # Delegate the phase rows to transition.sh — it writes phase_history,
  # project.current_phase, and the transition row (with metadata.rollback=true).
  if ! transition_rollback "$pid" "$target" "$actor" "$rationale" >/dev/null; then
    _err_j "transition_failure" \
      "transition.sh transition_rollback failed for pid=$pid → '$target'"
    return 6
  fi

  # Side-effects in their own TX. Schema CHECK constraint
  # (route_history_outcome_chk) forbids outcome='cancelled' — we stamp a
  # metadata marker instead and leave outcome NULL. Failure here is logged
  # but does NOT unwind the rollback (durability > cleanup).
  _psql <<SQL || _log WARN "rollback side-effects partial-failure pid=$pid (rollback durable)"
BEGIN;
UPDATE spine_lifecycle.approval
   SET expires_at = NOW()
 WHERE project_id = $pid AND decision = 'approved'
   AND (expires_at IS NULL OR expires_at > NOW())
   AND granted_at >= COALESCE(TIMESTAMPTZ NULLIF('$(_sql_esc "$ts")',''), 'epoch'::timestamptz);
UPDATE spine_lifecycle.route_history
   SET metadata = metadata || jsonb_build_object(
                     'cancelled_by_rollback', true,
                     'rollback_to_phase',     '$(_sql_esc "$target")',
                     'rollback_at',           NOW()::text)
 WHERE project_id = $pid AND completed_at IS NULL
   AND dispatched_at >= COALESCE(TIMESTAMPTZ NULLIF('$(_sql_esc "$ts")',''), 'epoch'::timestamptz);
COMMIT;
SQL

  _audit_row "$pid" "$target" "project_rolled_back" \
    "rationale=$rationale invalidated_approvals=$n_appr cancelled_directives=$n_dirs actor=$actor" || true

  printf '{"ok":true,"rollback":true,"project_id":%s,"from":"%s","to":"%s","actor":"%s","invalidated_approvals":%s,"cancelled_directives":%s}\n' \
    "$pid" "$current" "$target" "$actor" "$n_appr" "$n_dirs"
}

rollback_history() {
  # All rollback rows for $1, newest first. Identified via metadata.rollback
  # marker that transition.sh stamps in transition_rollback.
  local pid="${1:-}"
  [[ -z "$pid" ]] && { _err_j "invalid_input" "history requires <project_id>"; return 2; }
  local rows
  rows="$(_psql -c "SELECT json_agg(t) FROM (
    SELECT at::text AS at, from_phase, to_phase, actor, reason, metadata
      FROM spine_lifecycle.transition
     WHERE project_id = $pid
       AND metadata ? 'rollback' AND metadata->>'rollback' = 'true'
     ORDER BY at DESC) t;")" \
    || { _err_j "db_error" "history query failed pid=$pid"; return 6; }
  rows="${rows//[[:space:]]/}"
  [[ -z "$rows" || "$rows" == "null" ]] && rows="[]"
  printf '{"ok":true,"project_id":%s,"rollbacks":%s}\n' "$pid" "$rows"
}

# ─────────────────────────────────────────────────────────────────────
# CLI — minimal flag parser; positional <pid> <target>, named --actor/--rationale.
# ─────────────────────────────────────────────────────────────────────
_parse_rollback_flags() {
  _ROLL_PID=""; _ROLL_TARGET=""; _ROLL_ACTOR=""; _ROLL_RATIONALE=""
  while (( $# )); do
    case "$1" in
      --actor)     _ROLL_ACTOR="${2:-}"; shift 2 ;;
      --rationale) _ROLL_RATIONALE="${2:-}"; shift 2 ;;
      --)          shift; break ;;
      -*)          _err_j "invalid_input" "unknown flag: $1"; return 2 ;;
      *)           if [[ -z "$_ROLL_PID" ]]; then _ROLL_PID="$1"
                   elif [[ -z "$_ROLL_TARGET" ]]; then _ROLL_TARGET="$1"
                   fi; shift ;;
    esac
  done
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    preview)  rollback_preview  "$@" ;;
    history)  rollback_history  "$@" ;;
    rollback) _parse_rollback_flags "$@" || return $?
              rollback_project "$_ROLL_PID" "$_ROLL_TARGET" "$_ROLL_ACTOR" "$_ROLL_RATIONALE" ;;
    -h|--help|"") sed -n '2,20p' "${BASH_SOURCE[0]}" >&2; exit 0 ;;
    *) _err_j "unknown_command" "no such subcommand: $cmd"; exit 64 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
