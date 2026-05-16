#!/usr/bin/env bash
# budget_rollup.sh — Pretty-print Spine unified cost ledger rollups + enforce
# project budget caps. Reads V16 views (EPIC-9.6); check-budget is the call
# point for EPIC-2.3 budget enforcement.
#
# CLI: per-project [pid] | per-user [uid] | per-org [oid]
#      check-budget <pid> | summary
# Exit codes: 0=under/clean, 2=over budget, 3=db error, 64=unknown cmd.

set -euo pipefail
IFS=$'\n\t'

SPINE_DB_URL="${SPINE_DB_URL:-postgresql://spine:spine@localhost:33000/spine}"

_log() { printf '%s budget_rollup.sh %s %s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${*:2}" >&2; }
_sql_esc() { printf '%s' "$1" | sed "s/'/''/g"; }

# Pipe-delimited, header-less psql; column -t -s'|' aligns the output.
_psql_or_dberr() {
  psql "$SPINE_DB_URL" -A -t -X -q -v ON_ERROR_STOP=1 -F'|' "$@" || {
    _log ERROR "psql failed (db_error); SPINE_DB_URL=$SPINE_DB_URL"; return 3;
  }
}

_print_table() {
  printf '\n=== %s ===\n' "$1"
  { printf '%s\n' "$2"; cat; } | column -t -s'|'
  printf '\n'
}

cmd_per_project() {
  local where=""; [[ -n "${1:-}" ]] && where="WHERE project_id = $1"
  _psql_or_dberr -c "
SELECT project_id, COALESCE(phase,'-'), subsystem,
       ROUND(total_cost::numeric, 4), event_count,
       to_char(last_event AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SSZ')
FROM   spine_recording.v_cost_per_project $where
ORDER  BY project_id, total_cost DESC;" \
    | _print_table "Cost per project x phase x subsystem" \
                   "PROJECT|PHASE|SUBSYSTEM|COST_USD|EVENTS|LAST_EVENT"
}

cmd_per_user() {
  local where=""; [[ -n "${1:-}" ]] && where="WHERE user_id = '$(_sql_esc "$1")'"
  _psql_or_dberr -c "
SELECT user_id, subsystem, day_bucket, week_bucket, month_bucket,
       ROUND(total_cost::numeric, 4), event_count
FROM   spine_recording.v_cost_per_user $where
ORDER  BY total_cost DESC LIMIT 200;" \
    | _print_table "Cost per user (day/week/month buckets)" \
                   "USER|SUBSYSTEM|DAY|WEEK|MONTH|COST_USD|EVENTS"
}

cmd_per_org() {
  local where=""; [[ -n "${1:-}" ]] && where="WHERE org_id = '$(_sql_esc "$1")'"
  _psql_or_dberr -c "
SELECT COALESCE(org_id,'(unbundled)'), subsystem, COALESCE(phase,'-'),
       ROUND(total_cost::numeric, 4), event_count
FROM   spine_recording.v_cost_per_org $where
ORDER  BY total_cost DESC;" \
    | _print_table "Cost per org (via project.org_bundle join)" \
                   "ORG|SUBSYSTEM|PHASE|COST_USD|EVENTS"
}

cmd_check_budget() {
  local pid="${1:?check-budget requires <project_id>}"
  local row spent cap
  row="$(_psql_or_dberr -c "
SELECT COALESCE((SELECT SUM(total_cost) FROM spine_recording.v_cost_per_project
                 WHERE project_id = $pid), 0)::numeric
       || '|' ||
       COALESCE((SELECT (metadata ->> 'budget_cap_usd')::numeric
                 FROM spine_lifecycle.project WHERE id = $pid), 0)::numeric;")" \
    || return 3
  row="${row//[[:space:]]/}"
  spent="${row%%|*}"; cap="${row#*|}"
  if awk -v s="$spent" -v c="$cap" 'BEGIN{exit !(c>0 && s>c)}'; then
    printf '{"ok":false,"project_id":%s,"spent_usd":%s,"cap_usd":%s,"verdict":"over_budget"}\n' \
      "$pid" "$spent" "$cap"
    _log WARN "project=$pid spent=$spent cap=$cap OVER_BUDGET"; return 2
  fi
  printf '{"ok":true,"project_id":%s,"spent_usd":%s,"cap_usd":%s,"verdict":"under_budget"}\n' \
    "$pid" "$spent" "$cap"
}

cmd_summary() {
  _psql_or_dberr -c "
SELECT bucket, subsystem, ROUND(spend::numeric, 4) FROM (
  SELECT 'today' AS bucket, subsystem, SUM(cost_usd) AS spend
    FROM spine_recording.costs WHERE ts >= date_trunc('day', NOW())
    GROUP BY subsystem
  UNION ALL
  SELECT 'this_week', subsystem, SUM(cost_usd) FROM spine_recording.costs
    WHERE ts >= date_trunc('week', NOW()) GROUP BY subsystem
  UNION ALL
  SELECT 'this_month', subsystem, SUM(cost_usd) FROM spine_recording.costs
    WHERE ts >= date_trunc('month', NOW()) GROUP BY subsystem
) s
ORDER BY CASE bucket WHEN 'today' THEN 1 WHEN 'this_week' THEN 2 ELSE 3 END,
         spend DESC;" \
    | _print_table "Top-line spend by bucket x subsystem" \
                   "BUCKET|SUBSYSTEM|COST_USD"
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    per-project)   cmd_per_project  "$@" ;;
    per-user)      cmd_per_user     "$@" ;;
    per-org)       cmd_per_org      "$@" ;;
    check-budget)  cmd_check_budget "$@" ;;
    summary)       cmd_summary      "$@" ;;
    -h|--help|"")  sed -n '2,8p' "${BASH_SOURCE[0]}" >&2; exit 0 ;;
    *) _log ERROR "unknown subcommand: $cmd"; exit 64 ;;
  esac
}

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && main "$@"
