#!/usr/bin/env bash
# router.sh — Spine orchestrator MCP-only routing layer.
#
# Implements STORY-9.4.1 (MCP dispatch to plan/build/verify), STORY-9.4.2
# (every dispatch carries the locked pipeline_version per EPIC-1.7.5),
# STORY-9.4.3 (record `*_completed` replies in route_history), and
# STORY-9.8.1 (verify-fail auto-remediation back to Build).
#
# Architectural rule (PRD REQ-INIT-9 FR-5): subsystems are addressed
# EXCLUSIVELY via MCP — no direct imports, no cross-subsystem shell calls.
# This module is the single dispatch chokepoint that enforces that rule.
# The MCP server itself (STORY-2.2.1) is assumed to live at
# shared/mcp/server.py and to expose the tools declared in SPINE_MCP_TOOL.
#
# CLI:
#   router.sh dispatch  <subsystem> <role> <directive> <project_id> [parent_id] [budget_usd]
#   router.sh decide    <current_phase>
#   router.sh reply     <directive_id> <status> [error]
#   router.sh remediate <failed_directive_id> <findings_ref> <target_subsystem>

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASES_YAML="${SPINE_PHASES_YAML:-$SCRIPT_DIR/../state/phases.yaml}"
# shellcheck source=_env_loader.sh
. "$SCRIPT_DIR/_env_loader.sh"
SPINE_MCP_HTTP_URL="${SPINE_MCP_HTTP_URL:-http://localhost:8765/tools}"
SPINE_AUDIT_CLI="${SPINE_AUDIT_CLI:-$SCRIPT_DIR/../../shared/audit/audit_record.py}"
SPINE_HOME="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Pick a Python: project venv takes precedence
if [[ -x "$SPINE_HOME/.venv/bin/python3" ]]; then
  _SPINE_PY="$SPINE_HOME/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  _SPINE_PY="$(command -v python3)"
else
  _SPINE_PY=""
fi

# Manifest: subsystem -> MCP tool. Single source of truth for FR-5 mapping.
# Replaces associative array for compatibility with macOS Bash 3.2.
_get_mcp_tool() {
  case "$1" in
    plan)   printf 'plan_dispatch' ;;
    build)  printf 'build_dispatch' ;;
    verify) printf 'verify_audit' ;;
  esac
}

_psql() { psql "$SPINE_DB_URL" -v ON_ERROR_STOP=1 -A -t -X -q "$@"; }
_log()  { printf '%s router.sh %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${*:2}" >&2; }
_sql_esc() { printf '%s' "$1" | sed "s/'/''/g"; }
_err_json() {
  local code="$1" message="$2" extra="${3:-{\}}"
  printf '{"ok":false,"code":"%s","message":"%s","extra":%s}\n' \
    "$code" "${message//\"/\\\"}" "$extra"
  _log ERROR "$code: $message"
}

_mcp_inprocess_call() {
  local tool="$1" payload="$2"
  SPINE_TOOL="$tool" SPINE_PAYLOAD="$payload" SPINE_HOME="$SPINE_HOME" \
    "$_SPINE_PY" - <<'PY'
import json, os, sys, traceback
sys.path.insert(0, os.environ["SPINE_HOME"])
sys.path.insert(1, os.path.join(os.environ["SPINE_HOME"], "verify"))
try:
    from shared.secrets import SecretAdapter, SecretNotFound, set_default_adapter
    class FileSecretsAdapter(SecretAdapter):
        name = "file"
        def __init__(self, filepath: str) -> None:
            self.filepath = filepath
        def _read(self) -> dict[str, str]:
            if not os.path.exists(self.filepath):
                return {}
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        def _write(self, store: dict[str, str]) -> None:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(store, f)
        async def get(self, path: str) -> str:
            store = self._read()
            if path in store:
                return store[path]
            raise SecretNotFound(path)
        async def put(self, path: str, value: str) -> None:
            store = self._read()
            store[path] = value
            self._write(store)
        async def delete(self, path: str) -> None:
            store = self._read()
            if path in store:
                del store[path]
                self._write(store)
        async def list(self, prefix: str = "") -> list[str]:
            store = self._read()
            return sorted(k for k in store if k.startswith(prefix))
    set_default_adapter(FileSecretsAdapter(os.path.join(os.environ["SPINE_HOME"], ".spine", "mock_secrets.json")))
except Exception as e:
    print(json.dumps({"status": "error", "error": f"secrets_bootstrap_failed: {e}", "data": None}))
    sys.exit(0)

try:
    from shared.mcp.tools import TOOL_REGISTRY, discover_tools
except Exception as e:
    print(json.dumps({"status": "error", "error": f"import_failed: {e}", "data": None}))
    sys.exit(0)
discover_tools()
name = os.environ["SPINE_TOOL"]
spec = TOOL_REGISTRY.get(name)
if spec is None:
    print(json.dumps({"status": "error", "error": f"unknown_tool: {name}", "data": None}))
    sys.exit(0)
try:
    payload = spec.input_model.model_validate_json(os.environ["SPINE_PAYLOAD"])
    result = spec.fn(payload)
except Exception as e:
    print(json.dumps({"status": "error", "error": str(e),
                      "data": None, "trace": traceback.format_exc()}))
    sys.exit(0)
if hasattr(result, "model_dump_json"):
    print(result.model_dump_json())
elif hasattr(result, "model_dump"):
    print(json.dumps(result.model_dump(mode="json"), default=str))
else:
    print(json.dumps(result, default=str))
PY
}

# ─────────────────────────────────────────────────────────────────────
# MCP transport — prefer standard stdio/inprocess, fallback to HTTP.
# ─────────────────────────────────────────────────────────────────────
_mcp_call() {
  local tool="$1" payload="$2"
  if command -v mcp >/dev/null 2>&1; then
    mcp call "$tool" --json "$payload"
  elif [[ -n "$_SPINE_PY" && -d "$SPINE_HOME/shared/mcp" ]]; then
    _mcp_inprocess_call "$tool" "$payload"
  elif command -v curl >/dev/null 2>&1; then
    curl -fsS -H 'Content-Type: application/json' \
      -X POST "$SPINE_MCP_HTTP_URL/$tool" --data "$payload"
  else
    _err_json "mcp_unavailable" "no mcp CLI, no Python, and no curl on PATH"; return 1
  fi
}

# Pipeline-version lookup (STORY-9.4.2 / EPIC-1.7.5). HARD ERROR if missing:
# no project row => no lock => no dispatch. Never call MCP without this.
route_locked_pipeline_version() {
  local pid="$1" out resolved
  resolved="$(_psql -c "SELECT id FROM spine_lifecycle.project
                          WHERE id::text = '$(_sql_esc "$pid")'
                             OR name = '$(_sql_esc "$pid")'
                             OR project_uuid::text = '$(_sql_esc "$pid")' LIMIT 1;" 2>/dev/null || true)"
  resolved="${resolved//[[:space:]]/}"
  [[ -n "$resolved" ]] && pid="$resolved"

  out="$(_psql -c "SELECT pipeline_version FROM spine_lifecycle.project WHERE id = $pid;")" \
    || { _err_json "db_error" "could not read project pid=$pid"; return 2; }
  out="${out//[[:space:]]/}"
  [[ -z "$out" ]] && { _err_json "pipeline_version_missing" \
      "project $pid has no locked pipeline_version (cannot dispatch)"; return 3; }
  printf '%s' "$out"
}

# phase -> subsystem (reads phases.yaml). Echoes plan|build|verify on stdout.
route_decide_subsystem() {
  local phase="$1" sub
  if command -v yq >/dev/null 2>&1; then
    sub="$(yq -r ".phases[] | select(.id == \"$phase\") | .subsystem" "$PHASES_YAML")"
  else
    sub="$(awk -v want="$phase" '
      /^[[:space:]]*-[[:space:]]+id:[[:space:]]+/ {
        in_block = ($0 ~ ("id:[[:space:]]+" want "([[:space:]]|$)")) }
      in_block && /^[[:space:]]+subsystem:[[:space:]]+/ {
        sub("^[[:space:]]+subsystem:[[:space:]]+",""); print; exit }' "$PHASES_YAML")"
  fi
  sub="${sub//[[:space:]]/}"
  local tool; tool="$(_get_mcp_tool "$sub")"
  [[ -z "$sub" || -z "$tool" ]] \
    && { _err_json "unknown_phase" "phase '$phase' has no routable subsystem"; return 4; }
  printf '%s' "$sub"
}

# Audit hook — prefers shared/audit CLI when present; otherwise stubs to a
# best-effort psql insert. TODO(STORY-3.1): drop the psql path once wired.
_audit_dispatch() {
  local pid="$1" sub="$2" role="$3" did="$4"
  if [[ -x "$SPINE_AUDIT_CLI" ]]; then
    "$SPINE_AUDIT_CLI" record --project "$pid" --subsystem "$sub" \
      --role "$role" --action dispatch --subject "$did" >/dev/null 2>&1 || true
    return 0
  fi
  _psql <<SQL 2>/dev/null || true
DO \$\$ BEGIN
  IF to_regclass('spine_audit.events') IS NOT NULL THEN
    INSERT INTO spine_audit.events (project_id, phase, action, rationale)
    VALUES ($pid,
            (SELECT current_phase FROM spine_lifecycle.project WHERE id = $pid),
            'dispatch', 'router.sh -> $sub.$role directive=$did');
  END IF;
END \$\$;
SQL
}

# Dispatch (STORY-9.4.1 + 9.4.2). Records route_history with completed_at NULL.
route_dispatch_to_subsystem() {
  local sub="$1" role="$2" directive="$3" pid="$4"
  local parent="${5:-}" budget="${6:-}"
  local tool; tool="$(_get_mcp_tool "$sub")"
  [[ -z "$tool" ]] && { _err_json "unknown_subsystem" "no MCP tool for '$sub'"; return 5; }
  local pinv; pinv="$(route_locked_pipeline_version "$pid")" || return $?

  # Payload shape per PRD FR-5 (plan), FR-2 (build), FR-4 (verify).
  local payload
  payload=$(printf '{"project_id":%s,"role":"%s","directive":"%s","pipeline_version":"%s"' \
                   "$pid" "$role" "${directive//\"/\\\"}" "$pinv")
  [[ -n "$parent" ]] && payload+=",\"parent_directive_id\":\"$parent\""
  [[ -n "$budget" ]] && payload+=",\"budget_remaining_usd\":$budget"
  payload+="}"

  local resp did
  resp="$(_mcp_call "$tool" "$payload")" \
    || { _err_json "mcp_call_failed" "$tool dispatch failed pid=$pid"; return 6; }
  did="$(printf '%s' "$resp" | sed -n 's/.*"directive_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
  [[ -z "$did" ]] && { _err_json "no_directive_id" "MCP reply missing directive_id" "$resp"; return 7; }

  _psql <<SQL || { _err_json "db_error" "route_history insert failed"; return 8; }
INSERT INTO spine_lifecycle.route_history
       (project_id, phase, subsystem, role, directive_ref, metadata)
VALUES ($pid,
        (SELECT current_phase FROM spine_lifecycle.project WHERE id = $pid),
        '$sub', '$(_sql_esc "$role")', '$(_sql_esc "$did")',
        jsonb_build_object('pipeline_version','$(_sql_esc "$pinv")',
                           'parent_directive_id', NULLIF('$(_sql_esc "$parent")','')::text,
                           'tool','$tool'));
SQL
  _audit_dispatch "$pid" "$sub" "$role" "$did"
  printf '{"ok":true,"directive_id":"%s","tool":"%s","pipeline_version":"%s"}\n' \
    "$did" "$tool" "$pinv"
}

# Reply intake (STORY-9.4.3). Called by orchestrator's MCP listener on
# `*_completed` events. Sets completed_at + outcome on the matching row.
route_record_reply() {
  local did="$1" status="$2" err="${3:-}"
  local outcome
  case "$status" in
    completed|ok|success) outcome=completed ;;
    failed|error)         outcome=failed    ;;
    timeout)              outcome=timeout   ;;
    retry)                outcome=retry     ;;
    *) _err_json "bad_status" "unknown status '$status'"; return 9 ;;
  esac
  _psql <<SQL || { _err_json "db_error" "route_history update failed"; return 10; }
UPDATE spine_lifecycle.route_history
   SET completed_at = NOW(), outcome = '$outcome',
       metadata = metadata || jsonb_build_object('error', NULLIF('$(_sql_esc "$err")',''))
 WHERE directive_ref = '$(_sql_esc "$did")' AND completed_at IS NULL;
SQL
  printf '{"ok":true,"directive_id":"%s","outcome":"%s"}\n' "$did" "$outcome"
}

# Auto-remediation (STORY-9.8.1). Composes a remediation directive carrying
# prior findings and dispatches to target_sub (typically `build`). The new
# row links back via parent_directive_id so the verify-fail loop is queryable.
route_dispatch_remediation() {
  local failed_did="$1" findings_ref="$2" target_sub="$3"
  local row pid role
  row="$(_psql -c "SELECT project_id || '|' || role FROM spine_lifecycle.route_history
                    WHERE directive_ref = '$(_sql_esc "$failed_did")' LIMIT 1;")" \
    || { _err_json "db_error" "lookup failed_did=$failed_did"; return 11; }
  row="${row//[[:space:]]/}"
  pid="${row%%|*}"; role="${row#*|}"
  [[ -z "$pid" ]] && { _err_json "unknown_directive" "no route_history row for $failed_did"; return 12; }
  local directive="REMEDIATE: address findings $findings_ref (parent=$failed_did)"
  route_dispatch_to_subsystem "$target_sub" "$role" "$directive" "$pid" "$failed_did"
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    dispatch)  route_dispatch_to_subsystem "$@" ;;
    decide)    route_decide_subsystem      "$@" ;;
    reply)     route_record_reply          "$@" ;;
    remediate) route_dispatch_remediation  "$@" ;;
    -h|--help|"") sed -n '2,20p' "${BASH_SOURCE[0]}" >&2; exit 0 ;;
    *) _err_json "unknown_command" "no such subcommand: $cmd"; exit 64 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
