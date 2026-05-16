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
declare -a RESULT_ORDER=()
declare -A RESULTS=()
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
  RESULT_ORDER+=("$id"); RESULTS[$id]="$status|$msg"
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

  local schemas="spine_audit spine_calibration spine_eval spine_kg spine_lifecycle spine_memory spine_recording spine_verify_audit spine_verify_threat_intel"
  local present sch
  present="$(_psql -c "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'spine_%' ORDER BY 1;" 2>/dev/null || true)"
  for sch in $schemas; do
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
      e="${RESULTS[$id]}"; st="${e%%|*}"; msg="${e#*|}"
      [[ "$st" == FAIL ]] && printf '  - %s  %s\n' "$id" "$msg"
    done
  fi
}
emit_json() {
  local id e st msg first=1
  printf '{"summary":{"pass":%d,"fail":%d,"warn":%d,"skip":%d,"info":%d,"total":%d},"results":[' \
    "$COUNT_PASS" "$COUNT_FAIL" "$COUNT_WARN" "$COUNT_SKIP" "$COUNT_INFO" "${#RESULT_ORDER[@]}"
  for id in "${RESULT_ORDER[@]}"; do
    e="${RESULTS[$id]}"; st="${e%%|*}"; msg="${e#*|}"
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
    e="${RESULTS[$id]}"; st="${e%%|*}"; msg="${e#*|}"
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
Phases: 1 env, 2 db, 3 python, 4 pydantic, 5 lifecycle, 6 kg, 7 optional.
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
    all) phase1_env; phase2_db; phase3_python; phase4_pydantic; phase5_lifecycle; phase6_kg; phase7_optional;;
    1) phase1_env;; 2) phase2_db;; 3) phase3_python;; 4) phase4_pydantic;;
    5) phase5_lifecycle;; 6) phase6_kg;; 7) phase7_optional;;
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
    e="${RESULTS[$id]:-}"; st="${e%%|*}"
    [[ "$st" == FAIL ]] && env_problem=1
  done
  if (( COUNT_FAIL > 0 )); then (( env_problem )) && exit 2 || exit 1; fi
  exit 0
}
main "$@"
