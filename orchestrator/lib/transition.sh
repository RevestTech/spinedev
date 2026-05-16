#!/usr/bin/env bash
# transition.sh — Spine orchestrator state-machine transition engine.
#
# Implements STORY-9.2.1 (transition engine) and STORY-9.2.2 (invalid
# transitions rejected with a clear, structured error). See:
#   - docs/PRD.md REQ-INIT-9 (FR-3 transition engine, FR-4 HMAC gates, NFR-1
#     ≤100ms latency)
#   - docs/BACKLOG.md EPIC-9.2 (engine), EPIC-9.3 (gates), EPIC-9.7 (audit)
#   - orchestrator/state/phases.yaml (canonical phase manifest)
#   - db/flyway/sql/V14__spine_lifecycle_schema.sql (target schema)
#
# Bash-only. Python is invoked only as a subprocess for HMAC verification
# (orchestrator/lib/approval.py — stubbed for this skeleton).
#
# CLI:
#   transition.sh validate    <project_id> <target_phase>
#   transition.sh gate-check  <project_id> <target_phase>
#   transition.sh execute     <project_id> <target_phase> <actor> [rationale]
#   transition.sh rollback    <project_id> <target_phase> <actor> <rationale>

set -euo pipefail
IFS=$'\n\t'

# ─────────────────────────────────────────────────────────────────────
# Globals & helpers
# ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASES_YAML="${SPINE_PHASES_YAML:-$SCRIPT_DIR/../state/phases.yaml}"
APPROVAL_PY="${SPINE_APPROVAL_PY:-$SCRIPT_DIR/approval.py}"
SPINE_DB_URL="${SPINE_DB_URL:-postgresql://spine:spine@localhost:33000/spine}"

# Single-roundtrip psql wrapper. `-1` wraps the input in a single transaction
# (atomicity, NFR-1); `ON_ERROR_STOP=1` aborts immediately so we never write
# partial state. `-A -t` keeps stdout machine-parseable for the read helpers.
_psql() {
  psql "$SPINE_DB_URL" -v ON_ERROR_STOP=1 -A -t -X -q "$@"
}

_psql_tx() {
  # `-1` only applies when SQL is provided via -c/-f; we feed via stdin so we
  # bracket the script ourselves with BEGIN/COMMIT/ROLLBACK.
  psql "$SPINE_DB_URL" -v ON_ERROR_STOP=1 -A -t -X -q
}

_log() {
  # Structured stderr log: ISO-8601 ts + level + message. Matches the
  # `echo … >&2` convention used in lib/team-agent-daemon.sh.
  printf '%s transition.sh %s %s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${*:2}" >&2
}

_err_json() {
  # Structured error to stdout so callers can `jq` it. Stderr gets the human
  # log line. Caller decides exit code.
  local code="$1" message="$2" extra_json="${3:-{\}}"
  printf '{"ok":false,"code":"%s","message":%s,"extra":%s}\n' \
    "$code" "$(_jq_str "$message")" "$extra_json"
  _log ERROR "$code: $message"
}

_jq_str() {
  # Minimal JSON string escape (no jq dependency).
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' \
    | awk 'BEGIN{printf "\""} {printf "%s", $0} END{printf "\""}'
}

# ─────────────────────────────────────────────────────────────────────
# Phase manifest reader
# ─────────────────────────────────────────────────────────────────────

_load_phase_def() {
  # Prints the YAML block for phase $1 to stdout. Prefers `yq` (gives JSON);
  # falls back to grep/awk scoping by "- id: <phase>" to "  - id:" or EOF.
  local phase="$1"
  if command -v yq >/dev/null 2>&1; then
    yq -o=json ".phases[] | select(.id == \"$phase\")" "$PHASES_YAML"
    return
  fi
  awk -v want="$phase" '
    /^[[:space:]]*-[[:space:]]+id:[[:space:]]+/ {
      in_block = ($0 ~ ("id:[[:space:]]+" want "([[:space:]]|$)"))
      if (in_block) { print; next }
    }
    in_block {
      if ($0 ~ /^[[:space:]]*-[[:space:]]+id:[[:space:]]+/) { in_block = 0; exit }
      print
    }
  ' "$PHASES_YAML"
}

_phase_field_list() {
  # _phase_field_list <phase> <field>  → space-separated list of values for
  # `next:` / `rollback_to:` style arrays. Tolerates `[a, b]` and block form.
  local block field
  block="$(_load_phase_def "$1")"
  field="$2"
  printf '%s\n' "$block" \
    | awk -v f="$field" '
        $0 ~ "^[[:space:]]*" f ":" {
          sub("^[[:space:]]*" f ":[[:space:]]*", "")
          gsub(/[\[\],]/, " "); print; exit
        }'
}

_phase_field_scalar() {
  # _phase_field_scalar <phase> <field>  → scalar value (or empty).
  local block field
  block="$(_load_phase_def "$1")"
  field="$2"
  printf '%s\n' "$block" \
    | awk -v f="$field" '
        $0 ~ "^[[:space:]]*" f ":" {
          sub("^[[:space:]]*" f ":[[:space:]]*", "")
          gsub(/["\047]/, ""); print; exit
        }'
}

_in_list() {
  # _in_list <needle> <space-separated list> → 0 if present.
  local needle="$1"; shift
  local item
  for item in $*; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

_current_phase() {
  # Cheap denormalised read from project.current_phase.
  local pid="$1" out
  out="$(_psql -c "SELECT current_phase FROM spine_lifecycle.project WHERE id = $pid;")" || return 1
  out="${out//[[:space:]]/}"
  [[ -z "$out" ]] && return 1
  printf '%s' "$out"
}

# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────

transition_validate() {
  local pid="$1" target="$2" current allowed
  current="$(_current_phase "$pid")" || {
    _err_json "project_not_found" "no project row for id=$pid"
    return 2
  }
  if [[ "$current" == "$target" ]]; then
    _err_json "noop_transition" "project already in phase '$target'"
    return 3
  fi
  allowed="$(_phase_field_list "$current" next)"
  if ! _in_list "$target" "$allowed"; then
    _err_json "rejected_invalid" \
      "phase '$current' cannot transition directly to '$target'" \
      "{\"from\":\"$current\",\"to\":\"$target\",\"allowed_next\":\"$(echo "$allowed" | xargs)\"}"
    return 4
  fi
  printf '{"ok":true,"from":"%s","to":"%s"}\n' "$current" "$target"
}

transition_gate_check() {
  local pid="$1" target="$2" gate token expires_at
  gate="$(_phase_field_scalar "$target" gate)"
  if [[ -z "$gate" ]]; then
    printf '{"ok":true,"gate":null}\n'
    return 0
  fi
  # Most recent non-expired `approved` row wins; multi-approver support
  # (STORY-9.3.3) layers a COUNT(*) >= min_approvers check above this.
  read -r token expires_at < <(_psql <<SQL
SELECT COALESCE(token,''), COALESCE(expires_at::text,'')
FROM   spine_lifecycle.approval
WHERE  project_id = $pid
  AND  phase = '$target'
  AND  decision = 'approved'
  AND  (expires_at IS NULL OR expires_at > NOW())
ORDER  BY granted_at DESC
LIMIT  1;
SQL
)
  if [[ -z "$token" ]]; then
    _err_json "rejected_gate" \
      "phase '$target' requires gate '$gate' but no valid approval found" \
      "{\"gate\":\"$gate\"}"
    return 5
  fi
  # HMAC verification is delegated to a Python helper for crypto-correctness
  # (STORY-9.3.2). Stubbed: assume present + exit 0 = verified.
  if [[ -x "$APPROVAL_PY" ]]; then
    if ! "$APPROVAL_PY" verify --token "$token" --project "$pid" --phase "$target" >/dev/null 2>&1; then
      _err_json "rejected_gate" "approval token HMAC verification failed" \
        "{\"gate\":\"$gate\"}"
      return 5
    fi
  else
    _log WARN "approval.py not executable at $APPROVAL_PY — skipping HMAC verify (skeleton mode)"
  fi
  printf '{"ok":true,"gate":"%s"}\n' "$gate"
}

transition_execute() {
  local pid="$1" target="$2" actor="$3" rationale="${4:-}"
  transition_validate "$pid" "$target" >/dev/null || return $?
  transition_gate_check "$pid" "$target" >/dev/null || return $?
  local current
  current="$(_current_phase "$pid")"
  # Atomic: close prior phase_history row, open new one, update denormalised
  # cache, write transition (= audit row per V14 schema header). All or
  # nothing — psql ROLLBACKs on first error thanks to ON_ERROR_STOP.
  _psql_tx <<SQL || { _err_json "db_error" "transition transaction failed for pid=$pid"; return 6; }
BEGIN;
UPDATE spine_lifecycle.phase_history
   SET exited_at = NOW(), outcome = 'advanced'
 WHERE project_id = $pid AND exited_at IS NULL;
INSERT INTO spine_lifecycle.phase_history (project_id, phase)
     VALUES ($pid, '$target');
UPDATE spine_lifecycle.project
   SET current_phase = '$target'
 WHERE id = $pid;
INSERT INTO spine_lifecycle.transition
            (project_id, from_phase, to_phase, actor, decision, reason)
     VALUES ($pid, '$current', '$target', '$actor', 'allowed',
             NULLIF('$(printf '%s' "$rationale" | sed "s/'/''/g")', ''));
COMMIT;
SQL
  _audit_row "$pid" "$target" "transition_advanced" "$rationale" || true
  printf '{"ok":true,"from":"%s","to":"%s","actor":"%s"}\n' "$current" "$target" "$actor"
}

transition_rollback() {
  local pid="$1" target="$2" actor="$3" rationale="$4"
  # rollback_policy.requires_rationale = true (phases.yaml).
  if [[ -z "$rationale" ]]; then
    _err_json "rationale_required" "rollback requires non-empty rationale"
    return 7
  fi
  local current allowed
  current="$(_current_phase "$pid")" || {
    _err_json "project_not_found" "no project row for id=$pid"; return 2;
  }
  allowed="$(_phase_field_list "$current" rollback_to)"
  if ! _in_list "$target" "$allowed"; then
    _err_json "rejected_invalid" \
      "phase '$current' cannot rollback to '$target'" \
      "{\"from\":\"$current\",\"to\":\"$target\",\"allowed_rollback\":\"$(echo "$allowed" | xargs)\"}"
    return 4
  fi
  _psql_tx <<SQL || { _err_json "db_error" "rollback transaction failed for pid=$pid"; return 6; }
BEGIN;
UPDATE spine_lifecycle.phase_history
   SET exited_at = NOW(), outcome = 'rolled_back'
 WHERE project_id = $pid AND exited_at IS NULL;
INSERT INTO spine_lifecycle.phase_history (project_id, phase)
     VALUES ($pid, '$target');
UPDATE spine_lifecycle.project
   SET current_phase = '$target'
 WHERE id = $pid;
INSERT INTO spine_lifecycle.transition
            (project_id, from_phase, to_phase, actor, decision, reason, metadata)
     VALUES ($pid, '$current', '$target', '$actor', 'allowed',
             '$(printf '%s' "$rationale" | sed "s/'/''/g")',
             '{"rollback":true}'::jsonb);
COMMIT;
SQL
  _audit_row "$pid" "$target" "transition_rolled_back" "$rationale" || true
  printf '{"ok":true,"rollback":true,"from":"%s","to":"%s","actor":"%s"}\n' \
    "$current" "$target" "$actor"
}

_audit_row() {
  # Best-effort write into the unified audit table (EPIC-9.7). The
  # `transition` row IS the primary audit feed per V14 schema header, so this
  # is additive: skip silently if `spine_audit.events` is not yet present.
  local pid="$1" phase="$2" action="$3" rationale="${4:-}"
  _psql <<SQL 2>/dev/null || return 0
DO \$\$ BEGIN
  IF to_regclass('spine_audit.events') IS NOT NULL THEN
    INSERT INTO spine_audit.events (project_id, phase, action, rationale)
    VALUES ($pid, '$phase', '$action',
            NULLIF('$(printf '%s' "$rationale" | sed "s/'/''/g")', ''));
  END IF;
END \$\$;
SQL
}

# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    validate)    transition_validate    "$@" ;;
    gate-check)  transition_gate_check  "$@" ;;
    execute)     transition_execute     "$@" ;;
    rollback)    transition_rollback    "$@" ;;
    -h|--help|"")
      sed -n '2,18p' "${BASH_SOURCE[0]}" >&2
      exit 0
      ;;
    *)
      _err_json "unknown_command" "no such subcommand: $cmd"
      exit 64
      ;;
  esac
}

# Only run main when executed, not when sourced (so the helper functions
# remain available for in-process use by future orchestrator modules).
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
