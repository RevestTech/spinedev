#!/usr/bin/env bash
# verify-project-workspace.sh — curl the Hub APIs a project workspace needs on open.
# Loops until all endpoints respond OK (or max attempts). No browser required.
#
# Usage:
#   bash tools/verify-project-workspace.sh [project_uuid]
#   PROJECT_ID=... HUB_BASE=http://localhost:8090 bash tools/verify-project-workspace.sh
#
# Default project: Booger (c94d5f8c-5c7a-40a1-9da9-e25fcca63c88) when present.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HUB_BASE="${HUB_BASE:-http://localhost:8090}"
PROJECT_ID="${1:-${PROJECT_ID:-}}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-60}"
SLEEP_SEC="${SLEEP_SEC:-2}"
MAX_TIME="${MAX_TIME:-5}"

if [[ -z "$PROJECT_ID" ]]; then
  PROJECT_ID="$(curl -sf "${HUB_BASE}/api/v2/projects?limit=200" \
    | python3 -c "
import json, sys
items = json.load(sys.stdin).get('items', [])
for it in items:
    p = json.loads(it) if isinstance(it, str) else it
    if (p.get('name') or '').lower() == 'booger':
        print(p.get('project_id') or p.get('project_uuid') or '')
        break
else:
    if items:
        p = json.loads(items[0]) if isinstance(items[0], str) else items[0]
        print(p.get('project_id') or p.get('project_uuid') or '')
" 2>/dev/null || true)"
fi

if [[ -z "$PROJECT_ID" ]]; then
  echo "verify-project-workspace: no project id (pass arg or create Booger)" >&2
  exit 1
fi

curl_ok() {
  local label="$1"
  local path="$2"
  local extra="${3:-}"
  local code body
  body="$(mktemp)"
  code="$(curl -sf -o "$body" -w '%{http_code}' --max-time "$MAX_TIME" "${HUB_BASE}${path}" 2>/dev/null || echo "000")"
  if [[ "$code" != "200" ]]; then
    echo "  FAIL $label HTTP $code ${path}"
    rm -f "$body"
    return 1
  fi
  if [[ -n "$extra" ]]; then
    if ! python3 -c "$extra" < "$body" 2>/dev/null; then
      echo "  FAIL $label body check ${path}"
      rm -f "$body"
      return 1
    fi
  fi
  rm -f "$body"
  echo "  OK   $label"
  return 0
}

attempt=0
echo "verify-project-workspace: project=${PROJECT_ID} hub=${HUB_BASE} (max ${MAX_ATTEMPTS} attempts)"

while (( attempt < MAX_ATTEMPTS )); do
  attempt=$((attempt + 1))
  echo "--- attempt ${attempt}/${MAX_ATTEMPTS} ---"
  ok=true
  curl_ok "spa shell" "/spa/" || ok=false
  curl_ok "summary" "/api/v2/projects/${PROJECT_ID}/summary" \
    "import json,sys; d=json.load(sys.stdin); assert d.get('project_id') or d.get('name')" || ok=false
  curl_ok "recovery" "/api/v2/projects/${PROJECT_ID}/recovery" \
    "import json,sys; d=json.load(sys.stdin); assert d.get('ok') is True; assert len(d.get('actions') or []) >= 1" || ok=false
  curl_ok "terminal" "/api/v2/projects/${PROJECT_ID}/activity/terminal?limit=120" \
    "import json,sys; json.load(sys.stdin)" || ok=false
  curl_ok "decisions" "/api/v2/decisions?status=pending&scope=project&include_body=false" \
    "import json,sys; json.load(sys.stdin)" || ok=false
  curl_ok "recovery summary" "/api/v2/projects/recovery/summary?limit=200" \
    "import json,sys; json.load(sys.stdin)" || ok=false

  if [[ "$ok" == true ]]; then
    echo "verify-project-workspace: PASS (all endpoints OK for ${PROJECT_ID})"
    if [[ "${RUN_PLAYWRIGHT:-0}" == "1" ]]; then
      echo "verify-project-workspace: running Playwright booger-workspace e2e…"
      (cd "${REPO_ROOT}/shared/ui/spa" && npx playwright test e2e/booger-workspace.spec.ts --reporter=line)
    fi
    exit 0
  fi
  sleep "$SLEEP_SEC"
done

echo "verify-project-workspace: FAIL after ${MAX_ATTEMPTS} attempts" >&2
exit 1
