#!/usr/bin/env bash
# remediation.sh — Spine orchestrator verify-fail auto-remediation engine.
#
# Implements STORY-9.8.1 (verify failure -> orchestrator auto-generates a
# remediation directive -> routes back to Build with parent_directive_id
# linking the loop) and STORY-9.8.2 (max-retry policy). See:
#   - docs/PRD.md REQ-INIT-9 FR-9 (failure handling & re-routing)
#   - docs/PRD.md REQ-INIT-8 FR-4 (VerifyFindings shape)
#   - docs/BACKLOG.md EPIC-9.8
#   - orchestrator/state/phases.yaml (`retry_policy.verify_build_loop_max`)
#   - db/flyway/sql/V14__spine_lifecycle_schema.sql (route_history, transition)
#
# Architectural rule: we DO NOT re-implement dispatch or transition logic.
# We delegate to `router.sh route_dispatch_remediation` (MCP chokepoint)
# and `transition.sh transition_execute` (state-machine writer). This file
# is the policy layer that decides WHAT remediation to compose and WHETHER
# the retry budget is exhausted.
#
# CLI:
#   remediation.sh compose      <failed_directive_id> <findings_json>
#   remediation.sh check-retry  <project_id> <current_phase>
#   remediation.sh dispatch     <failed_directive_id> <findings_json>
#   remediation.sh surface      <project_id> <reason>

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASES_YAML="${SPINE_PHASES_YAML:-$SCRIPT_DIR/../state/phases.yaml}"
# shellcheck source=_env_loader.sh
. "$SCRIPT_DIR/_env_loader.sh"
ROUTER_SH="${SPINE_ROUTER_SH:-$SCRIPT_DIR/router.sh}"
TRANSITION_SH="${SPINE_TRANSITION_SH:-$SCRIPT_DIR/transition.sh}"

REMEDIATION_DIRECTIVE_MAX_CHARS="${SPINE_REMEDIATION_DIRECTIVE_MAX_CHARS:-2000}"
REMEDIATION_BODY_MAX_CHARS="${SPINE_REMEDIATION_BODY_MAX_CHARS:-1800}"
REMEDIATION_DEFAULT_TARGET="${SPINE_REMEDIATION_DEFAULT_TARGET:-build}"
REMEDIATION_DEFAULT_LOOP_MAX="${SPINE_REMEDIATION_DEFAULT_LOOP_MAX:-5}"

# Source helpers from router.sh + transition.sh so we can reuse their state
# without re-implementing dispatch / state-machine logic. Both scripts gate
# main() on BASH_SOURCE==0 so sourcing is side-effect free.
# shellcheck source=router.sh
. "$ROUTER_SH"
# shellcheck source=transition.sh
. "$TRANSITION_SH"

_psql() { psql "$SPINE_DB_URL" -v ON_ERROR_STOP=1 -A -t -X -q "$@"; }
_log()  { printf '%s remediation.sh %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${*:2}" >&2; }
_sql_esc() { printf '%s' "$1" | sed "s/'/''/g"; }
_err_json() {
  local code="$1" message="$2" extra="${3:-{\}}"
  printf '{"ok":false,"code":"%s","message":"%s","extra":%s}\n' \
    "$code" "${message//\"/\\\"}" "$extra"
  _log ERROR "$code: $message"
}

# ─────────────────────────────────────────────────────────────────────
# Findings summarizer — turns a VerifyFindings JSON array into the body
# of the remediation directive. Sorts by severity, deduplicates by
# (file, rule), truncates with an explicit "(+N more)" tail.
# ─────────────────────────────────────────────────────────────────────

_summarize_findings() {
  local findings_json="$1" max_chars="${2:-$REMEDIATION_BODY_MAX_CHARS}"
  [[ -z "$findings_json" || "$findings_json" == "null" ]] && {
    printf 'No findings supplied.\n'; return 0
  }

  if command -v jq >/dev/null 2>&1; then
    # Sort by severity weight DESC, dedupe by (file|rule). One line per
    # finding: `[SEV] file:line  rule — message  | fix: hint`.
    printf '%s' "$findings_json" | jq -r --argjson max "$max_chars" '
      def sev_rank:
        if   . == "critical" then 0
        elif . == "high"     then 1
        elif . == "medium"   then 2
        elif . == "low"      then 3
        else 4 end;
      ( . // [] )
      | map(. + {_sev: (.severity // "low" | ascii_downcase)})
      | sort_by(._sev | sev_rank)
      | unique_by([(.file // ""), (.rule // "")])
      | map(
          "[\(.severity // "low" | ascii_upcase)] "
          + (.file // "<unknown>")
          + (if .line then ":\(.line)" else "" end)
          + "  " + (.rule // "no-rule")
          + " — " + (.message // "(no message)")
          + (if .fix_hint then "  | fix: \(.fix_hint)" else "" end)
        )
      | . as $all
      | (
          (reduce $all[] as $l ({acc:"", n:0, kept:0};
            if (.acc | length) + ($l | length) + 1 <= $max
              then {acc: (.acc + $l + "\n"), n: (.n + 1), kept: (.kept + 1)}
              else {acc: .acc, n: (.n + 1), kept: .kept}
            end))
          | .acc
            + (if ($all | length) > .kept
                then "(+\($all | length - .kept) more finding(s) omitted)\n"
                else "" end)
        )
    ' 2>/dev/null || {
      _log WARN "jq parse failed; falling back to raw body"
      # SIGPIPE-tolerant: read into a var, slice in-shell.
      local raw="$findings_json"
      printf '%s\n' "${raw:0:$max_chars}"
    }
    return 0
  fi

  # Awk fallback: minimal — no severity sort, no dedupe, just truncate.
  # Prints lines up to max chars, then a single "(truncated...)" tail.
  printf '%s\n' "$findings_json" \
    | awk -v max="$max_chars" '
        BEGIN{n=0; done=0}
        { if (done) next;
          if (n + length($0) + 1 > max) { print "(truncated; install jq for full summary)"; done=1; next }
          print; n += length($0) + 1 }'
}

# ─────────────────────────────────────────────────────────────────────
# Compose — read original Build directive from route_history, build the
# remediation directive body, return JSON {directive, target, parent_id,
# project_id, role}. Pure: no DB writes here.
# ─────────────────────────────────────────────────────────────────────

remediation_compose_directive() {
  local failed_did="${1:-}" findings_json="${2:-}"
  [[ -z "$failed_did" || -z "$findings_json" ]] && {
    _err_json "invalid_input" "compose requires <failed_directive_id> <findings_json>"; return 2
  }

  local row pid role subsystem
  row="$(_psql -c "SELECT project_id::text || '|' || role || '|' || subsystem
                     FROM spine_lifecycle.route_history
                    WHERE directive_ref = '$(_sql_esc "$failed_did")'
                    ORDER BY dispatched_at DESC LIMIT 1;")" \
    || { _err_json "db_error" "lookup failed for $failed_did"; return 6; }
  row="${row//[[:space:]]/}"
  [[ -z "$row" ]] && {
    _err_json "invalid_input" "no route_history row for directive $failed_did"; return 2
  }
  pid="${row%%|*}"; row="${row#*|}"
  role="${row%%|*}"; subsystem="${row#*|}"

  local body
  body="$(_summarize_findings "$findings_json" "$REMEDIATION_BODY_MAX_CHARS")"

  # Header makes the loop self-documenting in the audit log; body carries
  # actionable per-finding lines. Always cite parent_directive_id.
  local directive
  directive=$(printf 'REMEDIATE (verify-fail) parent=%s prior_subsystem=%s\n%s\n%s' \
                "$failed_did" "$subsystem" \
                "Address the following findings and re-emit a BuildArtifact:" \
                "$body")

  # Hard cap on directive length so MCP payload stays well under typical
  # tool-call envelope limits. We trim the body (not the header) so the
  # parent_directive_id always survives.
  if (( ${#directive} > REMEDIATION_DIRECTIVE_MAX_CHARS )); then
    directive="${directive:0:REMEDIATION_DIRECTIVE_MAX_CHARS}
(... directive truncated at ${REMEDIATION_DIRECTIVE_MAX_CHARS} chars)"
  fi

  # JSON-escape the directive for stdout. Single-line, no embedded newlines
  # — we use \n escapes so jq consumers parse it cleanly.
  local esc
  esc="$(printf '%s' "$directive" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' \
                                        -e ':a;N;$!ba;s/\n/\\n/g')"
  printf '{"ok":true,"project_id":%s,"role":"%s","target":"%s","parent_directive_id":"%s","directive":"%s"}\n' \
    "$pid" "$role" "$REMEDIATION_DEFAULT_TARGET" "$failed_did" "$esc"
}

# ─────────────────────────────────────────────────────────────────────
# Retry budget — counts prior verify→build loops for this project via
# `transition` table (NOT a counter column; the audit table is the source
# of truth so the budget survives crashes / replays).
# ─────────────────────────────────────────────────────────────────────

_phases_yaml_loop_max() {
  local v=""
  if command -v yq >/dev/null 2>&1; then
    v="$(yq -r '.transitions_metadata.retry_policy.verify_build_loop_max // ""' "$PHASES_YAML" 2>/dev/null)"
  fi
  if [[ -z "$v" || "$v" == "null" ]]; then
    # Scope to the `retry_policy:` block by indentation: capture the block's
    # leading indent and exit once we see a same-or-less-indented key.
    v="$(awk '
      /^[[:space:]]*retry_policy:/ {
        match($0, /^[[:space:]]*/); rp_indent = RLENGTH; in_rp = 1; next
      }
      in_rp {
        match($0, /^[[:space:]]*/)
        if ($0 ~ /^[[:space:]]*[A-Za-z_]/ && RLENGTH <= rp_indent) { in_rp = 0; next }
        if ($0 ~ /verify_build_loop_max:/) {
          sub(/.*verify_build_loop_max:[[:space:]]*/, "")
          sub(/[[:space:]]*#.*/, ""); print; exit
        }
      }' "$PHASES_YAML" 2>/dev/null)"
  fi
  v="${v//[[:space:]]/}"
  [[ -z "$v" ]] && v="$REMEDIATION_DEFAULT_LOOP_MAX"
  printf '%s' "$v"
}

remediation_check_retry_budget() {
  local pid="${1:-}" phase="${2:-}"
  [[ -z "$pid" ]] && { _err_json "invalid_input" "check-retry requires <project_id> [current_phase]"; return 2; }

  local cap count
  cap="$(_phases_yaml_loop_max)"
  count="$(_psql -c "SELECT COUNT(*) FROM spine_lifecycle.transition
                      WHERE project_id = $pid
                        AND from_phase = 'verify_in_progress'
                        AND to_phase   = 'build_in_progress';")" \
    || { _err_json "db_error" "failed to count verify->build loops for pid=$pid"; return 6; }
  count="${count//[[:space:]]/}"; count="${count:-0}"

  if (( count >= cap )); then
    _err_json "retry_budget_exceeded" \
      "project $pid hit verify_build_loop_max ($cap) — surface to user" \
      "{\"project_id\":$pid,\"loops\":$count,\"cap\":$cap,\"phase\":\"$phase\"}"
    return 3
  fi
  printf '{"ok":true,"project_id":%s,"loops":%s,"cap":%s,"remaining":%s}\n' \
    "$pid" "$count" "$cap" "$((cap - count))"
}

# ─────────────────────────────────────────────────────────────────────
# Dispatch — top-level: compose -> retry check -> route_dispatch_remediation
# -> transition project from verify_in_progress back to build_in_progress.
# ─────────────────────────────────────────────────────────────────────

remediation_dispatch() {
  local failed_did="${1:-}" findings_json="${2:-}"
  [[ -z "$failed_did" || -z "$findings_json" ]] && {
    _err_json "invalid_input" "dispatch requires <failed_directive_id> <findings_json>"; return 2
  }

  # Look up the parent dispatch directly so we avoid round-tripping the
  # composed directive through JSON (which would double-escape quotes when
  # router.sh re-quotes for MCP). compose_directive remains the single
  # source of truth for body composition.
  local row pid role target parent directive
  row="$(_psql -c "SELECT project_id::text || '|' || role
                     FROM spine_lifecycle.route_history
                    WHERE directive_ref = '$(_sql_esc "$failed_did")'
                    ORDER BY dispatched_at DESC LIMIT 1;")" \
    || { _err_json "db_error" "lookup failed for $failed_did"; return 6; }
  row="${row//[[:space:]]/}"
  [[ -z "$row" ]] && { _err_json "invalid_input" "no route_history row for $failed_did"; return 2; }
  pid="${row%%|*}"; role="${row#*|}"
  target="$REMEDIATION_DEFAULT_TARGET"
  parent="$failed_did"

  # Build the directive body via the same summarizer the composer uses.
  local body
  body="$(_summarize_findings "$findings_json" "$REMEDIATION_BODY_MAX_CHARS")"
  directive=$(printf 'REMEDIATE (verify-fail) parent=%s\n%s\n%s' \
                "$failed_did" \
                "Address the following findings and re-emit a BuildArtifact:" \
                "$body")
  if (( ${#directive} > REMEDIATION_DIRECTIVE_MAX_CHARS )); then
    directive="${directive:0:REMEDIATION_DIRECTIVE_MAX_CHARS}
(... directive truncated at ${REMEDIATION_DIRECTIVE_MAX_CHARS} chars)"
  fi

  # Retry budget check BEFORE dispatch — never queue work past the cap.
  # `set -e` would abort on non-zero, so guard with `|| rc=$?` and capture
  # the real exit code (NOT via `if !`, which masks it through `!`).
  local rc=0
  remediation_check_retry_budget "$pid" "verify_in_progress" >/dev/null || rc=$?
  if (( rc != 0 )); then
    if (( rc == 3 )); then
      remediation_surface_to_user "$pid" \
        "verify_build_loop_max exhausted (failed_directive=$failed_did)" >/dev/null || true
    fi
    return "$rc"
  fi

  # Dispatch via router.sh — sourced, so the function is in scope. We pass
  # the COMPOSED directive (already includes finding summaries) so the
  # router does not need to know about findings shape. Router writes the
  # route_history row with parent_directive_id in metadata.
  local resp
  resp="$(route_dispatch_remediation "$failed_did" "$directive" "$target")" || {
    _err_json "router_failure" "route_dispatch_remediation failed for $failed_did"; return 4
  }
  local new_did
  new_did="$(printf '%s' "$resp" | sed -n 's/.*"directive_id":"\([^"]*\)".*/\1/p')"
  [[ -z "$new_did" ]] && {
    _err_json "router_failure" "router reply missing directive_id" "{\"response\":${resp:-null}}"; return 4
  }

  # Transition verify_in_progress -> build_in_progress. Delegated to the
  # state-machine engine so audit + phase_history rows match the canonical
  # writers. Actor is the orchestrator itself.
  if ! transition_execute "$pid" "build_in_progress" "orchestrator.remediation" \
        "verify-fail-remediation" >/dev/null; then
    _err_json "transition_failure" \
      "dispatch succeeded but verify->build transition failed for pid=$pid" \
      "{\"new_directive_id\":\"$new_did\"}"
    return 5
  fi

  printf '{"ok":true,"project_id":%s,"new_directive_id":"%s","parent_directive_id":"%s","role":"%s","target":"%s"}\n' \
    "$pid" "$new_did" "$parent" "$role" "$target"
}

# ─────────────────────────────────────────────────────────────────────
# Surface to user — last resort when the retry budget is blown. Direct
# UPDATE on project.status (no phase transition: blocked is a lifecycle
# envelope, not a phase). Writes an audit row for traceability.
# ─────────────────────────────────────────────────────────────────────

remediation_surface_to_user() {
  local pid="${1:-}" reason="${2:-retry budget exhausted}"
  [[ -z "$pid" ]] && { _err_json "invalid_input" "surface requires <project_id> <reason>"; return 2; }

  _psql <<SQL || { _err_json "db_error" "could not mark project $pid blocked"; return 6; }
UPDATE spine_lifecycle.project
   SET status   = 'paused',
       metadata = metadata || jsonb_build_object(
                     'blocked',           true,
                     'blocked_reason',    '$(_sql_esc "$reason")',
                     'blocked_at',        NOW()::text,
                     'blocked_by',        'orchestrator.remediation')
 WHERE id = $pid;
SQL

  # Best-effort audit row — uses transition.sh's _audit_row helper, which
  # silently no-ops if spine_audit.events is not yet present.
  _audit_row "$pid" "$(_current_phase "$pid")" "remediation_surfaced" "$reason" || true

  printf '{"ok":true,"project_id":%s,"status":"paused","blocker":"%s"}\n' \
    "$pid" "${reason//\"/\\\"}"
}

# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    compose)     remediation_compose_directive "$@" ;;
    check-retry) remediation_check_retry_budget "$@" ;;
    dispatch)    remediation_dispatch           "$@" ;;
    surface)     remediation_surface_to_user    "$@" ;;
    -h|--help|"") sed -n '2,22p' "${BASH_SOURCE[0]}" >&2; exit 0 ;;
    *) _err_json "unknown_command" "no such subcommand: $cmd"; exit 64 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
