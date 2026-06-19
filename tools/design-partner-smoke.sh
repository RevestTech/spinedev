#!/usr/bin/env bash
# tools/design-partner-smoke.sh — SPINE-020 local laptop onboarding smoke.
#
# Exercises the design-partner path that skips BYOC:
#   hub-up status → /healthz → decision queue → project create (if Hub up).
#
# Does NOT start Docker. Run `bash tools/hub-up.sh` first.
#
# Exit codes:
#   0  all executed checks passed (skips are OK)
#   1  one or more checks failed
#   2  Hub not running — documented skip only (still exit 0 unless --strict)

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BASE="${BASE:-http://localhost:8090}"
STRICT=0
PASS=0
FAIL=0
SKIP=0

log()  { printf '[design-partner-smoke] %s\n' "$*" >&2; }
pass() { PASS=$((PASS + 1)); log "PASS: $*"; }
fail() { FAIL=$((FAIL + 1)); log "FAIL: $*"; }
skip() { SKIP=$((SKIP + 1)); log "SKIP: $*"; }

usage() {
  cat <<EOF
tools/design-partner-smoke.sh — local design partner onboarding smoke (SPINE-020)

USAGE
  bash tools/design-partner-smoke.sh [options]

OPTIONS
  --base=URL          Hub base URL (default: http://localhost:8090)
  --strict            Exit 2 when Hub is not running (default: skip API checks, exit 0)
  -h, --help          Show this message

PREREQUISITES
  bash tools/hub-up.sh          # bring Hub up (not invoked by this script)
  ./hub/wizard/init.sh          # Day-0 wizard (optional for dev InMemory mode)

EXAMPLES
  bash tools/hub-up.sh
  bash tools/design-partner-smoke.sh
  BASE=http://127.0.0.1:8090 bash tools/design-partner-smoke.sh --strict
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base=*) BASE="${1#*=}"; shift ;;
    --strict) STRICT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) log "unknown flag: $1"; usage; exit 64 ;;
  esac
done

BASE="${BASE%/}"

# --- 1. hub-up status (informational) ---------------------------------------
log "Step 1/4 — hub container status (tools/hub-up.sh --status)"
if [[ -x "${REPO_ROOT}/tools/hub-up.sh" ]]; then
  if status_out="$(bash "${REPO_ROOT}/tools/hub-up.sh" --status 2>&1)"; then
    if [[ -n "${status_out}" ]]; then
      pass "hub-up --status: ${status_out//$'\n'/; }"
    else
      skip "hub-up --status: no spine-hub container (Hub may be down)"
    fi
  else
    skip "hub-up --status: command failed (docker unavailable?)"
  fi
else
  skip "tools/hub-up.sh not found"
fi

# --- 2. healthz -------------------------------------------------------------
log "Step 2/4 — GET ${BASE}/healthz"
hub_up=0
health_body=""
if health_body="$(curl -fsS --max-time 10 "${BASE}/healthz" 2>/dev/null)"; then
  hub_up=1
  if printf '%s' "${health_body}" | python3 -c "import json,sys; b=json.load(sys.stdin); assert b.get('mcp') is True" 2>/dev/null; then
    pass "healthz returned 200 with mcp=true"
  else
    pass "healthz returned 200 (body: ${health_body:0:120})"
  fi
else
  skip "Hub not reachable at ${BASE}/healthz — start with: bash tools/hub-up.sh"
  if (( STRICT == 1 )); then
    log "SUMMARY: pass=${PASS} fail=${FAIL} skip=${SKIP}"
    exit 2
  fi
  log "SUMMARY: pass=${PASS} fail=${FAIL} skip=${SKIP} (Hub down — API steps skipped)"
  log "See docs/DESIGN_PARTNER_ONBOARDING.md for full BYOC onboarding runbook."
  exit 0
fi

# --- 3. decision queue -------------------------------------------------------
log "Step 3/4 — GET ${BASE}/api/v2/decisions?status=pending"
decisions_json=""
if decisions_json="$(curl -fsS --max-time 15 "${BASE}/api/v2/decisions?status=pending" 2>/dev/null)"; then
  pending_count="$(printf '%s' "${decisions_json}" | python3 -c "
import json, sys
data = json.load(sys.stdin)
items = data.get('items') or data.get('data') or []
print(len(items) if isinstance(items, list) else 0)
" 2>/dev/null || echo "?")"
  pass "decision queue reachable (pending=${pending_count})"
else
  fail "decision queue request failed"
fi

# --- 4. project create -------------------------------------------------------
log "Step 4/4 — POST ${BASE}/api/v2/projects"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
project_name="Design Partner Smoke ${stamp}"
create_body="$(cat <<EOF
{
  "name": "${project_name}",
  "project_type": "feature",
  "greenfield": true,
  "description": "SPINE-020 design-partner-smoke.sh onboarding check"
}
EOF
)"

create_resp=""
if create_resp="$(curl -fsS --max-time 30 -X POST "${BASE}/api/v2/projects" \
  -H 'Content-Type: application/json' \
  -d "${create_body}" 2>/dev/null)"; then
  project_uuid="$(printf '%s' "${create_resp}" | python3 -c "
import json, sys
r = json.load(sys.stdin)
data = r.get('data') or r
for k in ('project_uuid', 'project_id'):
    v = data.get(k) if isinstance(data, dict) else None
    if v:
        print(v)
        break
else:
    v = r.get('project_uuid') or r.get('project_id')
    if v:
        print(v)
" 2>/dev/null || true)"
  if [[ -n "${project_uuid:-}" ]]; then
    pass "project create ok project_uuid=${project_uuid}"
    # Confirm intake_briefing or any pending card for this project
    if [[ -n "${decisions_json}" ]]; then
      has_card="$(PROJECT_UUID="${project_uuid}" DECISIONS="${decisions_json}" python3 -c "
import json, os
items = json.loads(os.environ['DECISIONS']).get('items') or []
pu = os.environ['PROJECT_UUID']
found = any(
    (c.get('project_id') == pu or (c.get('metadata') or {}).get('project_uuid') == pu)
    for c in items
)
print('yes' if found else 'no')
" 2>/dev/null || echo "no")"
      if [[ "${has_card}" == "yes" ]]; then
        pass "pending decision card exists for new project"
      else
        skip "no pending project-scoped card yet (queue may update async)"
      fi
    fi
  else
    fail "project create response missing project_uuid: ${create_resp:0:200}"
  fi
else
  fail "POST /api/v2/projects failed"
fi

log "SUMMARY: pass=${PASS} fail=${FAIL} skip=${SKIP}"
if (( FAIL > 0 )); then
  exit 1
fi
exit 0
