#!/usr/bin/env bash
# router_cli.sh — Spine cost-aware tier router CLI.
#
# Thin bash wrapper around shared/cost/router.py. Daemons call this BEFORE
# dispatching an LLM directive to decide which model to use (or to block on
# budget). Implements STORY-1.5.3; reads V16__unified_cost_ledger.sql.
# Style mirrors orchestrator/lib/router.sh + shared/cost/budget_rollup.sh.
#
# CLI:
#   router_cli.sh route       --project N --phase P --role R --tier T
#                             [--est-in N] [--est-out N] [--actor U]
#                             [--override MODEL] [--justification TEXT] [--granted-by U]
#   router_cli.sh team-route  --project N --phase P --role R --directive TEXT
#                             [--est-in N] [--est-out N] [--actor U]
#                             [--files N] [--loc N] [--artifact TYPE]
#                             [--retries N] [--override-tier TIER]
#   router_cli.sh budget      [--project N] [--user U] [--org O]
#   router_cli.sh list-models [--tier T]
#   router_cli.sh check       --project N --phase P --tier T [--est-in N] [--est-out N]
#
# Exit: 0 ok, 2 would-exceed/override-blocked, 3 error, 64 unknown subcommand.

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=../../orchestrator/lib/_env_loader.sh
. "$REPO_ROOT/orchestrator/lib/_env_loader.sh"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

_log() { printf '%s router_cli.sh %s %s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${*:2}" >&2; }
_err() { printf '{"ok":false,"code":"%s","message":"%s"}\n' "$1" "${2//\"/\\\"}"
         _log ERROR "$1: $2"; exit "${3:-3}"; }

# Run python with heredoc on stdin; propagate exit codes 0/2 (router intent)
# verbatim; remap any other non-zero (traceback, import error) to JSON+exit 3.
_py() {
  local rc=0
  python3 - "$@" || rc=$?
  case "$rc" in
    0|2) return "$rc" ;;
    *) _err py_error "router.py invocation failed (rc=$rc)" ;;
  esac
}

cmd_route() {
  local project="" phase="" role="" tier="" estin=0 estout=0
  local actor="${USER:-unknown}" override="" justif="" granted=""
  while [[ $# -gt 0 ]]; do case "$1" in
    --project)        project="$2";  shift 2 ;;
    --phase)          phase="$2";    shift 2 ;;
    --role)           role="$2";     shift 2 ;;
    --tier)           tier="$2";     shift 2 ;;
    --est-in)         estin="$2";    shift 2 ;;
    --est-out)        estout="$2";   shift 2 ;;
    --actor)          actor="$2";    shift 2 ;;
    --override)       override="$2"; shift 2 ;;
    --justification)  justif="$2";   shift 2 ;;
    --granted-by)     granted="$2";  shift 2 ;;
    *) _err invalid_input "unknown arg: $1" ;;
  esac; done
  for v in project phase role tier; do
    [[ -z "${!v}" ]] && _err invalid_input "--${v} required"
  done
  PROJECT_ID="$project" PHASE="$phase" ROLE="$role" TIER="$tier" \
    EST_IN="$estin" EST_OUT="$estout" ACTOR="$actor" \
    OVERRIDE="$override" JUSTIFICATION="$justif" GRANTED_BY="$granted" \
    _py <<'PY'
import json, os, sys
from shared.cost.router import RouteRequest, ModelOverride, route, _decision_to_dict
ov = ModelOverride(model_id=os.environ["OVERRIDE"],
    justification=os.environ.get("JUSTIFICATION") or "(no justification)",
    granted_by=os.environ.get("GRANTED_BY") or os.environ.get("ACTOR","unknown"),
) if os.environ.get("OVERRIDE") else None
d = route(RouteRequest(
    project_id=int(os.environ["PROJECT_ID"]), phase=os.environ["PHASE"],
    role=os.environ["ROLE"], intended_tier=os.environ["TIER"],
    estimated_input_tokens=int(os.environ["EST_IN"] or 0),
    estimated_output_tokens=int(os.environ["EST_OUT"] or 0),
    actor=os.environ["ACTOR"], override=ov))
print(json.dumps(_decision_to_dict(d)))
sys.exit(2 if d.blocked else 0)
PY
}

cmd_budget() {
  local project="" user="${USER:-unknown}" org=""
  while [[ $# -gt 0 ]]; do case "$1" in
    --project) project="$2"; shift 2 ;;
    --user)    user="$2";    shift 2 ;;
    --org)     org="$2";     shift 2 ;;
    *) _err invalid_input "unknown arg: $1" ;;
  esac; done
  PROJECT_ID="${project:-0}" USER_ID="$user" ORG_ID="${org:-}" _py <<'PY'
import os
from shared.cost.router import get_budget_status
print(get_budget_status(int(os.environ.get("PROJECT_ID") or 0),
    os.environ["USER_ID"], os.environ.get("ORG_ID") or None).model_dump_json())
PY
}

cmd_list_models() {
  local tier=""
  while [[ $# -gt 0 ]]; do case "$1" in
    --tier) tier="$2"; shift 2 ;;
    *) _err invalid_input "unknown arg: $1" ;;
  esac; done
  TIER="$tier" _py <<'PY'
import json, os
from shared.cost.router import list_allowed_models, _load_active_bundle
ms = list_allowed_models(_load_active_bundle(), tier=(os.environ.get("TIER") or None))
print(json.dumps([json.loads(m.model_dump_json()) for m in ms]))
PY
}

cmd_check() {
  # Reuses cmd_route's arg parsing + budget check; suppresses JSON, just sets exit.
  cmd_route --role check "$@" >/dev/null
}

cmd_team_route() {
  # STORY-3.3.1 + 3.3.2 — auto-route by (role, task complexity).
  local project="" phase="" role="" directive="" estin=0 estout=0
  local actor="${USER:-unknown}" files=0 loc=0 artifact="" retries=0
  local override_tier=""
  while [[ $# -gt 0 ]]; do case "$1" in
    --project)        project="$2";       shift 2 ;;
    --phase)          phase="$2";         shift 2 ;;
    --role)           role="$2";          shift 2 ;;
    --directive)      directive="$2";     shift 2 ;;
    --est-in)         estin="$2";         shift 2 ;;
    --est-out)        estout="$2";        shift 2 ;;
    --actor)          actor="$2";         shift 2 ;;
    --files)          files="$2";         shift 2 ;;
    --loc)            loc="$2";           shift 2 ;;
    --artifact)       artifact="$2";      shift 2 ;;
    --retries)        retries="$2";       shift 2 ;;
    --override-tier)  override_tier="$2"; shift 2 ;;
    *) _err invalid_input "unknown arg: $1" ;;
  esac; done
  for v in project phase role directive; do
    [[ -z "${!v}" ]] && _err invalid_input "--${v} required"
  done
  PROJECT_ID="$project" PHASE="$phase" ROLE="$role" DIRECTIVE="$directive" \
    EST_IN="$estin" EST_OUT="$estout" ACTOR="$actor" \
    FILES="$files" LOC="$loc" ARTIFACT="$artifact" RETRIES="$retries" \
    OVERRIDE_TIER="$override_tier" _py <<'PY'
import json, os, sys
from shared.cost.team_router import TeamRouteRequest, team_route
req = TeamRouteRequest(
    role=os.environ["ROLE"], phase=os.environ["PHASE"],
    directive_text=os.environ["DIRECTIVE"],
    project_id=int(os.environ.get("PROJECT_ID") or 0),
    actor=os.environ["ACTOR"],
    estimated_input_tokens=int(os.environ.get("EST_IN") or 0),
    estimated_output_tokens=int(os.environ.get("EST_OUT") or 0),
    file_count_touched=int(os.environ.get("FILES") or 0),
    estimated_loc=int(os.environ.get("LOC") or 0),
    artifact_type=(os.environ.get("ARTIFACT") or None),
    prior_attempts=int(os.environ.get("RETRIES") or 0),
    user_override_tier=(os.environ.get("OVERRIDE_TIER") or None),
)
d = team_route(req)
print(d.model_dump_json())
sys.exit(2 if d.blocked else 0)
PY
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    route)        cmd_route        "$@" ;;
    team-route)   cmd_team_route   "$@" ;;
    budget)       cmd_budget       "$@" ;;
    list-models)  cmd_list_models  "$@" ;;
    check)        cmd_check        "$@" ;;
    -h|--help|"") sed -n '2,26p' "${BASH_SOURCE[0]}" >&2; exit 0 ;;
    *) _err unknown_command "no such subcommand: $cmd" 64 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
