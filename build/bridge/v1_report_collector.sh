#!/usr/bin/env bash
# v1_report_collector.sh — bridge v1 markdown reports → v2 BuildArtifact.
#
# Implements part of STORY-7.5.1 / REQ-INIT-7 FR-5. Polls every v1 role
# team dir for `directive.md` files whose header has become `# Report`
# (PROTOCOL §3b — the v1 daemon completion marker). For each one, calls
# `report_parser.py` to extract a typed BuildArtifact and either:
#   1. POSTs it to the v2 MCP `build_completed` tool, OR
#   2. (Fallback) writes it directly to `spine_audit.audit_event` via psql.
# Then archives the v1 file to keep the directive slot clear.
#
# CLI:
#   v1_report_collector.sh watch         — long-running 8s poll loop
#   v1_report_collector.sh collect-once  — single pass (cron-safe)
#   v1_report_collector.sh status        — print queue counts per role

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SPINE_TEAMS_DIR="${SPINE_TEAMS_DIR:-.planning/orchestration/agent-handoff/teams}"
# shellcheck source=../../orchestrator/lib/_env_loader.sh
. "$(cd "$SCRIPT_DIR/../../orchestrator/lib" && pwd)/_env_loader.sh"
SPINE_MCP_HTTP_URL="${SPINE_MCP_HTTP_URL:-http://localhost:8765/tools}"
COLLECTOR_POLL_S="${COLLECTOR_POLL_S:-8}"   # matches v1 daemon POLL_INTERVAL

# Mirrors lib/roles.sh::SPINE_TEAM_ROLES; kept inline to stay read-only
# against lib/. Update both lists when a role lands or retires.
V1_KNOWN_ROLES=(product planner architect conductor researcher engineer ux \
                qa operator datawright seer auditor memory)

_log() { printf '%s v1_report_collector.sh %s %s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${*:2}" >&2; }
_psql() { psql "$SPINE_DB_URL" -v ON_ERROR_STOP=1 -A -t -X -q "$@" 2>/dev/null; }

# Look up project_id + pipeline_version + directive_id for a (role, file)
# pair by searching route_history for the most recent uncompleted dispatch.
# Best-effort: returns three tab-separated fields or empty on miss.
_lookup_pending_dispatch() {
  local role="$1"
  _psql -F$'\t' -c "SELECT directive_ref, project_id, COALESCE(metadata->>'pipeline_version','') FROM spine_lifecycle.route_history WHERE role = '${role}' AND subsystem = 'build' AND completed_at IS NULL ORDER BY dispatched_at DESC LIMIT 1;"
}

# Mark a route_history row completed (mirrors router.sh::route_record_reply).
_record_completion() {
  local directive_id="$1" outcome="$2"
  _psql -c "UPDATE spine_lifecycle.route_history SET completed_at = NOW(), outcome = '${outcome}' WHERE directive_ref = '${directive_id}' AND completed_at IS NULL;" >/dev/null 2>&1 || \
    _log WARN "could not mark $directive_id $outcome in route_history"
}

# Send the BuildArtifact JSON to v2 MCP build_completed. Returns 0 on
# success. Fallback path: append a raw row to spine_audit so the artifact
# is never lost, even if the MCP server is down.
_emit_artifact() {
  local artifact_json="$1" project_id="$2" directive_id="$3"
  local payload
  payload=$(python3 -c '
import json, sys
art = json.loads(sys.stdin.read())
print(json.dumps({"project_id": sys.argv[1], "directive_id": sys.argv[2], "artifact": art}))
' "$project_id" "$directive_id" <<<"$artifact_json")

  if command -v mcp >/dev/null 2>&1; then
    if mcp call build_completed --json "$payload" >/dev/null 2>&1; then return 0; fi
  fi
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS -H 'Content-Type: application/json' \
        -X POST "$SPINE_MCP_HTTP_URL/build_completed" \
        --data "$payload" >/dev/null 2>&1; then return 0; fi
  fi
  _log WARN "MCP build_completed unreachable — falling back to direct audit insert"
  local esc; esc="${artifact_json//\'/\'\'}"
  _psql -c "INSERT INTO spine_audit.audit_event (project_id, role, subsystem, action, subject_type, subject_id, actor, metadata) VALUES (${project_id}, 'engineer', 'build', 'build_completed_v1bridge', 'directive', '${directive_id}', 'v1_report_collector', '${esc}'::jsonb);" >/dev/null 2>&1 \
    || { _log ERROR "audit fallback insert failed for $directive_id"; return 1; }
  return 0
}

# Archive the v1 report file once we've consumed it. v1 daemons leave the
# file in place across directives; moving it ensures the next dispatch
# starts with a clean directive slot. PROTOCOL §3d uses the same pattern
# (workers/archive/) for worker reports.
_archive_report() {
  local role="$1" file="$2" directive_id="$3"
  local archive_dir="${SPINE_TEAMS_DIR}/${role}/archive"
  mkdir -p "$archive_dir"
  local target="${archive_dir}/${directive_id}.md"
  mv "$file" "$target" 2>/dev/null || _log WARN "archive move failed: $file"
  # Drop a placeholder so the v1 daemon's classify_file returns "other"
  # rather than picking the stale report up as a new directive.
  printf '%s\n' "# (idle — drop a directive here)" \
    > "${SPINE_TEAMS_DIR}/${role}/directive.md"
}

# Process a single completed v1 report ------------------------------------
v1_process_report() {
  local role="$1" file="$2"
  local lookup directive_id project_id pipeline_version
  lookup="$(_lookup_pending_dispatch "$role")"
  if [[ -z "$lookup" ]]; then
    _log WARN "no pending route_history row for role=$role file=$file — skipping (likely a manual v1 invocation)"
    return 0
  fi
  IFS=$'\t' read -r directive_id project_id pipeline_version <<<"$lookup"
  [[ -z "$directive_id" || -z "$project_id" ]] && {
    _log WARN "incomplete lookup row for role=$role: $lookup"; return 0; }
  [[ -z "$pipeline_version" ]] && pipeline_version="unknown"

  _log INFO "processing role=$role did=$directive_id pid=$project_id"

  local artifact
  artifact=$(python3 "$SCRIPT_DIR/report_parser.py" parse "$file" \
              --role "$role" \
              --project-id "$project_id" \
              --directive-id "$directive_id" \
              --pipeline-version "$pipeline_version" 2>/dev/null) || {
    _log ERROR "report_parser failed for $file"; return 1; }

  # Determine outcome from the report header. PROTOCOL §3e: failures keep
  # the `# Report` prefix but include FAILED/STOPPED/TIMEOUT in the title.
  local hdr outcome
  hdr="$(head -1 "$file" 2>/dev/null || echo "")"
  outcome="completed"
  [[ "$hdr" == *"FAILED"*  ]] && outcome="failed"
  [[ "$hdr" == *"STOPPED"* ]] && outcome="failed"
  [[ "$hdr" == *"TIMEOUT"* ]] && outcome="timeout"

  _emit_artifact "$artifact" "$project_id" "$directive_id" || return 1
  _record_completion "$directive_id" "$outcome"
  _archive_report "$role" "$file" "$directive_id"
}

# Single-pass collector ----------------------------------------------------
v1_collect_completed_reports() {
  local role file hdr n=0
  for role in "${V1_KNOWN_ROLES[@]}"; do
    file="${SPINE_TEAMS_DIR}/${role}/directive.md"
    [[ -f "$file" ]] || continue
    hdr="$(head -1 "$file" 2>/dev/null || echo "")"
    [[ "$hdr" == "# Report"* ]] || continue
    v1_process_report "$role" "$file" && n=$((n + 1)) || true
  done
  _log INFO "collect-once processed=$n reports"
  printf '{"ok":true,"processed":%d}\n' "$n"
}

# Long-running watcher -----------------------------------------------------
v1_watch_loop() {
  _log INFO "watch loop starting (poll=${COLLECTOR_POLL_S}s teams=${SPINE_TEAMS_DIR})"
  trap '_log INFO "watch loop stopping"; exit 0' INT TERM
  while true; do
    v1_collect_completed_reports >/dev/null 2>&1 || \
      _log WARN "collect pass errored — continuing"
    sleep "$COLLECTOR_POLL_S"
  done
}

# Status — queue counts per role, useful for `team doctor`-style checks.
v1_status() {
  local role file hdr pending_n=0 ready_n=0
  printf '{"roles":['
  local first=1
  for role in "${V1_KNOWN_ROLES[@]}"; do
    file="${SPINE_TEAMS_DIR}/${role}/directive.md"
    local state="missing"
    if [[ -f "$file" ]]; then
      hdr="$(head -1 "$file" 2>/dev/null || echo "")"
      case "$hdr" in
        "# Directive"*)         state="dispatched";          pending_n=$((pending_n + 1)) ;;
        "# Plan"*)              state="plan_in_progress";    pending_n=$((pending_n + 1)) ;;
        "# Awaiting approval"*) state="awaiting_approval";   pending_n=$((pending_n + 1)) ;;
        "# Report"*)            state="report_ready";        ready_n=$((ready_n + 1)) ;;
        *)                      state="idle" ;;
      esac
    fi
    [[ $first -eq 1 ]] || printf ','
    first=0
    printf '{"role":"%s","state":"%s"}' "$role" "$state"
  done
  printf '],"pending":%d,"ready":%d}\n' "$pending_n" "$ready_n"
}

main() {
  local cmd="${1:-}"
  case "$cmd" in
    watch)         v1_watch_loop ;;
    collect-once)  v1_collect_completed_reports ;;
    status)        v1_status ;;
    -h|--help|"")  sed -n '2,20p' "${BASH_SOURCE[0]}" >&2; exit 0 ;;
    *) printf '{"ok":false,"code":"unknown_command","message":"%s"}\n' "$cmd"; exit 64 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
