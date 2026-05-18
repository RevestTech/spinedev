#!/usr/bin/env bash
# Spine v3 — vault/ smoke test
#
# Starts an ephemeral OpenBao container in DEV MODE ONLY (in-memory, auto-init,
# single hardcoded root token), exercises write + read + delete on the KV v2
# mount, and tears down. NO PRODUCTION DATA touched.
#
# Dev mode is unequivocally NOT for production:
#   - Master key + recovery shares are in-memory only.
#   - Root token is fixed at startup (we set it ourselves).
#   - All data lost on container stop.
# That is EXACTLY what we want for a CI smoke test.
#
# Polls vault health with bounded retries (max 30s) — does NOT block forever.
#
# Usage:
#   ./tests/test-vault-up.sh
#
# Exits non-zero on any failure step.

set -euo pipefail

# --- Config ------------------------------------------------------------------
CONTAINER_NAME="spine-vault-smoketest-$$"
ROOT_TOKEN="spine-smoketest-root-token"
HOST_PORT="${SMOKETEST_VAULT_PORT:-8299}"     # avoid clash with running vault on 8200
IMAGE="${SPINE_VAULT_TEST_IMAGE:-openbao/openbao:2.1.1}"
MAX_WAIT_SECS=30
ADDR="http://127.0.0.1:${HOST_PORT}"

log()  { printf '[smoketest] %s\n' "$*" >&2; }
fail() { printf '[smoketest][FAIL] %s\n' "$*" >&2; exit 1; }

# --- Pre-flight --------------------------------------------------------------
command -v docker >/dev/null 2>&1 || fail "docker required for smoke test"
command -v curl   >/dev/null 2>&1 || fail "curl required for smoke test"

cleanup() {
  log "Tearing down: $CONTAINER_NAME"
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

# --- Step 1: start container in dev mode ------------------------------------
log "Starting $IMAGE as $CONTAINER_NAME on port $HOST_PORT (DEV MODE)..."
docker run -d --rm \
  --name "$CONTAINER_NAME" \
  --cap-add IPC_LOCK \
  -p "${HOST_PORT}:8200" \
  -e "BAO_DEV_ROOT_TOKEN_ID=${ROOT_TOKEN}" \
  -e "BAO_DEV_LISTEN_ADDRESS=0.0.0.0:8200" \
  "$IMAGE" server -dev >/dev/null

# --- Step 2: poll for readiness (bounded) -----------------------------------
log "Waiting for Vault to become ready (max ${MAX_WAIT_SECS}s)..."
DEADLINE=$(( $(date +%s) + MAX_WAIT_SECS ))
READY=0
while [[ $(date +%s) -lt $DEADLINE ]]; do
  if curl -sf --max-time 2 "${ADDR}/v1/sys/health?standbyok=true" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done
[[ $READY -eq 1 ]] || fail "Vault did not become ready within ${MAX_WAIT_SECS}s"
log "Vault ready."

# --- Step 3: verify dev mode unseals automatically --------------------------
SEAL_JSON="$(curl -sf "${ADDR}/v1/sys/seal-status")"
echo "$SEAL_JSON" | grep -q '"sealed":false' \
  || fail "Vault unexpectedly sealed: $SEAL_JSON"

# --- Step 4: confirm KV v2 default mount works (dev mode mounts 'secret/') --
# Dev mode pre-mounts secret/ at KV v2. We use that for the smoke test
# instead of mounting our own — simpler + tests the same code path.

log "Writing test secret..."
curl -sf -X POST "${ADDR}/v1/secret/data/spine-smoketest" \
  -H "X-Vault-Token: ${ROOT_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"data":{"canary":"spine-v3-wave0-vault"}}' >/dev/null \
  || fail "KV v2 write failed"

log "Reading test secret..."
READBACK="$(curl -sf -X GET "${ADDR}/v1/secret/data/spine-smoketest" \
  -H "X-Vault-Token: ${ROOT_TOKEN}")"
echo "$READBACK" | grep -q '"canary":"spine-v3-wave0-vault"' \
  || fail "Readback mismatch: $READBACK"

log "Deleting test secret (soft-delete via KV v2)..."
curl -sf -X DELETE "${ADDR}/v1/secret/data/spine-smoketest" \
  -H "X-Vault-Token: ${ROOT_TOKEN}" >/dev/null \
  || fail "Delete failed"

# --- Step 5: policy upload (use spine-hub.hcl) ------------------------------
POLICY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/policies"
if [[ -f "$POLICY_DIR/spine-hub.hcl" ]]; then
  log "Uploading spine-hub policy as smoke check..."
  HCL_JSON="$(python3 -c 'import sys,json;print(json.dumps({"policy":open(sys.argv[1]).read()}))' "$POLICY_DIR/spine-hub.hcl")"
  curl -sf -X PUT "${ADDR}/v1/sys/policies/acl/spine-hub" \
    -H "X-Vault-Token: ${ROOT_TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "$HCL_JSON" >/dev/null \
    || fail "Policy upload failed"
  log "Policy upload OK."
else
  log "SKIP: policies/spine-hub.hcl not found (running outside repo?)"
fi

log "Smoke test PASSED."
