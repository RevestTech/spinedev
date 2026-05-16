#!/usr/bin/env bash
# v1_dispatcher.sh — bridge v2 orchestrator dispatch → v1 daemon directive file.
#
# Implements part of STORY-7.5.1 / REQ-INIT-7 FR-5: lets the v2 MCP
# `build_dispatch` tool hand a directive to the existing v1 bash daemons
# (`lib/team-agent-daemon.sh`) via the file-bus contract in PROTOCOL.md
# §3a — without modifying any file in `lib/`. Additive only.
#
# Architecture: v2 orchestrator → MCP build_dispatch → THIS module → write
# teams/<role>/directive.md → v1 manager daemon picks up within 8s
# (PROTOCOL §3b). Completed reports are collected by `v1_report_collector.sh`.
#
# CLI:
#   v1_dispatcher.sh dispatch <role> <directive_text> <project_id> \
#                    <pipeline_version> [parent_directive_id]
#   v1_dispatcher.sh status <directive_id>

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Paths --------------------------------------------------------------------
# v1 team file layout (PROTOCOL §2). Override SPINE_TEAMS_DIR to retarget
# (e.g., installed projects keep daemons under their own repo root).
SPINE_TEAMS_DIR="${SPINE_TEAMS_DIR:-.planning/orchestration/agent-handoff/teams}"
# Pick up POSTGRES_* from db/.env so the bridge talks to the same DB the
# Docker stack publishes. Fixes wave-8 smoke F8/F9.
# shellcheck source=../../orchestrator/lib/_env_loader.sh
. "$(cd "$SCRIPT_DIR/../../orchestrator/lib" && pwd)/_env_loader.sh"

# Role manifest mirrors lib/roles.sh::SPINE_TEAM_ROLES. Hard-coded here so
# the bridge stays read-only against lib/ (sourcing roles.sh would couple
# us to its scaffolding side effects).
V1_KNOWN_ROLES=(product planner architect conductor researcher engineer ux \
                qa operator datawright seer auditor memory)

# Logging / JSON helpers ---------------------------------------------------
_log() { printf '%s v1_dispatcher.sh %s %s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${*:2}" >&2; }
_json_esc() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' <<<"$1" \
    | sed -e 's/^"//' -e 's/"$//'
}
_err_json() {
  local code="$1" message="$2"
  printf '{"ok":false,"code":"%s","message":"%s"}\n' \
    "$code" "$(_json_esc "$message")"
  _log ERROR "$code: $message"
}
_psql() { psql "$SPINE_DB_URL" -v ON_ERROR_STOP=1 -A -t -X -q "$@" 2>/dev/null; }

# Role validation ----------------------------------------------------------
v1_role_known() {
  local r="$1" x
  for x in "${V1_KNOWN_ROLES[@]}"; do
    [[ "$x" == "$r" ]] && return 0
  done
  return 1
}

# Generate a stable directive_id. Format: v1-<utc-compact>-<short-hash>
# Hash inputs (project_id|role|timestamp) so concurrent dispatches don't
# collide. Caller may pass parent_directive_id to scope retries.
v1_make_directive_id() {
  local project_id="$1" role="$2" parent="${3:-}"
  local ts hash_src
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  hash_src="${project_id}|${role}|${ts}|${parent}|$$|${RANDOM}"
  local short
  if command -v shasum >/dev/null 2>&1; then
    short=$(printf '%s' "$hash_src" | shasum -a 256 | awk '{print substr($1,1,10)}')
  else
    short=$(printf '%s' "$hash_src" | sha256sum  | awk '{print substr($1,1,10)}')
  fi
  printf 'v1-%s-%s' "$ts" "$short"
}

# Derive tier hint from role default (matches PROTOCOL §11 table). The
# orchestrator may override per-directive in a future revision.
v1_default_tier() {
  case "$1" in
    product|ux|seer|auditor|memory|operator|researcher|datawright) echo low ;;
    architect|qa|conductor|engineer|planner)                       echo medium ;;
    *)                                                              echo medium ;;
  esac
}

# Atomic write: stage to .tmp next to the target and rename (PROTOCOL §5).
v1_atomic_write() {
  local target="$1" body="$2"
  local tmp="${target}.tmp.$$"
  printf '%s' "$body" > "$tmp"
  mv "$tmp" "$target"
}

# Compose the v1 markdown directive. First line MUST be `# Directive`
# (PROTOCOL §3a / team-agent-daemon.sh::classify_file). Trailing metadata
# lines use the `## Key: value` shape v1 daemons already parse.
v1_compose_directive() {
  local role="$1" directive_text="$2" project_id="$3" \
        pipeline_version="$4" parent="${5:-}" tier="${6:-medium}"
  local summary
  summary=$(printf '%s' "$directive_text" | head -n1 | cut -c1-72)
  [[ -z "$summary" ]] && summary="from spine v2 orchestrator"
  {
    printf '# Directive — %s\n\n' "$summary"
    printf '%s\n\n' "$directive_text"
    printf '## Project: %s\n' "$project_id"
    printf '## Pipeline version: %s\n' "$pipeline_version"
    [[ -n "$parent" ]] && printf '## Parent directive: %s\n' "$parent"
    printf '## Source: spine v2 orchestrator\n'
    printf '## Tier hint: %s\n' "$tier"
  }
}

# Record dispatch in spine_lifecycle.route_history (mirrors router.sh).
# Best-effort: db failure must not break the dispatch — the file write is
# authoritative for the v1 daemon, the row is for orchestrator analytics.
v1_record_route_history() {
  local project_id="$1" role="$2" directive_id="$3" pipeline_version="$4" \
        parent="${5:-}"
  local sql
  sql=$(cat <<SQL
INSERT INTO spine_lifecycle.route_history
       (project_id, phase, subsystem, role, directive_ref, metadata)
VALUES (${project_id},
        (SELECT current_phase FROM spine_lifecycle.project WHERE id = ${project_id}),
        'build', '${role}', '${directive_id}',
        jsonb_build_object('pipeline_version','${pipeline_version}',
                           'parent_directive_id', NULLIF('${parent}','')::text,
                           'tool','build_dispatch',
                           'bridge','v1_dispatcher'));
SQL
)
  _psql -c "$sql" >/dev/null 2>&1 || \
    _log WARN "route_history insert failed (pid=${project_id} did=${directive_id}) — continuing"
}

# v1_dispatch_directive — main entry point ----------------------------------
# Args: role directive_text project_id pipeline_version [parent_directive_id]
# Returns JSON: {ok, directive_id, role, file_path, dispatched_at}
v1_dispatch_directive() {
  local role="${1:?role required}"
  local directive_text="${2:?directive_text required}"
  local project_id="${3:?project_id required}"
  local pipeline_version="${4:?pipeline_version required}"
  local parent="${5:-}"

  v1_role_known "$role" || {
    _err_json "unknown_role" "role '$role' not in v1 daemon set"; return 1; }

  local team_dir="${SPINE_TEAMS_DIR}/${role}"
  local directive_file="${team_dir}/directive.md"
  if [[ ! -d "$team_dir" ]]; then
    _err_json "team_dir_missing" \
      "v1 team dir '$team_dir' not present — is the v1 daemon up?"; return 2
  fi

  local directive_id tier body dispatched_at
  directive_id="$(v1_make_directive_id "$project_id" "$role" "$parent")"
  tier="$(v1_default_tier "$role")"
  body="$(v1_compose_directive "$role" "$directive_text" "$project_id" \
          "$pipeline_version" "$parent" "$tier")"
  dispatched_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  v1_atomic_write "$directive_file" "$body"
  _log INFO "dispatched role=$role did=$directive_id file=$directive_file"

  v1_record_route_history "$project_id" "$role" "$directive_id" \
                          "$pipeline_version" "$parent"

  printf '{"ok":true,"directive_id":"%s","role":"%s","file_path":"%s","dispatched_at":"%s"}\n' \
    "$directive_id" "$role" "$directive_file" "$dispatched_at"
}

# v1_check_directive_status — main entry point -----------------------------
# Looks up the route_history row for this directive_id, then inspects the
# matching directive file to classify state. v1 daemons rewrite the file
# header (PROTOCOL §3b–d): `# Directive` → in-progress / dispatched,
# `# Report` → completed, `# Awaiting approval` → awaiting human signoff.
v1_check_directive_status() {
  local directive_id="${1:?directive_id required}"
  local row role db_outcome
  row="$(_psql -c "SELECT role || '|' || COALESCE(outcome,'') FROM spine_lifecycle.route_history WHERE directive_ref = '${directive_id}' LIMIT 1;" 2>/dev/null || echo "")"
  row="${row//[[:space:]]/}"
  if [[ -z "$row" ]]; then
    _err_json "unknown_directive" \
      "no route_history row for directive_id=$directive_id"; return 1
  fi
  role="${row%%|*}"
  db_outcome="${row#*|}"

  local file="${SPINE_TEAMS_DIR}/${role}/directive.md"
  local file_state="missing"
  if [[ -f "$file" ]]; then
    local hdr
    hdr="$(head -1 "$file" 2>/dev/null)"
    case "$hdr" in
      "# Directive"*)         file_state="in_progress" ;;
      "# Plan"*)              file_state="in_progress" ;;
      "# Awaiting approval"*) file_state="awaiting_approval" ;;
      "# Report"*)            file_state="completed" ;;
      *)                      file_state="other" ;;
    esac
  fi

  # DB outcome trumps file state when set (route_history is updated on
  # `build_completed`, archived files might be reused for the next directive).
  local status="$file_state"
  case "$db_outcome" in
    completed) status="completed" ;;
    timeout)   status="timeout" ;;
    failed)    status="failed" ;;
    retry)     status="dispatched" ;;
  esac
  [[ "$file_state" == "missing" && -z "$db_outcome" ]] && status="dispatched"

  printf '{"ok":true,"directive_id":"%s","role":"%s","status":"%s","file_state":"%s","file_path":"%s"}\n' \
    "$directive_id" "$role" "$status" "$file_state" "$file"
}

# CLI dispatcher -----------------------------------------------------------
main() {
  local cmd="${1:-}"
  shift || true
  case "$cmd" in
    dispatch) v1_dispatch_directive "$@" ;;
    status)   v1_check_directive_status "$@" ;;
    -h|--help|"") sed -n '2,20p' "${BASH_SOURCE[0]}" >&2; exit 0 ;;
    *) _err_json "unknown_command" "no such subcommand: $cmd"; exit 64 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
