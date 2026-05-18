#!/usr/bin/env bash
#
# Spine v3 — Keycloak smoke test
# ------------------------------
#
# What it does:
#   1. Spins up an EPHEMERAL Keycloak (H2 in-memory; no Postgres dep; explicitly per spec
#      "H2 is OK only for ephemeral test mode").
#   2. Waits for /health/ready.
#   3. Fetches OIDC discovery + JWKS for the 'master' realm (default in ephemeral mode; we don't
#      run the full bootstrap here — that's a separate integration test in Wave 3).
#   4. Asserts the JWKS has at least one key with kty=RSA.
#   5. Tears down the container.
#
# Exit codes:
#   0  ok
#   1  unexpected failure
#   2  docker not available (skip, not fail)
#   3  Keycloak did not become ready
#   4  JWKS fetch / shape assertion failed
#
# This script is safe to run in CI; it uses unique container/network names so concurrent runs
# don't collide.

set -euo pipefail

KC_VERSION="${KC_VERSION:-26.0.7}"
KC_IMAGE="quay.io/keycloak/keycloak:${KC_VERSION}"
RUN_ID="kc-smoke-$$-$(date +%s)"
CONTAINER_NAME="spine-${RUN_ID}"
PORT=18080

log() { printf '[test-keycloak-up] %s\n' "$*" >&2; }
fail() { log "FAIL: $*"; cleanup; exit "${2:-1}"; }
skip() { log "SKIP: $*"; exit 2; }

cleanup() {
  log "Cleanup: removing container ${CONTAINER_NAME}"
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

# ---------- preflight -------------------------------------------------------

command -v docker >/dev/null 2>&1 || skip "docker not available"
docker info >/dev/null 2>&1 || skip "docker daemon not reachable"
command -v curl   >/dev/null 2>&1 || fail "curl required" 1
command -v python3 >/dev/null 2>&1 || fail "python3 required" 1

# ---------- start ephemeral Keycloak ---------------------------------------

log "Starting ephemeral Keycloak (${KC_IMAGE}) on port ${PORT} as ${CONTAINER_NAME}"
docker run -d --name "${CONTAINER_NAME}" \
  -e KEYCLOAK_ADMIN=admin \
  -e KEYCLOAK_ADMIN_PASSWORD=admin-smoke-test \
  -e KC_HEALTH_ENABLED=true \
  -e KC_HTTP_ENABLED=true \
  -e KC_HOSTNAME_STRICT=false \
  -p "${PORT}:8080" \
  -p "$((PORT+1000)):9000" \
  "${KC_IMAGE}" \
  start-dev >/dev/null \
  || fail "docker run failed" 1

# ---------- wait for ready --------------------------------------------------

log "Waiting for /health/ready (timeout 180s)…"
deadline=$(( SECONDS + 180 ))
ready=0
while (( SECONDS < deadline )); do
  if curl -fsS -m 3 "http://localhost:$((PORT+1000))/health/ready" >/dev/null 2>&1 \
     || curl -fsS -m 3 "http://localhost:${PORT}/health/ready" >/dev/null 2>&1 \
     || curl -fsS -m 3 "http://localhost:${PORT}/realms/master/.well-known/openid-configuration" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 3
done
(( ready == 1 )) || fail "Keycloak did not become ready within 180s" 3
log "Keycloak is ready."

# ---------- fetch OIDC discovery + JWKS ------------------------------------

log "Fetching OIDC discovery for realm 'master'"
DISCOVERY="$(curl -fsS "http://localhost:${PORT}/realms/master/.well-known/openid-configuration")" \
  || fail "OIDC discovery fetch failed" 4

JWKS_URI="$(printf '%s' "${DISCOVERY}" | python3 -c "import json,sys; print(json.load(sys.stdin)['jwks_uri'])")" \
  || fail "could not parse jwks_uri from discovery" 4
log "jwks_uri = ${JWKS_URI}"

# Hostname may differ inside container vs host; rewrite to localhost:${PORT}.
JWKS_URI_LOCAL="$(printf '%s' "${JWKS_URI}" | python3 -c "
import sys, re
u = sys.stdin.read().strip()
print(re.sub(r'^https?://[^/]+', 'http://localhost:${PORT}', u))
")"
log "jwks_uri (host-local) = ${JWKS_URI_LOCAL}"

log "Fetching JWKS"
JWKS="$(curl -fsS "${JWKS_URI_LOCAL}")" || fail "JWKS fetch failed" 4

# ---------- assert JWKS shape ----------------------------------------------

KEY_COUNT="$(printf '%s' "${JWKS}" | python3 -c "
import json, sys
keys = json.load(sys.stdin).get('keys', [])
rsa = [k for k in keys if k.get('kty') == 'RSA']
print(len(rsa))
")"

if [[ "${KEY_COUNT}" -lt 1 ]]; then
  fail "expected >=1 RSA key in JWKS, got ${KEY_COUNT}" 4
fi
log "JWKS OK: ${KEY_COUNT} RSA key(s) present"

log "PASS: ephemeral Keycloak start + ready + OIDC discovery + JWKS + key shape"
exit 0
