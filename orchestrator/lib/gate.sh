#!/usr/bin/env bash
# gate.sh — Spine orchestrator phase-gate engine (approve / reject /
# request-changes). Implements STORY-1.4.1 (engine), STORY-1.4.4 (three
# actions), STORY-1.4.5 (request-changes routing). HMAC delegated to
# approval.py (STORY-9.3.2); state writes to transition.sh (STORY-9.2.1);
# MCP dispatch to router.sh (STORY-9.4.1). See docs/PRD.md REQ-INIT-1
# FR-5, REQ-INIT-9 FR-3/FR-4; docs/BACKLOG.md EPIC-1.4 / EPIC-9.3.
#
# CLI:
#   gate.sh status          <project_id>
#   gate.sh approve         <project_id> <approver> [notes]
#   gate.sh reject          <project_id> <rejector> <reason>
#   gate.sh request-changes <project_id> <reviewer> <notes> [target_role]
#   gate.sh list-pending    [project_id] [role]
#
# Exit codes: 2=invalid_input, 3=gate_not_satisfied, 4=hmac_invalid,
#   5=transition_failure, 6=router_failure, 7=db_error, 64=unknown_subcommand.

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASES_YAML="${SPINE_PHASES_YAML:-$SCRIPT_DIR/../state/phases.yaml}"
APPROVAL_PY="${SPINE_APPROVAL_PY:-$SCRIPT_DIR/approval.py}"
# shellcheck source=_env_loader.sh
. "$SCRIPT_DIR/_env_loader.sh"
ROUTER_SH="${SPINE_ROUTER_SH:-$SCRIPT_DIR/router.sh}"
TRANSITION_SH="${SPINE_TRANSITION_SH:-$SCRIPT_DIR/transition.sh}"
SPINE_AUDIT_CLI="${SPINE_AUDIT_CLI:-$SCRIPT_DIR/../../shared/audit/audit_record.py}"

# Both source scripts gate main() on BASH_SOURCE==0 → sourcing is side-effect-free.
# shellcheck source=transition.sh
. "$TRANSITION_SH"
# shellcheck source=router.sh
. "$ROUTER_SH"

_log() { printf '%s gate.sh %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${*:2}" >&2; }
# _j <cfg> <key> <pattern>  — extract value of key matching pattern from a flat
# JSON object string. pattern is regex group for capture (no surrounding quotes).
_j() { printf '%s' "$1" | sed -n "s/.*\"$2\":$3.*/\1/p"; }

# _load_gate_config <phase> → JSON cfg object (gate, role_lead, artifact,
# rollback_to, required_approvers[], min_approvers, min_approvals,
# auto_advance). STORY-1.4.6: required_approvers may carry principal
# patterns (role:/user:/group:); min_approvals is the runtime name and
# defaults to min_approvers; auto_advance defaults true.
_load_gate_config() {
  local phase="$1" gate rl art rb apps mn ma aa arr
  gate="$(_phase_field_scalar "$phase" gate)"
  rl="$(_phase_field_scalar "$phase" role_lead)"
  art="$(_phase_field_scalar "$phase" artifact)"
  # _phase_field_list now emits one item per line (F10 fix). `head -n 1`
  # picks the first rollback target; `tr` flattens the approver list into
  # space-separated so the existing IFS=' ' counters below keep working.
  rb="$(_phase_field_list "$phase" rollback_to | head -n 1)"
  apps="$(_phase_field_list "$phase" required_approvers | tr '\n' ' ')"
  mn="$(_phase_field_scalar "$phase" min_approvers)"
  ma="$(_phase_field_scalar "$phase" min_approvals)"
  aa="$(_phase_field_scalar "$phase" auto_advance)"
  [[ -z "$aa" ]] && aa="true"
  # Use a subshell IFS=' ' so word-splitting works (file-level IFS=\n\t).
  local n_apps
  n_apps="$(IFS=' '; set -- $apps; printf '%s' "$#")"
  # min_approvals wins if both set; else fall back to min_approvers; else
  # use len(required_approvers) when the list is non-empty; else 1.
  [[ -z "$ma" ]] && ma="$mn"
  [[ -z "$ma" && -n "$apps" ]] && ma="$n_apps"
  [[ -z "$ma" ]] && ma="1"
  [[ -z "$mn" ]] && mn="$ma"        # keep min_approvers populated for old readers
  arr="[]"
  [[ -n "$apps" ]] && arr="[$(IFS=' '; set -- $apps; printf '"%s",' "$@" | sed 's/,$//')]"
  printf '{"gate":"%s","role_lead":"%s","artifact":"%s","rollback_to":"%s","required_approvers":%s,"min_approvers":%s,"min_approvals":%s,"auto_advance":%s}\n' \
    "$gate" "$rl" "$art" "$rb" "$arr" "$mn" "$ma" "$aa"
}

# _match_principal <approver> <space-separated-required> — STORY-1.4.6.
# Exact match wins; bare approver also matches `user:<approver>`. Prints
# the matched pattern (for dedup), non-zero exit on miss.
_match_principal() {
  local approver="$1" req="$2" p
  for p in $req; do
    [[ "$p" == "$approver" || "$p" == "user:$approver" ]] && { printf '%s' "$p"; return 0; }
  done
  return 1
}

# Invoke approval.py — prefer exec bit when present (transition.sh style),
# else fall back to python3. Errors propagate to the caller via exit code.
_approval_py() {
  if [[ -x "$APPROVAL_PY" ]]; then "$APPROVAL_PY" "$@"
  else python3 "$APPROVAL_PY" "$@"; fi
}

# Distinct approvers whose token survives HMAC verify (skips tampered).
# Plain mode emits "<total_valid>". with-matches mode (STORY-1.4.6) emits
# "<valid>|<matched_required>|<approvers_csv>|<matched_csv>".
_count_valid_approvals() {
  local pid="$1" phase="$2" mode="${3:-plain}" req="${4:-}"
  local line token approver seen=0 matched=0 set="" mset="" mp=""
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    token="${line%%|*}"; approver="${line#*|}"
    [[ -n "$token" ]] && { _approval_py verify --token "$token" --project-id "$pid" \
        --phase "$phase" >/dev/null 2>&1 || continue; }
    [[ ",$set," == *",$approver,"* ]] && continue
    set="${set:+$set,}$approver"; seen=$((seen+1))
    [[ -z "$req" ]] && continue
    mp="$(_match_principal "$approver" "$req")" || continue
    [[ ",$mset," == *",$mp,"* ]] && continue
    mset="${mset:+$mset,}$mp"; matched=$((matched+1))
  done < <(_psql <<SQL 2>/dev/null || true
SELECT COALESCE(token,'')||'|'||approver FROM spine_lifecycle.approval
 WHERE project_id=$pid AND phase='$(_sql_esc "$phase")' AND decision='approved'
   AND (expires_at IS NULL OR expires_at>NOW()) ORDER BY granted_at;
SQL
)
  [[ "$mode" == "with-matches" ]] && { printf '%s|%s|%s|%s' "$seen" "$matched" "$set" "$mset"; return; }
  printf '%s' "$seen"
}

_gate_audit() {
  local pid="$1" phase="$2" action="$3" actor="$4" rationale="${5:-}"
  if [[ -x "$SPINE_AUDIT_CLI" ]]; then
    "$SPINE_AUDIT_CLI" record --project "$pid" --phase "$phase" \
      --subsystem orchestrator --role approver --action "$action" \
      --actor "$actor" --rationale "$rationale" >/dev/null 2>&1 && return 0
  fi
  _audit_row "$pid" "$phase" "$action" "$rationale" || true
}

# Default rollback target = <prefix>_in_progress (plan_approved → plan_in_progress)
# unless phases.yaml declares rollback_to explicitly.
_rollback_target_for() {
  local phase="$1" cfg="$2" tgt; tgt="$(_j "$cfg" rollback_to '"\([^"]*\)"')"
  [[ -n "$tgt" ]] && { printf '%s' "$tgt"; return; }
  printf '%s_in_progress' "${phase%_*}"
}

# ─── STORY-1.4.1 — status ────────────────────────────────────────────
# STORY-1.4.6: surfaces per-required-principal progress + still_needed so
# UI can render "2/3 required approvers signed".
gate_status() {
  local pid="${1:-}"
  [[ -z "$pid" ]] && { _err_json "invalid_input" "status requires <project_id>"; return 2; }
  local phase cfg gate art req mn ma rcv combined valid matched satisfied="false"
  local req_list="" req_progress="[]" still_needed="0" rest="" mcsv="" p sep="" sig
  phase="$(_current_phase "$pid")" || { _err_json "project_not_found" "pid=$pid"; return 2; }
  cfg="$(_load_gate_config "$phase")"
  gate="$(_j "$cfg" gate '"\([^"]*\)"')"; art="$(_j "$cfg" artifact '"\([^"]*\)"')"
  req="$(_j "$cfg" required_approvers '\(\[[^]]*\]\)')"
  mn="$(_j "$cfg" min_approvers '\([0-9]*\)')"
  ma="$(_j "$cfg" min_approvals '\([0-9]*\)')"
  rcv="$(_psql <<SQL 2>/dev/null | tr '\n' ',' | sed 's/,$//'
SELECT DISTINCT approver FROM spine_lifecycle.approval WHERE project_id=$pid
 AND phase='$(_sql_esc "$phase")' AND decision='approved'
 AND (expires_at IS NULL OR expires_at>NOW()) ORDER BY 1;
SQL
)"
  req_list="$(printf '%s' "${req:-[]}" | tr -d '[]"' | tr ',' ' ')"
  combined="$(_count_valid_approvals "$pid" "$phase" with-matches "$req_list")"
  valid="${combined%%|*}"; rest="${combined#*|}"
  matched="${rest%%|*}"; rest="${rest#*|}"; mcsv="${rest#*|}"
  if [[ -z "$gate" || "$gate" == "auto" ]]; then satisfied="true"
  elif [[ -n "$req_list" ]]; then
    (( matched >= ${ma:-1} )) && satisfied="true"
    still_needed=$(( ma - matched )); (( still_needed < 0 )) && still_needed=0
    req_progress="["
    for p in $req_list; do
      sig="false"; [[ ",$mcsv," == *",$p,"* ]] && sig="true"
      req_progress+="${sep}{\"principal\":\"$p\",\"signed\":$sig}"; sep=","
    done
    req_progress+="]"
  else
    (( valid >= ${ma:-1} )) && satisfied="true"
    still_needed=$(( ma - valid )); (( still_needed < 0 )) && still_needed=0
  fi
  printf '{"ok":true,"project_id":%s,"phase":"%s","gate":"%s","artifact":"%s","required_approvers":%s,"min_approvers":%s,"min_approvals":%s,"approvals_received":"%s","valid_approvals":%s,"matched_required":%s,"still_needed":%s,"required_progress":%s,"satisfied":%s}\n' \
    "$pid" "$phase" "${gate:-none}" "$art" "${req:-[]}" "${mn:-1}" "${ma:-1}" "$rcv" "$valid" "$matched" "$still_needed" "$req_progress" "$satisfied"
}

# ─── STORY-1.4.4 (a) — approve ───────────────────────────────────────
# STORY-1.4.6: validates the approver against required_approvers principal
# patterns (role:/user:/group:/bare). Gate is satisfied only when the count
# of distinct *matched required principals* >= min_approvals.
gate_approve() {
  local pid="${1:-}" approver="${2:-}" notes="${3:-}"
  [[ -z "$pid" || -z "$approver" ]] && {
    _err_json "invalid_input" "approve requires <project_id> <approver>"; return 2; }
  local phase cfg req mn ma aa args resp aid combined valid matched rest=""
  local req_list="" still_needed="0" satisfied="false" advanced="false" new=""
  phase="$(_current_phase "$pid")" || { _err_json "project_not_found" "pid=$pid"; return 2; }
  cfg="$(_load_gate_config "$phase")"
  req="$(_j "$cfg" required_approvers '\(\[[^]]*\]\)')"
  mn="$(_j "$cfg" min_approvers '\([0-9]*\)')"
  ma="$(_j "$cfg" min_approvals '\([0-9]*\)')"
  aa="$(_j "$cfg" auto_advance '\([a-z]*\)')"
  req_list="$(printf '%s' "${req:-[]}" | tr -d '[]"' | tr ',' ' ')"

  if [[ -n "$req_list" ]] && ! _match_principal "$approver" "$req_list" >/dev/null; then
    _err_json "hmac_invalid" "approver '$approver' does not match any required principal" \
      "{\"required\":$req}"; return 4
  fi

  args=(grant --project-id "$pid" --phase "$phase" --approver "$approver")
  [[ -n "$notes" ]] && args+=(--notes "$notes")
  if ! resp="$(_approval_py "${args[@]}" 2>&1)"; then
    _err_json "hmac_invalid" "approval.py grant failed" "{\"detail\":${resp:-null}}"; return 4
  fi
  aid="$(printf '%s' "$resp" | sed -n 's/.*"approval_id":[[:space:]]*\([0-9]*\).*/\1/p')"

  combined="$(_count_valid_approvals "$pid" "$phase" with-matches "$req_list")"
  valid="${combined%%|*}"; rest="${combined#*|}"; matched="${rest%%|*}"
  if [[ -n "$req_list" ]]; then
    (( matched >= ${ma:-1} )) && satisfied="true"
    still_needed=$(( ma - matched )); (( still_needed < 0 )) && still_needed=0
  else
    (( valid >= ${ma:-1} )) && satisfied="true"
    still_needed=$(( ma - valid )); (( still_needed < 0 )) && still_needed=0
  fi

  if [[ "$satisfied" == "true" && "$aa" == "true" ]]; then
    new="$(_phase_field_list "$phase" next | head -n 1)"
    if [[ -n "$new" ]] \
        && transition_execute "$pid" "$new" "gate.approve:$approver" \
             "gate satisfied (matched=$matched/${ma:-1})" >/dev/null; then
      advanced="true"
    elif [[ -n "$new" ]]; then
      _log WARN "approval recorded but transition $phase->$new failed pid=$pid"
    fi
  fi

  _gate_audit "$pid" "$phase" "approval_granted" "$approver" "approval_id=${aid:-?}"
  printf '{"ok":true,"approval_id":%s,"required_approvers":%s,"approvals_received":%s,"matched_required":%s,"still_needed":%s,"gate_satisfied":%s,"phase_advanced":%s,"new_phase":"%s","auto_advance":%s}\n' \
    "${aid:-null}" "${req:-[]}" "$valid" "$matched" "$still_needed" "$satisfied" "$advanced" "$new" "${aa:-true}"
}

# ─── STORY-1.4.4 (b) — reject ────────────────────────────────────────
# Schema CHECK currently only allows active|paused|terminated|completed.
# We encode "blocked" as paused + metadata.blocked=true (see README).
gate_reject() {
  local pid="${1:-}" rejector="${2:-}" reason="${3:-}"
  [[ -z "$pid" || -z "$rejector" || -z "$reason" ]] && {
    _err_json "invalid_input" "reject requires <project_id> <rejector> <reason>"; return 2; }
  local phase cfg rb rid status="blocked" rolled=""
  phase="$(_current_phase "$pid")" || { _err_json "project_not_found" "pid=$pid"; return 2; }
  cfg="$(_load_gate_config "$phase")"; rb="$(_j "$cfg" rollback_to '"\([^"]*\)"')"

  rid="$(_psql <<SQL || true
INSERT INTO spine_lifecycle.approval (project_id,phase,artifact_ref,approver,decision,notes)
VALUES ($pid,'$(_sql_esc "$phase")','phase:$(_sql_esc "$phase")',
        '$(_sql_esc "$rejector")','rejected','$(_sql_esc "$reason")') RETURNING id;
SQL
)"; rid="${rid//[[:space:]]/}"
  [[ -z "$rid" ]] && { _err_json "db_error" "rejection insert failed pid=$pid"; return 7; }

  if [[ -n "$rb" ]] \
      && transition_rollback "$pid" "$rb" "gate.reject:$rejector" "$reason" \
           >/dev/null 2>&1; then
    rolled="$rb"; status="active"
  else
    _psql <<SQL || { _err_json "db_error" "could not mark blocked pid=$pid"; return 7; }
UPDATE spine_lifecycle.project
   SET status='paused',
       metadata=metadata||jsonb_build_object(
         'blocked',true,'blocked_reason','$(_sql_esc "$reason")',
         'blocked_by','gate.reject:$(_sql_esc "$rejector")',
         'blocked_phase','$(_sql_esc "$phase")','blocked_at',NOW()::text)
 WHERE id=$pid;
SQL
  fi

  _gate_audit "$pid" "$phase" "gate_rejected" "$rejector" "$reason"
  printf '{"ok":true,"rejection_id":%s,"project_status":"%s","rollback_to":"%s"}\n' \
    "$rid" "$status" "$rolled"
}

# ─── STORY-1.4.5 — request-changes (routes back to producing role) ───
# Sequence: insert decision → roll back to *_in_progress → MCP re-dispatch
# with parent_directive_id of the prior producing directive.
gate_request_changes() {
  local pid="${1:-}" reviewer="${2:-}" notes="${3:-}" target_role="${4:-}"
  [[ -z "$pid" || -z "$reviewer" || -z "$notes" ]] && {
    _err_json "invalid_input" "request-changes requires <project_id> <reviewer> <notes>"; return 2; }
  local phase cfg art role sub rb parent rid directive resp new_did
  phase="$(_current_phase "$pid")" || { _err_json "project_not_found" "pid=$pid"; return 2; }
  cfg="$(_load_gate_config "$phase")"
  art="$(_j "$cfg" artifact '"\([^"]*\)"')"; role="$(_j "$cfg" role_lead '"\([^"]*\)"')"
  [[ -n "$target_role" ]] && role="$target_role"
  rb="$(_rollback_target_for "$phase" "$cfg")"

  rid="$(_psql <<SQL || true
INSERT INTO spine_lifecycle.approval (project_id,phase,artifact_ref,approver,decision,notes)
VALUES ($pid,'$(_sql_esc "$phase")','phase:$(_sql_esc "$phase")',
        '$(_sql_esc "$reviewer")','request_changes','$(_sql_esc "$notes")') RETURNING id;
SQL
)"; rid="${rid//[[:space:]]/}"
  [[ -z "$rid" ]] && { _err_json "db_error" "request_changes insert failed pid=$pid"; return 7; }

  sub="$(route_decide_subsystem "$rb" 2>/dev/null || true)"
  [[ -z "$sub" ]] && sub="$(route_decide_subsystem "$phase" 2>/dev/null || true)"
  parent="$(_psql <<SQL 2>/dev/null || true
SELECT directive_ref FROM spine_lifecycle.route_history
 WHERE project_id=$pid AND subsystem='$(_sql_esc "$sub")'
 ORDER BY dispatched_at DESC LIMIT 1;
SQL
)"; parent="${parent//[[:space:]]/}"

  directive="$(printf 'USER FEEDBACK on %s: %s\n\nPlease revise and resubmit.' \
                 "${art:-artifact}" "$notes")"

  # Roll back BEFORE dispatch so route_history.phase reflects the *_in_progress phase.
  if ! transition_rollback "$pid" "$rb" "gate.request_changes:$reviewer" \
        "request-changes by $reviewer" >/dev/null 2>&1; then
    _err_json "transition_failure" "rollback $phase->$rb failed pid=$pid" \
      "{\"request_id\":$rid}"; return 5
  fi

  resp="$(route_dispatch_to_subsystem "$sub" "$role" "$directive" "$pid" "$parent" 2>&1)" || {
    _err_json "router_failure" "route_dispatch_to_subsystem failed" "{\"detail\":${resp:-null}}"; return 6; }
  new_did="$(printf '%s' "$resp" | sed -n 's/.*"directive_id":"\([^"]*\)".*/\1/p')"
  [[ -z "$new_did" ]] && {
    _err_json "router_failure" "router reply missing directive_id" "{\"response\":${resp:-null}}"; return 6; }

  _gate_audit "$pid" "$phase" "gate_request_changes" "$reviewer" "$notes (new_did=$new_did)"
  printf '{"ok":true,"request_id":%s,"new_directive_id":"%s","project_status":"active","rolled_back_to":"%s","target_role":"%s","parent_directive_id":"%s"}\n' \
    "$rid" "$new_did" "$rb" "$role" "${parent:-}"
}

# ─── STORY-1.4.2 helper — approval queue feed ────────────────────────
gate_list_pending() {
  local pid="${1:-}" role="${2:-}" filter="" rows body=""
  [[ -n "$pid"  ]] && filter+=" AND p.id=$pid"
  [[ -n "$role" ]] && filter+=" AND lower(p.metadata->>'role_lead_hint')=lower('$(_sql_esc "$role")')"
  rows="$(_psql <<SQL 2>/dev/null || true
SELECT json_build_object(
  'project_id',p.id,'project_uuid',p.project_uuid,'name',p.name,
  'phase',p.current_phase,'status',p.status,
  'artifact_ref',COALESCE(a.artifact_ref,'phase:'||p.current_phase),
  'approvals_received',COALESCE((
    SELECT json_agg(DISTINCT approver) FROM spine_lifecycle.approval
     WHERE project_id=p.id AND phase=p.current_phase AND decision='approved'
       AND (expires_at IS NULL OR expires_at>NOW())),'[]'::json),
  'last_decision',a.decision,'last_decided_at',a.granted_at)::text
 FROM spine_lifecycle.project p
 LEFT JOIN LATERAL (SELECT decision,granted_at,artifact_ref FROM spine_lifecycle.approval
   WHERE project_id=p.id AND phase=p.current_phase
   ORDER BY granted_at DESC LIMIT 1) a ON TRUE
WHERE p.status IN ('active','paused') $filter ORDER BY p.updated_at DESC;
SQL
)"
  while IFS= read -r line; do [[ -z "$line" ]] && continue; body+="${body:+,}$line"; done <<< "$rows"
  printf '{"ok":true,"pending":[%s]}\n' "$body"
}

# ─── CLI ─────────────────────────────────────────────────────────────
main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    status)          gate_status          "$@" ;;
    approve)         gate_approve         "$@" ;;
    reject)          gate_reject          "$@" ;;
    request-changes) gate_request_changes "$@" ;;
    list-pending)    gate_list_pending    "$@" ;;
    -h|--help|"") sed -n '2,17p' "${BASH_SOURCE[0]}" >&2; exit 0 ;;
    *) _err_json "unknown_command" "no such subcommand: $cmd"; exit 64 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
