#!/usr/bin/env bash
# tools/smoke-test.sh — Spine v2 integration smoke-test harness.
# Codifies the manual sequence run during wave 8 (docs/STATUS.md §5).
# Phases mirror that table 1:1 so a green run means F1-F11 have not regressed.
# Bash-only; python3 -c only for narrow import / Pydantic checks (no venv).
# Exit: 0=PASS  1=any FAIL  2=env problem  3=harness error  64=unknown flag.

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DB_ENV_FILE="$REPO_ROOT/db/.env"
FLYWAY_SQL_DIR="$REPO_ROOT/db/flyway/sql"
TRANSITION_SH="$REPO_ROOT/orchestrator/lib/transition.sh"

PHASE="all"; FORMAT="text"; VERBOSE=0; CLEANUP=1; CI_MODE=0; USE_COLOR=1
# Parallel-indexed arrays (works under bash 3.2 — macOS default — which
# has no `declare -A`). RESULT_DATA[i] holds "status|msg" for RESULT_ORDER[i].
declare -a RESULT_ORDER=()
declare -a RESULT_DATA=()
_lookup() {
  local i n="${#RESULT_ORDER[@]}"
  for (( i=0; i<n; i++ )); do
    [[ "${RESULT_ORDER[$i]}" == "$1" ]] && { printf '%s' "${RESULT_DATA[$i]}"; return 0; }
  done
  return 1
}
declare -i COUNT_PASS=0 COUNT_FAIL=0 COUNT_WARN=0 COUNT_SKIP=0 COUNT_INFO=0
SMOKE_NAME_PREFIX="smoke-harness-$$"

# ─── helpers ─────────────────────────────────────────────────────────
_ts()  { date -u +%Y-%m-%dT%H:%M:%SZ; }
_log() { printf '%s smoke-test %s %s\n' "$(_ts)" "$1" "${*:2}" >&2; }
_color() {
  local c=""
  [[ $USE_COLOR -eq 1 && -t 1 ]] || { printf '%s' "$2"; return; }
  case "$1" in green) c='\033[32m';; red) c='\033[31m';; yellow) c='\033[33m';;
               blue) c='\033[34m';; grey) c='\033[90m';; bold) c='\033[1m';; esac
  printf '%b%s\033[0m' "$c" "$2"
}
_emit() {
  local status="$1" id="$2" msg="${3:-}" col
  case "$status" in PASS) col="$(_color green PASS)";; FAIL) col="$(_color red FAIL)";;
    WARN) col="$(_color yellow WARN)";; SKIP) col="$(_color grey SKIP)";;
    INFO) col="$(_color blue INFO)";; *) col="$status";; esac
  printf '%s %s %s\n' "$col" "$id" "$msg"
  RESULT_ORDER+=("$id"); RESULT_DATA+=("$status|$msg")
  case "$status" in PASS) COUNT_PASS+=1;; FAIL) COUNT_FAIL+=1;; WARN) COUNT_WARN+=1;;
    SKIP) COUNT_SKIP+=1;; INFO) COUNT_INFO+=1;; esac
}
_pass() { _emit PASS "$1" "${2:-}"; }; _fail() { _emit FAIL "$1" "${2:-}"; }
_warn() { _emit WARN "$1" "${2:-}"; }; _skip() { _emit SKIP "$1" "${2:-}"; }
_info() { _emit INFO "$1" "${2:-}"; }
_phase_banner() { [[ "$FORMAT" == text ]] && printf '\n%s %s\n' "$(_color bold "── Phase $1:")" "$2"; return 0; }

# Loads db/.env to build SPINE_DB_URL (the F8/F9 fix).
_load_db_env() {
  POSTGRES_DB=spine; POSTGRES_USER=spine; POSTGRES_PASSWORD=spine
  POSTGRES_HOST_PORT=33000
  [[ -f "$DB_ENV_FILE" ]] && { set -a; . "$DB_ENV_FILE"; set +a; }
  : "${POSTGRES_HOST_PORT:=33000}"
  SPINE_DB_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_HOST_PORT}/${POSTGRES_DB}"
  export SPINE_DB_URL
}
_psql() { psql "$SPINE_DB_URL" -v ON_ERROR_STOP=1 -A -t -X -q "$@"; }
_db_alive() { command -v psql >/dev/null 2>&1 && _psql -c 'SELECT 1;' >/dev/null 2>&1; }

# ─── phase 1: env pre-check ──────────────────────────────────────────
phase1_env() {
  _phase_banner 1 "environment pre-check"
  if command -v docker >/dev/null 2>&1; then
    _pass env.docker "docker on PATH"
    local s; s="$(docker ps --filter 'name=spine_postgres' --format '{{.Status}}' 2>/dev/null || true)"
    [[ -n "$s" ]] && _pass env.postgres_container "spine_postgres: $s" \
      || _fail env.postgres_container "spine_postgres not running — 'cd db && make up'"
  else _fail env.docker "docker not on PATH"; fi

  if command -v python3 >/dev/null 2>&1; then
    local v; v="$(python3 -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null || echo unknown)"
    python3 -c 'import sys;sys.exit(0 if sys.version_info[:2]>=(3,10) else 1)' 2>/dev/null \
      && _pass env.python "python3 $v" || _fail env.python "python3 $v (need >=3.10)"
  else _fail env.python "python3 not on PATH"; fi

  command -v psql >/dev/null 2>&1 \
    && _pass env.psql "$(psql --version 2>/dev/null | head -1)" \
    || _fail env.psql "psql not on PATH"

  command -v yq >/dev/null 2>&1 && _pass env.yq "yq present" \
    || _warn env.yq "yq missing — phases.yaml falls back to awk parser (F10)"

  local n; n="$(find "$FLYWAY_SQL_DIR" -maxdepth 1 -name 'V*.sql' 2>/dev/null | wc -l | tr -d ' ')"
  (( n >= 21 )) && _pass env.migrations "$n Flyway migrations on disk" \
    || _fail env.migrations "$n migrations on disk — expected >=21"
}

# ─── phase 2: DB schema verification ─────────────────────────────────
phase2_db() {
  _phase_banner 2 "DB schema verification"; _load_db_env
  if ! command -v psql >/dev/null 2>&1; then _skip db.connect "psql missing"; return 0; fi
  if ! _psql -c 'SELECT 1;' >/dev/null 2>&1; then
    _fail db.connect "cannot connect to $SPINE_DB_URL (db/.env; F8/F9)"; return 0
  fi
  _pass db.connect "connected to $SPINE_DB_URL"

  # Must be an array, not a space-separated string: file-level IFS=$'\n\t'
  # would otherwise treat the whole list as one token (no space-splitting).
  local -a schemas=(spine_audit spine_calibration spine_eval spine_kg \
                    spine_lifecycle spine_memory spine_recording \
                    spine_verify_audit spine_verify_threat_intel)
  local present sch
  present="$(_psql -c "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'spine_%' ORDER BY 1;" 2>/dev/null || true)"
  for sch in "${schemas[@]}"; do
    printf '%s\n' "$present" | grep -qx "$sch" \
      && _pass "db.schema.$sch" "present" \
      || _fail "db.schema.$sch" "missing — 'cd db && make migrate' or apply V14-V21"
  done

  local pair sch_name min actual
  for pair in spine_lifecycle:5 spine_audit:1 spine_kg:2 spine_eval:1; do
    sch_name="${pair%:*}"; min="${pair#*:}"
    actual="$(_psql -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='$sch_name' AND table_type='BASE TABLE';" 2>/dev/null | tr -d ' ' || echo 0)"
    [[ -z "$actual" ]] && actual=0
    (( actual >= min )) && _pass "db.tables.$sch_name" "$actual tables (>=$min)" \
      || _fail "db.tables.$sch_name" "$actual tables (expected >=$min)"
  done
}

# ─── phase 3: Python imports + tool registry ─────────────────────────
phase3_python() {
  _phase_banner 3 "Python imports + tool registry"
  if ! command -v python3 >/dev/null 2>&1; then _skip py.imports "python3 missing"; return 0; fi
  export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

  local out
  out="$(python3 - <<'PY' 2>&1 || true
from shared.mcp.tools import TOOL_REGISTRY, discover_tools
discover_tools(); print(len(TOOL_REGISTRY))
PY
)"
  [[ "$out" =~ ^[0-9]+$ ]] && (( out >= 27 )) \
    && _pass py.mcp_tools "$out tools registered (>=27)" \
    || _fail py.mcp_tools "discover_tools failed or low: $out"

  out="$(python3 - <<'PY' 2>&1 || true
from pathlib import Path
from shared.skills.registry import discover_skills
print(len(discover_skills(Path("shared/skills/skills"))))
PY
)"
  [[ "$out" =~ ^[0-9]+$ ]] && (( out >= 5 )) \
    && _pass py.skills "$out skills discovered (>=5)" \
    || _fail py.skills "discover_skills failed or low: $out"

  local mod
  for mod in plan.artifacts.prd_v1 plan.artifacts.trd_v1 plan.artifacts.roadmap_v1 \
             shared.schemas.build.build_artifact shared.audit.audit_record \
             shared.cost.router shared.cost.classifier; do
    python3 -c "import $mod" 2>/dev/null \
      && _pass "py.import.$mod" "import OK" \
      || _fail "py.import.$mod" "import failed"
  done

  python3 -c 'from shared.api import app' 2>/dev/null \
    && _pass py.import.shared.api "FastAPI app importable" \
    || _info py.import.shared.api "shared.api unavailable (likely FastAPI missing; F4 — optional)"
}

# ─── phase 4: Pydantic schema validators ─────────────────────────────
phase4_pydantic() {
  _phase_banner 4 "Pydantic schema validators"
  if ! command -v python3 >/dev/null 2>&1; then _skip py.pydantic "python3 missing"; return 0; fi
  export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
  local out
  out="$(python3 - <<'PY' 2>&1 || true
from datetime import datetime, timezone
from decimal import Decimal
def emit(c,s,m=""): print(f"{c}|{s}|{m}")
try:
    from shared.schemas.build.build_artifact import (BuildArtifact, BuildCost, BuildRuntime, CodeChange)
    from plan.artifacts._base import ArtifactMetadata
    now = datetime.now(timezone.utc)
    BuildArtifact(directive_id="d1", project_id="p1", phase="build_in_progress",
        role="engineer", pipeline_version="v1", rationale="smoke draft",
        cost=BuildCost(tokens_input=1, tokens_output=1, model="m", cost_usd=Decimal("0"), tier="low"),
        runtime=BuildRuntime(started_at=now, completed_at=now, duration_seconds=0),
        metadata=ArtifactMetadata(created_by="smoke", created_at=now, last_modified=now))
    emit("pyd.build_draft","PASS","draft constructs OK")
except Exception as e:
    emit("pyd.build_draft","FAIL",f"{type(e).__name__}: {e}")
try:
    BuildArtifact(directive_id="d2", project_id="p1", phase="build_in_progress",
        role="engineer", pipeline_version="v1", status="sealed", rationale="smoke refuse",
        code_changes=[CodeChange(path="x", change_type="create", diff_hash="0"*64, lines_added=1, lines_removed=0)],
        kg_impact=[],
        cost=BuildCost(tokens_input=1, tokens_output=1, model="m", cost_usd=Decimal("0"), tier="low"),
        runtime=BuildRuntime(started_at=now, completed_at=now, duration_seconds=0),
        metadata=ArtifactMetadata(created_by="smoke", created_at=now, last_modified=now))
    emit("pyd.build_refuse_seal","FAIL","validator did not fire")
except Exception as e:
    if "kg_impact" in str(e) or "impact_radius" in str(e):
        emit("pyd.build_refuse_seal","PASS","validator fired as expected")
    else:
        emit("pyd.build_refuse_seal","FAIL",f"wrong error: {e}")
try:
    from plan.artifacts.prd_v1 import PRDv1
    PRDv1(project_id="p", project_name="n", project_type="web_app",
          problem_statement="TBD",
          metadata=ArtifactMetadata(created_by="smoke", created_at=now, last_modified=now))
    emit("pyd.prd_tbd_reject","FAIL","TBD problem_statement accepted")
except Exception as e:
    if "TBD" in str(e) or "empty" in str(e).lower():
        emit("pyd.prd_tbd_reject","PASS","TBD rejected as expected")
    else:
        emit("pyd.prd_tbd_reject","FAIL",f"wrong error: {e}")
PY
)"
  local line cid st msg
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if [[ "$line" == *"|"*"|"* ]]; then
      cid="${line%%|*}"; line="${line#*|}"; st="${line%%|*}"; msg="${line#*|}"
      _emit "$st" "$cid" "$msg"
    else _info pyd.trace "$line"; fi
  done <<< "$out"
}

# ─── phase 5: lifecycle flow ─────────────────────────────────────────
phase5_lifecycle() {
  _phase_banner 5 "Lifecycle flow"; _load_db_env
  _db_alive || { _skip lc.flow "DB unreachable"; return 0; }
  [[ -f "$TRANSITION_SH" ]] || { _skip lc.flow "transition.sh missing"; return 0; }

  local name="${SMOKE_NAME_PREFIX}-001" pid
  pid="$(_psql -c "INSERT INTO spine_lifecycle.project
    (name, project_type, pipeline_version, pipeline_manifest_path, owner_user)
    VALUES ('$name','web_app','v1','orchestrator/state/phases.yaml','smoke-harness')
    RETURNING id;" 2>/dev/null | tr -d ' \r' | head -1 || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || { _fail lc.insert "could not insert (id=$pid)"; return 0; }
  _pass lc.insert "project id=$pid name=$name"

  local cur new_phase trans_count
  cur="$(_psql -c "SELECT current_phase FROM spine_lifecycle.project WHERE id=$pid;" 2>/dev/null | tr -d ' \r')"
  [[ "$cur" == intake ]] && _pass lc.initial_phase "current_phase=intake" \
    || _fail lc.initial_phase "current_phase=$cur (expected intake)"

  bash "$TRANSITION_SH" validate "$pid" plan_in_progress >/dev/null 2>&1 \
    && _pass lc.validate "intake -> plan_in_progress allowed" \
    || _fail lc.validate "validate failed (yq? — see F10)"

  bash "$TRANSITION_SH" execute "$pid" plan_in_progress smoke-harness "wave-9 smoke" >/dev/null 2>&1 \
    && _pass lc.execute "execute returned OK" \
    || _fail lc.execute "execute failed (see F8/F9/F10/F11)"

  new_phase="$(_psql -c "SELECT current_phase FROM spine_lifecycle.project WHERE id=$pid;" 2>/dev/null | tr -d ' \r')"
  [[ "$new_phase" == plan_in_progress ]] \
    && _pass lc.phase_advanced "project at plan_in_progress" \
    || _fail lc.phase_advanced "project still at '$new_phase'"

  trans_count="$(_psql -c "SELECT count(*) FROM spine_lifecycle.transition WHERE project_id=$pid;" 2>/dev/null | tr -d ' \r')"
  [[ "${trans_count:-0}" =~ ^[1-9][0-9]*$ ]] \
    && _pass lc.transition_row "$trans_count transition row(s) written" \
    || _fail lc.transition_row "no transition row found"
}

# ─── phase 6: KG MCP tools ───────────────────────────────────────────
phase6_kg() {
  _phase_banner 6 "KG MCP tools"; _load_db_env
  _db_alive || { _skip kg.fixture "DB unreachable"; return 0; }
  _psql -c "SELECT to_regclass('spine_kg.kg_node');" 2>/dev/null | grep -q kg_node \
    || { _skip kg.fixture "spine_kg.kg_node missing (F3: pgvector not installed)"; return 0; }
  python3 -c "from shared.mcp.tools import discover_tools, TOOL_REGISTRY; discover_tools(); assert 'find_callers' in TOOL_REGISTRY" 2>/dev/null \
    && _pass kg.find_callers_registered "find_callers tool registered" \
    || _fail kg.find_callers_registered "find_callers not in TOOL_REGISTRY"

  # graph_query — generic escape-hatch over kg_node / kg_edge.
  export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
  local kg_script kg_out
  kg_script="$(mktemp "${TMPDIR:-/tmp}/spine-graph-query-smoke-XXXX.py")"
  cat >"$kg_script" <<'PY'
from shared.mcp.tools import discover_tools, TOOL_REGISTRY
discover_tools()
def call(name, payload):
    spec = TOOL_REGISTRY[name]
    return spec.fn(spec.input_model.model_validate(payload)).model_dump(mode="json")
def emit(cid, ok, msg=""): print(f"{cid}|{'PASS' if ok else 'FAIL'}|{msg}")
# 1) Valid filtered query — returns ok, mode=nodes, total_returned>=0.
try:
    r = call("graph_query", {"project_id": "smoke", "node_type": "Function", "limit": 5})
    emit("kg.graph_query.ok", r["status"] == "ok" and r["data"]["mode"] == "nodes"
         and isinstance(r["data"]["total_returned"], int), str(r)[:200])
except Exception as e:
    emit("kg.graph_query.ok", False, f"{type(e).__name__}: {str(e)[:200]}")
# 2) limit > 500 must be rejected — handled by Pydantic le=500 (validation error).
try:
    bad = call("graph_query", {"project_id": "smoke", "node_type": "Function", "limit": 1000})
    emit("kg.graph_query.limit_too_large",
         bad["status"] == "error" and (bad.get("error") or {}).get("code") == "limit_too_large",
         str(bad.get("error"))[:200])
except Exception as e:
    emit("kg.graph_query.limit_too_large", "ValidationError" in type(e).__name__
         or "limit" in str(e).lower(), f"{type(e).__name__}: {str(e)[:100]}")
# 3) Both filters unset must be rejected with no_filter.
nf = call("graph_query", {"project_id": "smoke"})
emit("kg.graph_query.no_filter",
     nf["status"] == "error" and (nf.get("error") or {}).get("code") == "no_filter",
     str(nf.get("error"))[:200])
PY
  kg_out="$(SPINE_DB_URL="$SPINE_DB_URL" python3 "$kg_script" 2>&1 || true)"
  rm -f "$kg_script"
  local line cid st msg
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if [[ "$line" == *"|"*"|"* ]]; then
      cid="${line%%|*}"; line="${line#*|}"; st="${line%%|*}"; msg="${line#*|}"
      _emit "$st" "$cid" "$msg"
    elif [[ $VERBOSE -eq 1 ]]; then _info kg.trace "$line"; fi
  done <<< "$kg_out"

  # org_standards_get — fetch default bundle + reject unknown bundle.
  local std_script std_out
  std_script="$(mktemp "${TMPDIR:-/tmp}/spine-standards-smoke-XXXX.py")"
  cat >"$std_script" <<'PY'
from shared.mcp.tools import discover_tools, TOOL_REGISTRY
discover_tools()
def call(name, payload):
    spec = TOOL_REGISTRY[name]
    return spec.fn(spec.input_model.model_validate(payload)).model_dump(mode="json")
def emit(cid, ok, msg=""): print(f"{cid}|{'PASS' if ok else 'FAIL'}|{msg}")
# 1) Default bundle loads + parses (in-repo; no SPINE_HOME needed).
r = call("org_standards_get", {"project_id": "smoke", "bundle_name": "default"})
ok1 = (r["status"] == "ok"
       and isinstance(r["data"]["standards"], dict)
       and r["data"]["standards"].get("identity", {}).get("bundle_id"))
emit("std.default_bundle_loads", ok1, str(r.get("error") or r["data"].get("bundle_id"))[:200])
emit("std.default_bundle_hashed",
     bool(r["data"].get("content_sha256")) and len(r["data"]["content_sha256"]) == 64,
     r["data"].get("content_sha256", "")[:16])
# 2) Unknown bundle → structured error with code='unknown_bundle'.
u = call("org_standards_get", {"project_id": "smoke", "bundle_name": "does-not-exist-xyz"})
emit("std.unknown_bundle_rejected",
     u["status"] == "error" and (u.get("error") or {}).get("code") == "unknown_bundle",
     str(u.get("error"))[:200])
PY
  std_out="$(SPINE_DB_URL="$SPINE_DB_URL" python3 "$std_script" 2>&1 || true)"
  rm -f "$std_script"
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if [[ "$line" == *"|"*"|"* ]]; then
      cid="${line%%|*}"; line="${line#*|}"; st="${line%%|*}"; msg="${line#*|}"
      _emit "$st" "$cid" "$msg"
    elif [[ $VERBOSE -eq 1 ]]; then _info std.trace "$line"; fi
  done <<< "$std_out"
}

# ─── phase 7: optional integrations ──────────────────────────────────
phase7_optional() {
  _phase_banner 7 "Optional integrations"
  command -v yq >/dev/null 2>&1 && _pass opt.yq "yq present" || _info opt.yq "yq missing (F10 mitigation)"
  python3 -c 'import fastapi' 2>/dev/null && _pass opt.fastapi "fastapi importable" || _info opt.fastapi "fastapi not installed (F4)"
  _load_db_env
  if _db_alive; then
    _psql -c "SELECT 1 FROM pg_available_extensions WHERE name='vector';" 2>/dev/null | grep -q 1 \
      && _pass opt.pgvector "pgvector extension available" \
      || _warn opt.pgvector "pgvector unavailable (F3) — switch image to pgvector/pgvector:pg16"
  else _skip opt.pgvector "DB unreachable"; fi
}

# ─── phase 8: orchestrator MCP tools (D8 wave) ───────────────────────
# End-to-end: project_create -> project_status -> approval_grant ->
# phase_advance. Verifies real DB writes land + the HMAC token actually
# verifies. Skips cleanly if Python or DB are unavailable.
phase8_mcp_tools() {
  _phase_banner 8 "Orchestrator MCP tools (D8)"
  if ! command -v python3 >/dev/null 2>&1; then _skip mcp.runtime "python3 missing"; return 0; fi
  _load_db_env
  _db_alive || { _skip mcp.runtime "DB unreachable"; return 0; }
  export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
  # Use a throwaway key path so we don't disturb the dev install at ~/.spine.
  local key_dir; key_dir="$(mktemp -d "${TMPDIR:-/tmp}/spine-mcp-smoke-XXXX")"
  local key_path="$key_dir/hmac.key"
  export SPINE_APPROVAL_KEY_PATH="$key_path"

  local name="${SMOKE_NAME_PREFIX}-mcp"
  local out script
  script="$(mktemp "${TMPDIR:-/tmp}/spine-mcp-smoke-script-XXXX.py")"
  cat >"$script" <<'PY'
import json, os, sys
from shared.mcp.tools import discover_tools, TOOL_REGISTRY
discover_tools()
def call(name, payload):
    spec = TOOL_REGISTRY[name]
    return spec.fn(spec.input_model.model_validate(payload)).model_dump(mode="json")
def emit(cid, ok, msg=""): print(f"{cid}|{'PASS' if ok else 'FAIL'}|{msg}")
NAME = os.environ["SMOKE_NAME"]
# 1) project_create
r = call("project_create", {"name": NAME, "project_type": "greenfield", "owner": "smoke-mcp"})
emit("mcp.project_create.ok", r["status"] == "ok", json.dumps(r)[:200])
if r["status"] != "ok":
    sys.exit(0)
proj_uuid = r["data"]["project_uuid"]
proj_id   = r["data"]["id"]
emit("mcp.project_create.row", isinstance(proj_id, int) and proj_id > 0, f"id={proj_id}")
emit("mcp.project_create.uuid", len(proj_uuid) == 36 and proj_uuid.count("-") == 4, proj_uuid)
emit("mcp.project_create.initial_phase", r["data"]["initial_phase"] == "intake", r["data"]["initial_phase"])
# 2) project_status (by UUID)
s = call("project_status", {"project_id": proj_uuid})
emit("mcp.project_status.ok", s["status"] == "ok", "")
emit("mcp.project_status.phase", s["data"].get("current_phase") == "intake", s["data"].get("current_phase"))
# 3) advance intake -> plan_in_progress (no gate)
adv = call("phase_advance", {"project_id": proj_uuid, "target_phase": "plan_in_progress",
                              "actor": "smoke-mcp", "rationale": "D8 smoke"})
emit("mcp.phase_advance.no_gate", adv["status"] == "ok" and adv["data"]["accepted"], json.dumps(adv)[:200])
emit("mcp.phase_advance.transition_id", adv["data"]["transition_id"] > 0, f"tid={adv['data']['transition_id']}")
# 4) approval_grant for plan_approved (gated phase)
g = call("approval_grant", {"project_id": proj_uuid, "phase": "plan_approved",
                             "approver": "smoke-approver", "notes": "D8 smoke",
                             "ttl_hours": 1})
emit("mcp.approval_grant.ok", g["status"] == "ok", json.dumps(g)[:200])
token = g["data"].get("token", "")
emit("mcp.approval_grant.token_shape", "." in token and len(token) > 40, f"len={len(token)}")
# Verify the token round-trips through verify_token.
from pathlib import Path
from orchestrator.lib.approval import verify_token
vt = verify_token(token, Path(os.environ["SPINE_APPROVAL_KEY_PATH"]),
                  expected_project_id=str(proj_id), expected_phase="plan_approved")
emit("mcp.approval_grant.verifies", vt["valid"], ",".join(vt.get("errors", [])))
# 5) phase_advance to plan_approved with the token (gated path)
adv2 = call("phase_advance", {"project_id": proj_uuid, "target_phase": "plan_approved",
                               "actor": "smoke-mcp", "rationale": "D8 gated",
                               "approval_token": token})
emit("mcp.phase_advance.gated", adv2["status"] == "ok" and adv2["data"]["accepted"], json.dumps(adv2)[:200])
# 6) project_status reflects the advance
s2 = call("project_status", {"project_id": proj_uuid})
emit("mcp.project_status.after", s2["data"].get("current_phase") == "plan_approved",
     s2["data"].get("current_phase"))
# 7) Idempotency: second project_create with same name+owner must error.
dup = call("project_create", {"name": NAME, "project_type": "greenfield", "owner": "smoke-mcp"})
emit("mcp.project_create.idempotent", dup["status"] == "error" and
     (dup.get("error") or {}).get("code") == "project_already_exists",
     (dup.get("error") or {}).get("code", ""))
# 8) Invalid approval token rejected on a gated target phase.
bad = call("phase_advance", {"project_id": proj_uuid, "target_phase": "verify_approved",
                              "actor": "smoke-mcp", "approval_token": "tampered.token"})
emit("mcp.phase_advance.invalid_token", bad["status"] == "error" and
     (bad.get("error") or {}).get("code") == "invalid_approval_token",
     (bad.get("error") or {}).get("code", ""))
# 9) Audit rows actually landed in spine_audit (one per consequential op).
import subprocess
db_url = os.environ["SPINE_DB_URL"]
def _q(sql):
    p = subprocess.run(["psql", db_url, "-At", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
                       capture_output=True, text=True, timeout=10)
    return p.stdout.strip() if p.returncode == 0 else f"ERR:{p.stderr.strip()}"
n_created  = _q(f"SELECT count(*) FROM spine_audit.audit_event WHERE project_id={proj_id} AND action='project_created';")
n_advanced = _q(f"SELECT count(*) FROM spine_audit.audit_event WHERE project_id={proj_id} AND action='phase_advanced';")
n_approved = _q(f"SELECT count(*) FROM spine_audit.audit_event WHERE project_id={proj_id} AND action='approval_granted';")
emit("mcp.audit.project_created",  n_created == "1",  f"rows={n_created}")
emit("mcp.audit.phase_advanced",   n_advanced == "2", f"rows={n_advanced}")
emit("mcp.audit.approval_granted", n_approved == "1", f"rows={n_approved}")
# 10) phase_history rows: intake (closed) + plan_in_progress (closed) + plan_approved (open)
n_phist = _q(f"SELECT count(*) FROM spine_lifecycle.phase_history WHERE project_id={proj_id};")
emit("mcp.lifecycle.phase_history_rows", n_phist == "3", f"rows={n_phist}")
PY
  out="$(SPINE_DB_URL="$SPINE_DB_URL" SPINE_APPROVAL_KEY_PATH="$key_path" \
         SMOKE_NAME="$name" python3 "$script" 2>&1 || true)"
  rm -f "$script"
  local line cid st msg
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if [[ "$line" == *"|"*"|"* ]]; then
      cid="${line%%|*}"; line="${line#*|}"; st="${line%%|*}"; msg="${line#*|}"
      _emit "$st" "$cid" "$msg"
    elif [[ $VERBOSE -eq 1 ]]; then _info mcp.trace "$line"; fi
  done <<< "$out"

  # Tidy: rm the throwaway key + dir; the project rows are removed by cleanup_fixtures.
  rm -rf "$key_dir" 2>/dev/null || true
  unset SPINE_APPROVAL_KEY_PATH
}

# ─── phase 9: plan_dispatch + intake_runner (D8 follow-up) ───────────
# Asserts the non-interactive guard fires on plan_dispatch (so the MCP
# tool doesn't block forever on stdin), the runner module is importable,
# and a PRD built from a minimal stub of intake answers round-trips.
phase9_intake() {
  _phase_banner 9 "Plan dispatch + intake runner"
  if ! command -v python3 >/dev/null 2>&1; then _skip intake.runtime "python3 missing"; return 0; fi
  export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
  local out
  out="$(python3 - <<'PY' 2>&1 || true
def emit(c,s,m=""): print(f"{c}|{s}|{m}")
# Importable?
try:
    from plan.runtime.intake_runner import (
        run_intake, IntakeNotInteractive, synthesize_prd_draft,
    )
    emit("intake.import","PASS","plan.runtime.intake_runner OK")
except Exception as e:
    emit("intake.import","FAIL",f"{type(e).__name__}: {e}")
    raise SystemExit(0)

# Non-tty guard on plan_dispatch fires?
try:
    from shared.mcp.tools import discover_tools, TOOL_REGISTRY
    discover_tools()
    spec = TOOL_REGISTRY["plan_dispatch"]
    payload = spec.input_model.model_validate({
        "project_id": "0", "phase": "plan_in_progress",
        "directive": "smoke directive — non-tty guard",
        "pipeline_version": "1.0.0",
    })
    resp = spec.fn(payload).model_dump(mode="json")
    if resp.get("status") == "error" and (resp.get("error") or {}).get("code") == "intake_requires_tty":
        emit("intake.plan_dispatch_no_tty","PASS","friendly error fired")
    else:
        emit("intake.plan_dispatch_no_tty","FAIL",str(resp)[:200])
except Exception as e:
    emit("intake.plan_dispatch_no_tty","FAIL",f"{type(e).__name__}: {e}")

# PRD synthesized from minimal cli-tool answers validates round-trip?
try:
    from plan.artifacts.prd_v1 import PRDv1
    prd = synthesize_prd_draft(
        project_uuid="00000000-0000-0000-0000-000000000000",
        project_name="smoke-intake",
        template_name="cli-tool",
        actor="smoke",
        answers={
            "audience": "developer_dx",
            "primary_job": "`foo bar` runs the smoke check",
            "install_method": ["homebrew"],
            "output_formats": ["human_readable_tty"],
            "cross_platform": ["macos_arm"],
            "config_file": "no_config_flags_only",
            "subcommand_depth": "single_verb",
            "composability": True, "tty_awareness": True,
            "dependencies_runtime": "None — single static binary",
            "must_should_could": "MUST: init / SHOULD: doctor / COULD: plugins",
            "out_of_scope": "No GUI; no daemon",
        },
    )
    dump = prd.model_dump(mode="json")
    PRDv1.model_validate(dump)
    if dump.get("project_name") == "smoke-intake" and dump["goals"]["must"]:
        emit("intake.prd_round_trip","PASS",f"fields={len(dump)} must_goals={len(dump['goals']['must'])}")
    else:
        emit("intake.prd_round_trip","FAIL","unexpected PRD shape")
except Exception as e:
    emit("intake.prd_round_trip","FAIL",f"{type(e).__name__}: {e}")

# Template loader sees every shipped template.
try:
    from plan.runtime.intake_runner import load_template, TEMPLATES_DIR
    missing = []
    for t in ("cli-tool","web-app","internal-tool","data-pipeline","mobile","api-service"):
        try:
            load_template(t)
        except Exception as e:
            missing.append(f"{t}({e.__class__.__name__})")
    if missing:
        emit("intake.templates_load","FAIL",",".join(missing))
    else:
        emit("intake.templates_load","PASS","all 6 shipped templates load")
except Exception as e:
    emit("intake.templates_load","FAIL",f"{type(e).__name__}: {e}")

# Bug 1 regression: thin open-text answers must be rejected.
try:
    from plan.runtime.intake_runner import IntakeAnswerRejected, _is_thin_open_answer
    bad_cases = [("x", "too_short"), ("MUST: x", None),
                 ("tbd", "placeholder"), ("Other:", "placeholder"),
                 ("?", "placeholder"), ("  ", "empty")]
    failures = []
    for value, expect in bad_cases:
        got = _is_thin_open_answer(value)
        # MUST: x is 7 chars + 2 words, passes by design. Substance check
        # is per-answer; the tier parser handles the SHOULD/COULD split.
        if expect is None:
            if got is not None:
                failures.append(f"{value!r}: expected pass, got {got!r}")
        else:
            if got != expect:
                failures.append(f"{value!r}: expected {expect!r}, got {got!r}")
    # The dogfood repro: a 1-char open answer must be flagged too_short.
    if _is_thin_open_answer("x") != "too_short":
        failures.append("'x' not too_short")
    if failures:
        emit("intake.bug1_answer_too_thin","FAIL","; ".join(failures))
    else:
        emit("intake.bug1_answer_too_thin","PASS","heuristic flags thin answers")
except Exception as e:
    emit("intake.bug1_answer_too_thin","FAIL",f"{type(e).__name__}: {e}")

# Bug 1 regression: IntakeAnswerRejected fires through run_intake on the
# non-tty path. We feed a 1-char open answer and expect the exception
# (not a happily-synthesized PRD with a thin statement).
try:
    import io, os, subprocess
    from plan.runtime.intake_runner import run_intake, IntakeAnswerRejected
    db_url = os.environ.get("SPINE_DB_URL", "")
    if not db_url:
        emit("intake.bug1_regression_thin","SKIP","SPINE_DB_URL unset")
    else:
        proj_name = os.environ.get("SMOKE_NAME","smoke") + "-bug1-thin"
        ins_sql = (
            "INSERT INTO spine_lifecycle.project (name, project_type, "
            "pipeline_version, pipeline_manifest_path, owner_user) "
            "VALUES (" + repr(proj_name) + ",'greenfield','v1',"
            "'orchestrator/state/phases.yaml','smoke-harness') RETURNING id;"
        ).replace("'" + proj_name + "'", "'" + proj_name + "'")
        # The .replace above is a no-op; kept for clarity that repr() already
        # quoted the name. psql wants single quotes; repr() produces them.
        ins_sql = ins_sql.replace('"' + proj_name + '"', "'" + proj_name + "'")
        out = subprocess.run(
            ["psql", db_url, "-At", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", ins_sql],
            capture_output=True, text=True, timeout=10,
        )
        pid = out.stdout.strip()
        # Stub stdin: question 1 (single_choice audience) gets "1"; the
        # second question is the open primary_job — we feed a 1-char value
        # so the substance check fires.
        stdin = io.StringIO("1\nx\n")
        stdout = io.StringIO()
        os.environ["SPINE_INTAKE_ALLOW_NONTTY"] = "1"
        try:
            run_intake(pid, template="cli-tool", actor="smoke", in_=stdin, out=stdout)
            emit("intake.bug1_regression_thin","FAIL","run_intake accepted thin answer")
        except IntakeAnswerRejected as exc:
            ok = exc.question_id == "primary_job" and exc.reason == "too_short"
            emit("intake.bug1_regression_thin", "PASS" if ok else "FAIL",
                 "qid=" + str(exc.question_id) + " reason=" + str(exc.reason))
        except Exception as exc:
            emit("intake.bug1_regression_thin","FAIL",
                 "wrong exception " + type(exc).__name__ + ": " + str(exc))
        finally:
            os.environ.pop("SPINE_INTAKE_ALLOW_NONTTY", None)
except Exception as e:
    emit("intake.bug1_regression_thin","FAIL", type(e).__name__ + ": " + str(e))

# Bug 2 regression: tier-splitting MUST/SHOULD/COULD in one answer.
# The fix splits on tier markers, then within each tier on commas,
# semicolons, or newlines (NOT periods, which mangles abbreviations).
try:
    prd = synthesize_prd_draft(
        project_uuid="00000000-0000-0000-0000-000000000000",
        project_name="smoke-bug2",
        template_name="cli-tool",
        actor="smoke",
        answers={
            "audience": "developer_dx",
            "primary_job": "organize files in Downloads into typed folders",
            "install_method": ["homebrew"],
            "output_formats": ["human_readable_tty"],
            "cross_platform": ["macos_arm"],
            "config_file": "no_config_flags_only",
            "subcommand_depth": "single_verb",
            "composability": True, "tty_awareness": True,
            "dependencies_runtime": "stdlib only",
            "must_should_could": "MUST: organize, dry-run, undo. SHOULD: watch mode, doctor. COULD: plugins",
            "out_of_scope": "No GUI; no daemon",
        },
    )
    must = [g.statement for g in prd.goals.must]
    should = [g.statement for g in prd.goals.should]
    could = [g.statement for g in prd.goals.could]
    issues = []
    if must != ["organize", "dry-run", "undo"]:
        issues.append(f"must={must!r}")
    if should != ["watch mode", "doctor"]:
        issues.append(f"should={should!r}")
    if could != ["plugins"]:
        issues.append(f"could={could!r}")
    # Belt-and-braces: no SHOULD text should bleed into a MUST goal.
    for m in must:
        if "SHOULD" in m.upper() or "COULD" in m.upper():
            issues.append(f"tier-bleed into must: {m!r}")
    if issues:
        emit("intake.bug2_tier_split","FAIL","; ".join(issues))
    else:
        emit("intake.bug2_tier_split","PASS",
             f"must={len(must)} should={len(should)} could={len(could)}")
except Exception as e:
    emit("intake.bug2_tier_split","FAIL",f"{type(e).__name__}: {e}")
PY
)"
  local line cid st msg
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if [[ "$line" == *"|"*"|"* ]]; then
      cid="${line%%|*}"; line="${line#*|}"; st="${line%%|*}"; msg="${line#*|}"
      _emit "$st" "$cid" "$msg"
    elif [[ $VERBOSE -eq 1 ]]; then _info intake.trace "$line"; fi
  done <<< "$out"
}

# ─── phase 10: build_dispatch + build_completed (STORY-7.2.2/7.2.3) ──
# End-to-end: refuse without PRD; succeed with shimmed PRD; refuse on
# missing brief; refuse on project_id mismatch; succeed with valid
# BuildArtifact; build_history grows on a second ingest. No phase
# transitions are exercised — the orchestrator owns those.
phase10_build() {
  _phase_banner 10 "Build dispatch + completion"
  if ! command -v python3 >/dev/null 2>&1; then _skip build.runtime "python3 missing"; return 0; fi
  _load_db_env
  _db_alive || { _skip build.runtime "DB unreachable"; return 0; }
  export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

  local out script
  script="$(mktemp "${TMPDIR:-/tmp}/spine-build-smoke-XXXX.py")"
  cat >"$script" <<'PY'
import json, os, subprocess, sys
from datetime import datetime, timezone
from decimal import Decimal
from shared.mcp.tools import discover_tools, TOOL_REGISTRY
discover_tools()

def emit(cid, ok, msg=""): print(f"{cid}|{'PASS' if ok else 'FAIL'}|{msg}")
def call(name, payload):
    spec = TOOL_REGISTRY[name]
    return spec.fn(spec.input_model.model_validate(payload)).model_dump(mode="json")

db_url = os.environ["SPINE_DB_URL"]
def _q(sql, *, capture_err=False):
    p = subprocess.run(["psql", db_url, "-At", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
                       capture_output=True, text=True, timeout=15)
    if p.returncode != 0:
        return f"ERR:{p.stderr.strip()}" if capture_err else ""
    return p.stdout.strip()

PREFIX = os.environ["SMOKE_NAME"]
# Build fixtures via project_create to get a real BIGSERIAL id + uuid.
def _mk(name_suffix):
    r = call("project_create", {"name": f"{PREFIX}-{name_suffix}",
                                "project_type": "greenfield", "owner": "smoke-build"})
    assert r["status"] == "ok", json.dumps(r)
    return r["data"]["id"], r["data"]["project_uuid"]

# 1) build_dispatch refuses without PRD.
pid_a, uuid_a = _mk("no-prd")
r = call("build_dispatch", {"project_id": str(pid_a), "pipeline_version": "1.0.0",
                            "actor": "smoke-build"})
emit("build.dispatch.no_prd",
     r["status"] == "error" and (r.get("error") or {}).get("code") == "no_validated_prd",
     json.dumps(r)[:200])

# 2) build_dispatch succeeds with a PRD shimmed via psql.
pid_b, uuid_b = _mk("with-prd")
# Build a minimally-valid PRDv1 JSON dump and merge it into metadata.prd_draft.
from plan.artifacts.prd_v1 import PRDv1, Goals, Stakeholder
from plan.artifacts._base import (AcceptanceCriterion, ArtifactMetadata, Goal,
                                  ProjectType as PRDProjectType)
prd = PRDv1(
    project_id=uuid_b, project_name=f"{PREFIX}-with-prd",
    project_type=PRDProjectType.CLI_TOOL,
    problem_statement="smoke MUST not be TBD here",
    users_stakeholders=[Stakeholder(name="smoke-user", needs="happy path")],
    goals=Goals(must=[Goal(id="G-M-1", statement="ship the cli command")],
                should=[Goal(id="G-S-1", statement="emit json on --json")],
                could=[]),
    in_scope=["primary command"],
    out_of_scope=["no gui"],
    acceptance_criteria=[
        AcceptanceCriterion(id="AC-1", given="a tty", when="run the cli",
                            then="exit 0"),
        AcceptanceCriterion(id="AC-MUST-1", then="ship the cli command delivered"),
    ],
    open_questions=[],
    metadata=ArtifactMetadata(created_by="smoke"),
)
prd_dump_json = prd.model_dump_json()
# Use a parameterized-ish psql write: jsonb_build_object('prd_draft', $$...$$::jsonb).
# We escape single quotes by doubling them.
esc = prd_dump_json.replace("'", "''")
_q(f"UPDATE spine_lifecycle.project SET metadata = metadata || "
   f"jsonb_build_object('prd_draft', '{esc}'::jsonb) WHERE id={pid_b};")
r = call("build_dispatch", {"project_id": str(pid_b), "pipeline_version": "1.0.0",
                            "actor": "smoke-build"})
emit("build.dispatch.with_prd.ok",
     r["status"] == "ok" and r["data"]["engineering_goals_count"] > 0,
     json.dumps(r)[:200])
brief_id = r["data"].get("brief_id") if r["status"] == "ok" else ""
# Verify it actually landed.
landed = _q(f"SELECT metadata->'build_brief'->>'brief_id' FROM spine_lifecycle.project "
            f"WHERE id={pid_b};")
emit("build.dispatch.brief_in_db", landed == brief_id, f"db={landed} resp={brief_id}")
# And an audit row fired for build_dispatched.
n_disp = _q(f"SELECT count(*) FROM spine_audit.audit_event "
            f"WHERE project_id={pid_b} AND action='build_dispatched';")
emit("build.dispatch.audit", n_disp == "1", f"rows={n_disp}")

# 3) build_completed refuses without brief.
pid_c, uuid_c = _mk("no-brief")
fake_art = {
    "directive_id": "dir_smoke", "project_id": uuid_c, "phase": "build_in_progress",
    "role": "engineer", "pipeline_version": "1.0.0",
    "rationale": "smoke", "status": "draft",
    "cost": {"tokens_input": 0, "tokens_output": 0, "model": "smoke",
             "cost_usd": "0", "tier": "low"},
    "runtime": {"started_at": "2026-05-16T00:00:00+00:00",
                "completed_at": "2026-05-16T00:00:00+00:00",
                "duration_seconds": 0},
    "metadata": {"created_by": "smoke"},
}
r = call("build_completed", {"project_id": str(pid_c), "actor": "smoke-build",
                             "artifact": fake_art})
emit("build.completed.no_brief",
     r["status"] == "error" and (r.get("error") or {}).get("code") == "no_build_brief",
     json.dumps(r)[:200])

# 4) build_completed refuses on project_id mismatch.
bad_art = dict(fake_art)
bad_art["project_id"] = "00000000-0000-0000-0000-000000000000"
r = call("build_completed", {"project_id": str(pid_b), "actor": "smoke-build",
                             "artifact": bad_art})
emit("build.completed.project_id_mismatch",
     r["status"] == "error" and (r.get("error") or {}).get("code") == "project_id_mismatch",
     json.dumps(r)[:200])

# 5) build_completed succeeds with a valid artifact.
good_art = dict(fake_art)
good_art["project_id"] = uuid_b
good_art["directive_id"] = "dir_smoke_b"
r = call("build_completed", {"project_id": str(pid_b), "actor": "smoke-build",
                             "artifact": good_art})
emit("build.completed.ok",
     r["status"] == "ok" and r["data"]["ready_for_verify"] is True,
     json.dumps(r)[:200])
# Verify the artifact landed.
land_uuid = _q(f"SELECT metadata->'build_artifact'->>'directive_id' FROM spine_lifecycle.project "
               f"WHERE id={pid_b};")
emit("build.completed.artifact_in_db", land_uuid == "dir_smoke_b", f"db={land_uuid}")
# Audit row fired.
n_recv = _q(f"SELECT count(*) FROM spine_audit.audit_event "
            f"WHERE project_id={pid_b} AND action='build_completed_received';")
emit("build.completed.audit", n_recv == "1", f"rows={n_recv}")

# 6) build_history grows on second ingest.
good_art2 = dict(good_art); good_art2["directive_id"] = "dir_smoke_b2"
r = call("build_completed", {"project_id": str(pid_b), "actor": "smoke-build",
                             "artifact": good_art2})
emit("build.completed.ok_second",
     r["status"] == "ok", json.dumps(r)[:200])
hlen = _q(f"SELECT jsonb_array_length(metadata->'build_history') FROM spine_lifecycle.project "
          f"WHERE id={pid_b};")
emit("build.completed.history_grows", hlen == "2", f"history_length={hlen}")

# 7) Bug 3 regression: build_dispatch must accept project_uuid.
r = call("build_dispatch", {"project_id": uuid_b, "pipeline_version": "1.0.0",
                            "actor": "smoke-build"})
emit("build.bug3_dispatch_by_uuid",
     r["status"] == "ok" and r["data"]["engineering_goals_count"] > 0,
     json.dumps(r)[:200])
# Hand the test below the project id via stdout for the bash wrapper to read.
print(f"BUG4_PID|{pid_b}")
PY
  out="$(SPINE_DB_URL="$SPINE_DB_URL" SMOKE_NAME="$SMOKE_NAME_PREFIX-build" \
         python3 "$script" 2>&1 || true)"
  rm -f "$script"
  local line cid st msg b4_pid=""
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if [[ "$line" == BUG4_PID\|* ]]; then
      b4_pid="${line#BUG4_PID|}"
    elif [[ "$line" == *"|"*"|"* ]]; then
      cid="${line%%|*}"; line="${line#*|}"; st="${line%%|*}"; msg="${line#*|}"
      _emit "$st" "$cid" "$msg"
    elif [[ $VERBOSE -eq 1 ]]; then _info build.trace "$line"; fi
  done <<< "$out"

  _bug4_env_fallback_regression "$b4_pid"
  _bug5_real_cli_regression
}

# Bug 4 regression: build_dispatcher composes its own SPINE_DB_URL from
# db/.env when nothing is exported. We spawn a clean python3 with no
# Spine env vars, call dispatch_build, and check it ran against postgres.
_bug4_env_fallback_regression() {
  local b4_pid="$1"
  if [[ -z "$b4_pid" ]]; then
    _skip build.bug4_db_url_fallback "no fixture project id from phase 10"
    return 0
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    _skip build.bug4_db_url_fallback "python3 missing"; return 0
  fi
  local probe; probe="$(mktemp "${TMPDIR:-/tmp}/spine-bug4-probe-XXXX.py")"
  cat >"$probe" <<'PYBUG4'
import json, os, sys
sys.path.insert(0, os.environ["SPINE_HOME"])
from build.runtime.build_dispatcher import dispatch_build, _db_url
url = _db_url()
r = dispatch_build(int(os.environ["BUG4_PID"]), actor="smoke-bug4")
print(json.dumps({
    "url_ok": url.startswith("postgresql://"),
    "project_id": r.project_id,
    "engineering_goals_count": r.engineering_goals_count,
}))
PYBUG4
  # Build a clean env: PATH/HOME only — no SPINE_DB_URL, no POSTGRES_*.
  # Sets SPINE_HOME so the probe can import build.runtime.*.
  local out_b4 rc_b4
  out_b4="$(env -i \
      PATH="$PATH" HOME="$HOME" \
      SPINE_HOME="$REPO_ROOT" BUG4_PID="$b4_pid" \
      python3 "$probe" 2>&1)"
  rc_b4=$?
  rm -f "$probe"
  if (( rc_b4 != 0 )); then
    _fail build.bug4_db_url_fallback "probe rc=$rc_b4 out=${out_b4:0:300}"
    return 0
  fi
  # Parse the JSON line and assert all three flags.
  local last_line; last_line="$(printf '%s\n' "$out_b4" | tail -1)"
  if [[ "$last_line" == *'"url_ok": true'* && "$last_line" == *'"engineering_goals_count": '* ]]; then
    _pass build.bug4_db_url_fallback "no env, dispatcher fell back to db/.env: $last_line"
  else
    _fail build.bug4_db_url_fallback "unexpected probe output: $last_line"
  fi
}

# Bug 5 regression: real shell invocation of the spine CLI build report
# subcommand. Failure mode: CLI dies at flag-parse with required-flag
# message before reaching the MCP layer.
_bug5_real_cli_regression() {
  local spine_bin="$REPO_ROOT/orchestrator/bin/spine"
  if [[ ! -x "$spine_bin" ]]; then
    _skip build.bug5_cli_artifact_flag "spine binary not executable"
    return 0
  fi
  local b5_name="${SMOKE_NAME_PREFIX}-build-with-prd" b5_pid b5_uuid
  b5_pid="$(_psql -c "SELECT id FROM spine_lifecycle.project WHERE name='${b5_name}' AND status='active' LIMIT 1;" 2>/dev/null | tr -d ' \r')"
  if [[ -z "$b5_pid" ]]; then
    _skip build.bug5_cli_artifact_flag "no fixture project from phase 10"
    return 0
  fi
  b5_uuid="$(_psql -c "SELECT project_uuid FROM spine_lifecycle.project WHERE id=$b5_pid;" 2>/dev/null | tr -d ' \r')"
  local b5_art; b5_art="$(mktemp "${TMPDIR:-/tmp}/spine-bug5-artifact-XXXX.json")"
  # Build the artifact via python — keeps bash 3.2 parser away from JSON.
  python3 - "$b5_uuid" "$b5_art" <<'PYBUG5'
import json, sys
uuid, path = sys.argv[1], sys.argv[2]
art = {
    "directive_id": "bug5_dir",
    "project_id": uuid,
    "phase": "build_in_progress",
    "role": "engineer",
    "pipeline_version": "1.0.0",
    "rationale": "bug 5 regression",
    "status": "draft",
    "cost": {"tokens_input": 0, "tokens_output": 0, "model": "smoke",
             "cost_usd": "0", "tier": "low"},
    "runtime": {"started_at": "2026-05-17T00:00:00+00:00",
                "completed_at": "2026-05-17T00:00:00+00:00",
                "duration_seconds": 0},
    "metadata": {"created_by": "smoke-bug5"},
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(art, f)
PYBUG5
  local b5_out b5_rc
  b5_out="$(bash "$spine_bin" build report "$b5_pid" --artifact "$b5_art" --actor smoke-bug5 2>&1)" || true
  b5_rc=$?
  rm -f "$b5_art" 2>/dev/null || true
  # Pass criterion: the CLI must NOT die at flag-parse. Either it
  # proceeds to the MCP and returns status=ok, OR returns a structured
  # error from a later layer — both prove --artifact was read.
  if [[ "$b5_out" == *"--artifact"*"required"* ]]; then
    _fail build.bug5_cli_artifact_flag "flag-parse still broken: ${b5_out:0:300}"
  elif [[ "$b5_out" == *status*ok* ]]; then
    _pass build.bug5_cli_artifact_flag "CLI proceeded past flag-parse (rc=$b5_rc)"
  else
    _pass build.bug5_cli_artifact_flag "CLI parsed --artifact OK (rc=$b5_rc, no flag-parse error)"
  fi
}

# ─── phase 11: TRON subsystem (verify/) ──────────────────────────────
# Asserts the TRON subtree is wired into Spine well enough that:
#   1. tron.agents.manager.AuditManager is importable (PYTHONPATH includes
#      verify/ so TRON's absolute tron.* imports resolve)
#   2. AuditManager() instantiates with empty secrets (constructor only,
#      no LLM call made)
#   3. Bandit (Layer-1 deterministic scanner) is callable via subprocess
#      and emits valid JSON on a trivial input — no LLM dollars burned
#   4. TRON's postgres (spine_tron_postgres on 127.0.0.1:33010 per
#      verify/.env + verify/docker-compose.override.yml) is reachable
#      and alembic is at head (8 migrations)
# All four pass without any LLM API keys. See verify/SUBSYSTEM_BOUNDARY.md.
phase11_tron() {
  _phase_banner 11 "TRON subsystem (verify/)"
  if [[ ! -d "$REPO_ROOT/verify/tron" ]]; then
    _fail tron.layout "verify/tron missing - subtree not present"; return 0
  fi
  # Prefer project venv (where TRON deps live: sqlalchemy, temporalio,
  # bandit, psycopg2, etc.). Falls back to system python3 — which is
  # expected to lack the deps and produce a clean FAIL on import. The
  # smoke-test_README documents the install path.
  local py=""
  if [[ -x "$REPO_ROOT/.venv/bin/python3" ]]; then py="$REPO_ROOT/.venv/bin/python3"
  elif command -v python3 >/dev/null 2>&1; then    py="$(command -v python3)"
  else _skip tron.runtime "no python3 available"; return 0; fi
  # PYTHONPATH = repo root (for shared/plan/build) + verify/ (so TRON's
  # tron.* absolute imports resolve from verify/tron/...).
  export PYTHONPATH="$REPO_ROOT:$REPO_ROOT/verify${PYTHONPATH:+:$PYTHONPATH}"

  local out
  out="$("$py" "$REPO_ROOT/tools/_smoke_phase11_tron.py" 2>&1 || true)"
  local line cid st msg
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if [[ "$line" == *"|"*"|"* ]]; then
      cid="${line%%|*}"; line="${line#*|}"; st="${line%%|*}"; msg="${line#*|}"
      _emit "$st" "$cid" "$msg"
    elif [[ $VERBOSE -eq 1 ]]; then _info tron.trace "$line"; fi
  done <<< "$out"
}

# ─── phase 12: bootstrap artifacts (don't actually run bootstrap) ────
# Asserts the files + targets that `make bootstrap` depends on are in
# place. We deliberately do NOT call `make bootstrap` from inside smoke
# — that would be circular, since bootstrap calls smoke as its
# acceptance gate. Cheap structural checks only.
phase12_bootstrap() {
  _phase_banner 12 "bootstrap artifacts"
  [[ -f "$REPO_ROOT/Makefile" ]] && grep -qE '^bootstrap:' "$REPO_ROOT/Makefile" \
    && _pass boot.make_target "top-level Makefile has 'bootstrap' target" \
    || _fail boot.make_target "Makefile missing 'bootstrap' target"
  [[ -f "$REPO_ROOT/Makefile" ]] && grep -qE '^nuke:' "$REPO_ROOT/Makefile" \
    && _pass boot.nuke_target "top-level Makefile has 'nuke' target" \
    || _fail boot.nuke_target "Makefile missing 'nuke' target"
  [[ -f "$REPO_ROOT/requirements.txt" ]] \
    && _pass boot.requirements "requirements.txt present at repo root" \
    || _fail boot.requirements "requirements.txt missing — bootstrap can't install python deps"
  [[ -f "$REPO_ROOT/tools/bootstrap.sh" ]] \
    && _pass boot.script "tools/bootstrap.sh present" \
    || _fail boot.script "tools/bootstrap.sh missing"
  [[ -f "$REPO_ROOT/tools/spine-flyway-sync.sh" ]] \
    && _pass boot.flyway_sync "tools/spine-flyway-sync.sh present (F2 fix helper)" \
    || _fail boot.flyway_sync "tools/spine-flyway-sync.sh missing"
  # `make help` works (cheap structural check; no expensive subtargets fired).
  if ( cd "$REPO_ROOT" && make -n help >/dev/null 2>&1 ); then
    _pass boot.make_help "'make help' parses without error"
  else
    _fail boot.make_help "'make help' fails — Makefile syntax broken"
  fi
}

# ─── cleanup + formatters ────────────────────────────────────────────
cleanup_fixtures() {
  [[ $CLEANUP -eq 1 ]] || { _info cleanup.skip "--no-cleanup: fixtures left in DB"; return 0; }
  _load_db_env
  _db_alive && _psql -c "DELETE FROM spine_lifecycle.project WHERE name LIKE '${SMOKE_NAME_PREFIX}%';" >/dev/null 2>&1 || true
}
emit_text_summary() {
  printf '\n%s\n' "$(_color bold '── Summary')"
  printf '  PASS=%d  FAIL=%d  WARN=%d  SKIP=%d  INFO=%d  (total=%d)\n' \
    "$COUNT_PASS" "$COUNT_FAIL" "$COUNT_WARN" "$COUNT_SKIP" "$COUNT_INFO" "${#RESULT_ORDER[@]}"
  if (( COUNT_FAIL > 0 )); then
    printf '\n%s\n' "$(_color red 'Failed checks:')"
    local id e st msg
    for id in "${RESULT_ORDER[@]}"; do
      e="$(_lookup "$id")"; st="${e%%|*}"; msg="${e#*|}"
      [[ "$st" == FAIL ]] && printf '  - %s  %s\n' "$id" "$msg"
    done
  fi
}
emit_json() {
  local id e st msg first=1
  printf '{"summary":{"pass":%d,"fail":%d,"warn":%d,"skip":%d,"info":%d,"total":%d},"results":[' \
    "$COUNT_PASS" "$COUNT_FAIL" "$COUNT_WARN" "$COUNT_SKIP" "$COUNT_INFO" "${#RESULT_ORDER[@]}"
  for id in "${RESULT_ORDER[@]}"; do
    e="$(_lookup "$id")"; st="${e%%|*}"; msg="${e#*|}"
    msg="${msg//\\/\\\\}"; msg="${msg//\"/\\\"}"
    (( first )) && first=0 || printf ','
    printf '{"id":"%s","status":"%s","message":"%s"}' "$id" "$st" "$msg"
  done
  printf ']}\n'
}
emit_junit() {
  local id e st msg name
  printf '<?xml version="1.0" encoding="UTF-8"?>\n'
  printf '<testsuite name="spine.smoke-test" tests="%d" failures="%d" skipped="%d">\n' \
    "${#RESULT_ORDER[@]}" "$COUNT_FAIL" "$((COUNT_SKIP+COUNT_INFO))"
  for id in "${RESULT_ORDER[@]}"; do
    e="$(_lookup "$id")"; st="${e%%|*}"; msg="${e#*|}"
    name="${id//&/&amp;}"; name="${name//</&lt;}"; name="${name//>/&gt;}"
    msg="${msg//&/&amp;}"; msg="${msg//</&lt;}"; msg="${msg//>/&gt;}"; msg="${msg//\"/&quot;}"
    printf '  <testcase classname="spine.smoke" name="%s">' "$name"
    case "$st" in FAIL) printf '<failure message="%s"/>' "$msg";;
                  SKIP|INFO|WARN) printf '<skipped message="%s"/>' "$msg";; esac
    printf '</testcase>\n'
  done
  printf '</testsuite>\n'
}

# ─── CLI ─────────────────────────────────────────────────────────────
usage() {
  cat <<'USAGE'
Usage: tools/smoke-test.sh [--phase N|all] [--format text|json|junit]
                           [--verbose] [--no-cleanup] [--ci] [--no-color]
Phases: 1 env, 2 db, 3 python, 4 pydantic, 5 lifecycle, 6 kg, 7 optional, 8 mcp-tools, 9 intake, 10 build, 11 tron, 12 bootstrap.
Exit:   0=PASS  1=FAIL  2=env-problem  3=harness-error  64=unknown-flag.
USAGE
}
parse_args() {
  while (( $# )); do
    case "$1" in
      --phase) PHASE="${2:-all}"; shift 2;;
      --format) FORMAT="${2:-text}"; shift 2;;
      --verbose) VERBOSE=1; shift;;
      --no-cleanup) CLEANUP=0; shift;;
      --ci) CI_MODE=1; FORMAT=junit; USE_COLOR=0; shift;;
      --no-color) USE_COLOR=0; shift;;
      -h|--help) usage; exit 0;;
      *) printf 'unknown flag: %s\n' "$1" >&2; usage >&2; exit 64;;
    esac
  done
  case "$FORMAT" in text|json|junit) ;; *)
    printf 'invalid --format %s\n' "$FORMAT" >&2; exit 64;; esac
}
run_phases() {
  case "$PHASE" in
    all) phase1_env; phase2_db; phase3_python; phase4_pydantic; phase5_lifecycle; phase6_kg; phase7_optional; phase8_mcp_tools; phase9_intake; phase10_build; phase11_tron; phase12_bootstrap;;
    1) phase1_env;; 2) phase2_db;; 3) phase3_python;; 4) phase4_pydantic;;
    5) phase5_lifecycle;; 6) phase6_kg;; 7) phase7_optional;; 8) phase8_mcp_tools;;
    9) phase9_intake;; 10) phase10_build;; 11) phase11_tron;; 12) phase12_bootstrap;;
    *) printf 'invalid --phase %s\n' "$PHASE" >&2; exit 64;;
  esac
}
main() {
  parse_args "$@"
  _log INFO "starting phase=$PHASE format=$FORMAT ci=$CI_MODE"
  # Let each check decide pass/fail (don't let set -e kill mid-phase).
  set +e; run_phases; cleanup_fixtures; set -e
  case "$FORMAT" in text) emit_text_summary;; json) emit_json;; junit) emit_junit;; esac
  # Promote env failures to exit 2 so CI can distinguish setup from regression.
  local env_problem=0 id e st
  for id in env.docker env.python env.psql env.postgres_container db.connect; do
    e="$(_lookup "$id" 2>/dev/null || true)"; st="${e%%|*}"
    [[ "$st" == FAIL ]] && env_problem=1
  done
  if (( COUNT_FAIL > 0 )); then (( env_problem )) && exit 2 || exit 1; fi
  exit 0
}
main "$@"
