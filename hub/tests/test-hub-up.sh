#!/usr/bin/env bash
# Spine v3 — Hub container smoke test (Wave 3 Squad B)
#
# What this does:
#   1. Spin up hub/docker-compose.yml (with a SYNTHETIC .env.local from this
#      script so wizard isn't a hard prerequisite for the smoke).
#   2. Poll http://localhost:${SPINE_HUB_HOST_PORT}/healthz with a 60s deadline.
#   3. GET /api/v2/spec — must return OpenAPI 3.x JSON.
#   4. GET /api/v2/projects — must return 200 (empty list) OR 401 if OIDC
#      middleware (Wave 3 Squad C) is active. Both are acceptable in the
#      smoke; the goal here is "is the surface alive and routed".
#   5. Tear everything down.
#
# Exit codes:
#   0  pass
#   1  generic failure
#   2  docker not available (skip, not fail)
#   3  /healthz did not become OK within 60s
#   4  /api/v2/spec missing or malformed
#   5  /api/v2/projects returned an unacceptable status
#
# Hard constraints from agent brief:
#   - DO NOT actually start docker-compose unless explicitly requested.
#     Default mode is design-validation only (--dry-run is the default).
#     Pass --run to opt in to docker spin-up.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HUB_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${HUB_DIR}/.." && pwd)"
COMPOSE_FILE="${HUB_DIR}/docker-compose.yml"

DRY_RUN=1
HOST_PORT="${SPINE_HUB_HOST_PORT:-8090}"
HEALTH_DEADLINE_SECS=60
ENV_FILE=""

log()  { printf '[hub-smoke] %s\n' "$*" >&2; }
fail() { log "FAIL: $*"; cleanup; exit "${2:-1}"; }
skip() { log "SKIP: $*"; exit 2; }
pass() { log "PASS: $*"; }

usage() {
  cat <<EOF
hub/tests/test-hub-up.sh — Hub container smoke test

Usage:
  test-hub-up.sh [--run] [--host-port=PORT] [--health-deadline=SECS]

Default mode is DRY-RUN (per Wave 3 Squad B scope: do NOT start docker).
Pass --run to actually bring up the compose stack and exercise endpoints.

Options:
  --run                       Actually run docker compose up + curl probes.
  --host-port=PORT            Override host port for /healthz (default 8090).
  --health-deadline=SECS      How long to wait for /healthz=ok (default 60).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run)                  DRY_RUN=0; shift ;;
    --host-port=*)          HOST_PORT="${1#*=}"; shift ;;
    --health-deadline=*)    HEALTH_DEADLINE_SECS="${1#*=}"; shift ;;
    -h|--help)              usage; exit 0 ;;
    *)                      fail "Unknown flag: $1 (try --help)" 1 ;;
  esac
done

cleanup() {
  if (( DRY_RUN == 1 )); then return 0; fi
  log "Cleanup: docker compose down -v"
  docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE:-/dev/null}" down -v >/dev/null 2>&1 || true
  if [[ -n "${ENV_FILE}" && -f "${ENV_FILE}" ]]; then
    rm -f "${ENV_FILE}"
  fi
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Validation pass (always runs — this is what makes the script useful in CI
# without docker).
# ---------------------------------------------------------------------------
log "Validation: file presence + bash syntax + compose schema"

[[ -f "${HUB_DIR}/Dockerfile"            ]] || fail "missing Dockerfile" 1
[[ -f "${HUB_DIR}/docker-compose.yml"    ]] || fail "missing docker-compose.yml" 1
[[ -f "${HUB_DIR}/entrypoint.sh"         ]] || fail "missing entrypoint.sh" 1
[[ -f "${HUB_DIR}/healthcheck.sh"        ]] || fail "missing healthcheck.sh" 1
[[ -f "${HUB_DIR}/__init__.py"           ]] || fail "missing __init__.py" 1
[[ -f "${HUB_DIR}/main.py"               ]] || fail "missing main.py" 1
[[ -f "${HUB_DIR}/wizard/init.sh"        ]] || fail "missing wizard/init.sh" 1
[[ -f "${HUB_DIR}/config/default_bundle.yaml"   ]] || fail "missing config/default_bundle.yaml" 1
[[ -f "${HUB_DIR}/config/free_tier_flags.yaml"  ]] || fail "missing config/free_tier_flags.yaml" 1

bash -n "${HUB_DIR}/entrypoint.sh"       || fail "entrypoint.sh syntax" 1
bash -n "${HUB_DIR}/healthcheck.sh"      || fail "healthcheck.sh syntax" 1
bash -n "${HUB_DIR}/wizard/init.sh"      || fail "wizard/init.sh syntax" 1
bash -n "${SCRIPT_DIR}/test-hub-up.sh"   || fail "test-hub-up.sh self-syntax" 1

python3 -m py_compile "${HUB_DIR}/__init__.py" "${HUB_DIR}/main.py" \
  || fail "hub python package does not compile" 1

python3 -c "
import yaml, sys
for f in [
    '${HUB_DIR}/config/default_bundle.yaml',
    '${HUB_DIR}/config/free_tier_flags.yaml',
]:
    yaml.safe_load(open(f))
print('yaml-ok')
" >/dev/null || fail "yaml configs do not parse" 1

pass "validation pass complete"

if (( DRY_RUN == 1 )); then
  log "Default --dry-run mode: not spinning up docker (per Wave 3 Squad B scope)."
  log "Re-run with --run to exercise the live stack."
  exit 0
fi

# ---------------------------------------------------------------------------
# Live run (opt-in via --run).
# ---------------------------------------------------------------------------
command -v docker  >/dev/null 2>&1 || skip "docker not available"
docker info        >/dev/null 2>&1 || skip "docker daemon not reachable"
command -v curl    >/dev/null 2>&1 || fail "curl required" 1
command -v python3 >/dev/null 2>&1 || fail "python3 required" 1

# Synthetic .env.local — non-secret placeholders so the required-env syntax
# in the compose file passes validation. These are NOT secrets; they are
# trivial dev defaults that the smoke test owns end-to-end (volumes get
# wiped on cleanup).
ENV_FILE="$(mktemp -t hub-smoke-env.XXXXXX)"
cat >"${ENV_FILE}" <<EOF
SPINE_HUB_HOST_PORT=${HOST_PORT}
SPINE_HUB_DEV=1
SPINE_HUB_LOG_LEVEL=info
SPINE_DB_PASSWORD=smoke-test-db-pw
KEYCLOAK_DB_PASSWORD=smoke-test-kc-db-pw
KEYCLOAK_ADMIN_PASSWORD=smoke-test-kc-admin-pw
SPINE_VAULT_ROLE_ID=smoke-test-role-id
SPINE_VAULT_SECRET_ID_WRAPPED=smoke-test-wrapped-secret-id
EOF

log "Spinning up compose stack (this can take a minute on first run)..."
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d \
  || fail "docker compose up failed" 1

# Poll /healthz.
log "Polling http://localhost:${HOST_PORT}/healthz (deadline ${HEALTH_DEADLINE_SECS}s)..."
deadline=$(( SECONDS + HEALTH_DEADLINE_SECS ))
ready=0
while (( SECONDS < deadline )); do
  body="$(curl -fsS -m 3 "http://localhost:${HOST_PORT}/healthz" 2>/dev/null || true)"
  if [[ -n "${body}" ]]; then
    ok="$(printf '%s' "${body}" | python3 -c 'import sys,json
try:
    print(json.load(sys.stdin).get("ok",""))
except Exception:
    print("")' 2>/dev/null || true)"
    if [[ "${ok}" == "True" || "${ok}" == "true" ]]; then
      ready=1
      break
    fi
  fi
  sleep 2
done
(( ready == 1 )) || fail "/healthz did not become ok within ${HEALTH_DEADLINE_SECS}s" 3
pass "/healthz ok"

# GET /api/v2/spec — must be OpenAPI.
log "GET /api/v2/spec"
spec="$(curl -fsS -m 5 "http://localhost:${HOST_PORT}/api/v2/spec")" \
  || fail "/api/v2/spec request failed" 4
spec_ok="$(printf '%s' "${spec}" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    print("yes" if "openapi" in d and isinstance(d.get("paths"), dict) else "no")
except Exception:
    print("no")
')"
[[ "${spec_ok}" == "yes" ]] || fail "/api/v2/spec did not look like OpenAPI" 4
pass "/api/v2/spec is OpenAPI"

# GET /api/v2/projects — 200 (empty list) OR 401 (OIDC active) both accepted.
log "GET /api/v2/projects"
code="$(curl -s -o /dev/null -w '%{http_code}' -m 5 "http://localhost:${HOST_PORT}/api/v2/projects")"
case "${code}" in
  200|401|403) pass "/api/v2/projects status=${code} (acceptable)" ;;
  *)           fail "/api/v2/projects unexpected status=${code}" 5 ;;
esac

log "Smoke test complete."
exit 0
