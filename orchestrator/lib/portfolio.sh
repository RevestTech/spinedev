#!/usr/bin/env bash
# portfolio.sh — Spine orchestrator portfolio management.
#
# Implements STORY-9.5.1 (multiple projects in flight), STORY-9.5.2 (per-
# project resource limits + queue), STORY-9.5.3 (cross-project rollups via
# SQL views). Maps to docs/PRD.md REQ-INIT-9 §9.5 FR-6; depends on V14
# (project, route_history) + V17 (portfolio_queue + views).
#
# Why: transition.sh + router.sh are per-project; nothing stops one chatty
# project starving the rest. This coordinator gates dispatches against per-
# project limits, queues overflow, and exposes rollups so an operator can
# answer "what's where, what's stuck" without writing SQL. Same split as
# gate.sh: portfolio decides yes/no/queued; router.sh dispatches over MCP.
#
# CLI:
#   portfolio.sh can-dispatch <project_id>
#   portfolio.sh queue        <project_id> <subsystem> <role> <directive_ref> [priority]
#   portfolio.sh drain        [project_id]
#   portfolio.sh status
#   portfolio.sh set-limit    <project_id> <max_parallel_directives> [max_workers]
#   portfolio.sh blocked
#
# Exit codes: 0=ok/has-capacity, 2=at-limit/queued, 3=blocked,
#   4=db-error, 64=unknown-subcommand.

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_env_loader.sh
. "$SCRIPT_DIR/_env_loader.sh"
ROUTER_SH="${SPINE_ROUTER_SH:-$SCRIPT_DIR/router.sh}"
TRANSITION_SH="${SPINE_TRANSITION_SH:-$SCRIPT_DIR/transition.sh}"

# Default per-project parallel directive cap. Org bundles override via
# project.metadata->>'max_parallel_directives'; `set-limit` is the operator
# escape hatch.
SPINE_DEFAULT_MAX_PARALLEL="${SPINE_DEFAULT_MAX_PARALLEL:-3}"
SPINE_DEFAULT_MAX_WORKERS="${SPINE_DEFAULT_MAX_WORKERS:-2}"

# Source siblings only if present (tests may run without them). Both gate
# main() on BASH_SOURCE==0 so the import is side-effect-free.
[[ -f "$TRANSITION_SH" ]] && . "$TRANSITION_SH"   # shellcheck source=transition.sh
[[ -f "$ROUTER_SH"     ]] && . "$ROUTER_SH"       # shellcheck source=router.sh

_psql() { psql "$SPINE_DB_URL" -v ON_ERROR_STOP=1 -A -t -X -q "$@"; }
_log()  { printf '%s portfolio.sh %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${*:2}" >&2; }
_sql_esc() { printf '%s' "$1" | sed "s/'/''/g"; }
_err_json() {
  local code="$1" message="$2" extra="${3:-{\}}"
  printf '{"ok":false,"code":"%s","message":"%s","extra":%s}\n' \
    "$code" "${message//\"/\\\"}" "$extra"
  _log ERROR "$code: $message"
}

# _project_limit: project.metadata override → env default → constant.
_project_limit() {
  local out
  out="$(_psql -c "SELECT COALESCE((metadata->>'max_parallel_directives')::int, $SPINE_DEFAULT_MAX_PARALLEL)
                     FROM spine_lifecycle.project WHERE id = $1;")" || return 4
  out="${out//[[:space:]]/}"; [[ -z "$out" ]] && out="$SPINE_DEFAULT_MAX_PARALLEL"
  printf '%s' "$out"
}
_project_status() {
  local out
  out="$(_psql -c "SELECT status FROM spine_lifecycle.project WHERE id = $1;")" || return 4
  printf '%s' "${out//[[:space:]]/}"
}
_project_is_blocked() {
  local out
  out="$(_psql -c "SELECT CASE WHEN status='paused'
                              OR COALESCE((metadata->>'blocked')::bool, false)
                          THEN 1 ELSE 0 END
                     FROM spine_lifecycle.project WHERE id = $1;")" || return 4
  [[ "${out//[[:space:]]/}" == "1" ]]
}
_in_flight() {
  local out
  out="$(_psql -c "SELECT COUNT(*) FROM spine_lifecycle.route_history
                    WHERE project_id = $1
                      AND dispatched_at IS NOT NULL
                      AND completed_at  IS NULL;")" || return 4
  printf '%s' "${out//[[:space:]]/}"
}

# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────

# portfolio_can_dispatch <pid> — does this project have headroom RIGHT NOW?
# exit 0 = yes; 2 = at limit (caller should queue); 3 = paused/blocked
# (neither dispatch nor queue); 4 = db error.
portfolio_can_dispatch() {
  local pid="$1" status limit in_flight
  status="$(_project_status "$pid")" || { _err_json "db_error" "status lookup failed pid=$pid"; return 4; }
  [[ -z "$status" ]] && { _err_json "project_not_found" "no project pid=$pid"; return 4; }
  if _project_is_blocked "$pid"; then
    _err_json "project_blocked" "project $pid is paused or metadata.blocked=true" \
      "{\"project_id\":$pid,\"status\":\"$status\"}"
    return 3
  fi
  limit="$(_project_limit "$pid")"    || { _err_json "db_error" "limit lookup failed"; return 4; }
  in_flight="$(_in_flight "$pid")"    || { _err_json "db_error" "in-flight count failed"; return 4; }
  if (( in_flight >= limit )); then
    printf '{"ok":false,"code":"at_limit","project_id":%s,"in_flight":%s,"limit":%s}\n' \
      "$pid" "$in_flight" "$limit"
    return 2
  fi
  printf '{"ok":true,"project_id":%s,"in_flight":%s,"limit":%s}\n' \
    "$pid" "$in_flight" "$limit"
}

# portfolio_queue_directive <pid> <subsystem> <role> <directive_ref> [priority]
# Enqueues an overflow directive. Caller invokes this when can-dispatch
# returned 2. Payload is stored as JSON so drain() can hand it to router.sh
# without re-parsing argv.
portfolio_queue_directive() {
  local pid="$1" sub="$2" role="$3" ref="$4" prio="${5:-100}"
  case "$sub" in plan|build|verify) ;; *)
    _err_json "bad_subsystem" "subsystem must be plan|build|verify"; return 4 ;;
  esac
  local payload qid
  payload="$(printf '{"directive_ref":"%s","subsystem":"%s","role":"%s"}' \
              "$(_sql_esc "$ref")" "$sub" "$(_sql_esc "$role")")"
  qid="$(_psql -c "INSERT INTO spine_lifecycle.portfolio_queue
                          (project_id, subsystem, role, directive_payload, priority)
                   VALUES ($pid, '$sub', '$(_sql_esc "$role")',
                           '$(_sql_esc "$payload")'::jsonb, $prio)
                   RETURNING id;")" \
    || { _err_json "db_error" "queue insert failed pid=$pid"; return 4; }
  qid="${qid//[[:space:]]/}"
  printf '{"ok":true,"queued":true,"queue_id":%s,"project_id":%s,"priority":%s}\n' \
    "$qid" "$pid" "$prio"
  return 2
}

# portfolio_drain_queue [pid] — try to dispatch queued items, lowest-priority
# integer first, oldest first within priority. Scope-narrowed to one pid
# when given. Idempotent (cron-safe); also event-driven from router.sh's
# reply handler (every completed_at frees a slot).
portfolio_drain_queue() {
  local pid="${1:-}" rows row qid p sub role ref where=""
  [[ -n "$pid" ]] && where="AND project_id = $pid"
  rows="$(_psql -c "SELECT id || '|' || project_id || '|' || subsystem || '|' ||
                          role || '|' || (directive_payload->>'directive_ref')
                     FROM spine_lifecycle.portfolio_queue
                    WHERE dispatched_at IS NULL $where
                    ORDER BY priority ASC, queued_at ASC
                    LIMIT 100;")" \
    || { _err_json "db_error" "drain SELECT failed"; return 4; }
  local dispatched=0 skipped=0
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    qid="${row%%|*}"; row="${row#*|}"
    p="${row%%|*}";   row="${row#*|}"
    sub="${row%%|*}"; row="${row#*|}"
    role="${row%%|*}"; ref="${row#*|}"
    if ! portfolio_can_dispatch "$p" >/dev/null 2>&1; then
      skipped=$((skipped + 1)); continue
    fi
    if declare -F route_dispatch_to_subsystem >/dev/null \
        && route_dispatch_to_subsystem "$sub" "$role" "$ref" "$p" >/dev/null; then
      _psql -c "UPDATE spine_lifecycle.portfolio_queue
                   SET dispatched_at = NOW()
                 WHERE id = $qid;" >/dev/null || true
      dispatched=$((dispatched + 1))
    else
      skipped=$((skipped + 1))
    fi
  done <<<"$rows"
  printf '{"ok":true,"dispatched":%s,"skipped":%s}\n' "$dispatched" "$skipped"
}

# portfolio_status — JSON rollup across all active/paused projects. One row
# per project so the dashboard / CLI can render a single table.
portfolio_status() {
  local body
  body="$(_psql -c "SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (
    SELECT p.id           AS project_id,
           p.project_uuid AS uuid,
           p.name,
           p.current_phase,
           p.status,
           COALESCE((p.metadata->>'blocked')::bool,false) AS blocked,
           COALESCE((p.metadata->>'max_parallel_directives')::int,
                    $SPINE_DEFAULT_MAX_PARALLEL)          AS limit_,
           (SELECT COUNT(*) FROM spine_lifecycle.route_history rh
             WHERE rh.project_id = p.id AND rh.completed_at IS NULL) AS in_flight,
           (SELECT COUNT(*) FROM spine_lifecycle.portfolio_queue q
             WHERE q.project_id = p.id AND q.dispatched_at IS NULL)  AS queue_depth,
           COALESCE((SELECT SUM(cost_usd) FROM spine_recording.costs c
                      WHERE c.project_id = p.id
                        AND c.ts >= date_trunc('day', NOW())), 0)::numeric AS cost_today
      FROM spine_lifecycle.project p
     WHERE p.status IN ('active','paused')
     ORDER BY p.id) t;")" \
    || { _err_json "db_error" "status rollup failed"; return 4; }
  printf '{"ok":true,"projects":%s}\n' "$body"
}

# portfolio_set_limit <pid> <max_parallel> [max_workers] — admin override.
portfolio_set_limit() {
  local pid="$1" mp="$2" mw="${3:-$SPINE_DEFAULT_MAX_WORKERS}"
  case "$mp" in ''|*[!0-9]*) _err_json "bad_input" "max_parallel must be integer"; return 4 ;; esac
  case "$mw" in ''|*[!0-9]*) _err_json "bad_input" "max_workers must be integer";  return 4 ;; esac
  _psql -c "UPDATE spine_lifecycle.project
               SET metadata = metadata
                            || jsonb_build_object('max_parallel_directives', $mp)
                            || jsonb_build_object('max_workers', $mw)
             WHERE id = $pid;" >/dev/null \
    || { _err_json "db_error" "set-limit UPDATE failed pid=$pid"; return 4; }
  printf '{"ok":true,"project_id":%s,"max_parallel_directives":%s,"max_workers":%s}\n' \
    "$pid" "$mp" "$mw"
}

# portfolio_blocked_projects — list paused OR metadata.blocked=true projects
# with a best-effort reason. Read-only; consumed by operator CLI + dashboard
# "what's stuck" card.
portfolio_blocked_projects() {
  local body
  body="$(_psql -c "SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (
    SELECT id, project_uuid AS uuid, name, current_phase, status,
           COALESCE(metadata->>'block_reason',
                    CASE WHEN status='paused' THEN 'project paused'
                         ELSE 'metadata.blocked=true' END) AS reason,
           updated_at
      FROM spine_lifecycle.project
     WHERE status = 'paused'
        OR COALESCE((metadata->>'blocked')::bool, false)
     ORDER BY updated_at DESC) t;")" \
    || { _err_json "db_error" "blocked-list query failed"; return 4; }
  printf '{"ok":true,"blocked":%s}\n' "$body"
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    can-dispatch) portfolio_can_dispatch      "$@" ;;
    queue)        portfolio_queue_directive   "$@" ;;
    drain)        portfolio_drain_queue       "$@" ;;
    status)       portfolio_status            "$@" ;;
    set-limit)    portfolio_set_limit         "$@" ;;
    blocked)      portfolio_blocked_projects  "$@" ;;
    -h|--help|"") sed -n '2,26p' "${BASH_SOURCE[0]}" >&2; exit 0 ;;
    *)            _err_json "unknown_command" "no such subcommand: $cmd"; exit 64 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
