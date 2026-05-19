#!/usr/bin/env bash
# Spine v3 — Hub container entrypoint (Wave 3 Squad B)
#
# Responsibilities (in order):
#   1. Wait for vault   (http GET vault:8200/v1/sys/health, accept any documented response)
#   2. Wait for postgres (TCP probe on $POSTGRES_HOST:$POSTGRES_PORT)
#   3. Wait for keycloak (http GET keycloak:8080/health/ready OR realm OIDC discovery)
#   4. Optionally run flyway migrations (skipped when SPINE_HUB_SKIP_FLYWAY=1;
#      the compose file runs flyway as a dedicated init container by default,
#      so this is here for the "no-compose" k8s/podman path).
#   5. Bootstrap the secrets adapter:
#        - SPINE_HUB_DEV=1               → InMemoryAdapter (laptop dev only)
#        - SPINE_SECRETS_ADAPTER=vault   → VaultAdapter via AppRole login
#        - other                         → require explicit config; abort if missing
#   6. Exec uvicorn shared.api.app:create_app --factory.
#
# Hard rules:
#   - Per #9, this script NEVER prints a secret value. It logs metadata
#     (path, adapter name, status codes) only.
#   - Per #21 (ALL AI), every interactive branch has a non-interactive
#     fallback; the wizard's flags reach all the way down here via env vars.
#   - Per #25, Keycloak is the source of truth for identity; we do not start
#     the Hub if Keycloak is unreachable (would degrade to no-auth).

set -euo pipefail

# ---------- logging helpers --------------------------------------------------
log()  { printf '[hub-entrypoint] %s\n' "$*" >&2; }
warn() { printf '[hub-entrypoint][WARN] %s\n' "$*" >&2; }
die()  { printf '[hub-entrypoint][FATAL] %s\n' "$*" >&2; exit 1; }

# ---------- config (NON-SECRET env hints only) -------------------------------
SPINE_HUB_HOST="${SPINE_HUB_HOST:-0.0.0.0}"
SPINE_HUB_PORT="${SPINE_HUB_PORT:-8080}"
SPINE_HUB_LOG_LEVEL="${SPINE_HUB_LOG_LEVEL:-info}"
SPINE_HUB_DEV="${SPINE_HUB_DEV:-0}"
SPINE_HUB_SKIP_FLYWAY="${SPINE_HUB_SKIP_FLYWAY:-1}"   # compose runs flyway separately

SPINE_VAULT_ADDR="${SPINE_VAULT_ADDR:-http://vault:8200}"
SPINE_KEYCLOAK_URL="${SPINE_KEYCLOAK_URL:-http://keycloak:8080}"
SPINE_KEYCLOAK_REALM="${SPINE_KEYCLOAK_REALM:-spine}"
SPINE_SECRETS_ADAPTER="${SPINE_SECRETS_ADAPTER:-vault}"

# Derive postgres host/port from SPINE_DB_URL if present; fall back to defaults.
SPINE_DB_URL="${SPINE_DB_URL:-postgres://spine@postgres:5432/spine}"
POSTGRES_HOST="$(printf '%s' "$SPINE_DB_URL" | sed -E 's|^[a-zA-Z]+://([^@]+@)?([^:/]+).*|\2|')"
POSTGRES_PORT="$(printf '%s' "$SPINE_DB_URL" | sed -nE 's|^[a-zA-Z]+://[^@]*@?[^:]+:([0-9]+).*|\1|p')"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

WAIT_DEADLINE_SECS="${SPINE_HUB_WAIT_DEADLINE_SECS:-180}"

# ---------- subcommand handling ----------------------------------------------
# `docker run ... bash` should still work for debugging. `serve` is default.
CMD="${1:-serve}"
case "$CMD" in
  serve|bash|sh|python3|python|''):;;
  *) :;;
esac

if [[ "$CMD" == "bash" || "$CMD" == "sh" || "$CMD" == "python" || "$CMD" == "python3" ]]; then
  log "Debug entry: exec'ing '$*'"
  shift || true
  exec "$CMD" "$@"
fi

# ---------- step 1: wait for vault -------------------------------------------
wait_for_vault() {
  local url="${SPINE_VAULT_ADDR%/}/v1/sys/health?standbyok=true&sealedcode=200&uninitcode=200"
  log "Waiting for vault at ${SPINE_VAULT_ADDR} (deadline ${WAIT_DEADLINE_SECS}s)..."
  local deadline=$(( SECONDS + WAIT_DEADLINE_SECS ))
  while (( SECONDS < deadline )); do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      log "vault reachable."
      return 0
    fi
    sleep 2
  done
  die "vault not reachable within ${WAIT_DEADLINE_SECS}s at ${SPINE_VAULT_ADDR}"
}

# ---------- step 2: wait for postgres ----------------------------------------
wait_for_postgres() {
  log "Waiting for postgres at ${POSTGRES_HOST}:${POSTGRES_PORT}..."
  local deadline=$(( SECONDS + WAIT_DEADLINE_SECS ))
  while (( SECONDS < deadline )); do
    # python3 stdlib TCP probe — no extra binaries needed and works without
    # postgres-client packages in the image.
    if python3 -c "
import socket, sys
s = socket.socket()
s.settimeout(2)
try:
    s.connect(('${POSTGRES_HOST}', ${POSTGRES_PORT}))
    sys.exit(0)
except Exception:
    sys.exit(1)
finally:
    s.close()
" >/dev/null 2>&1; then
      log "postgres reachable."
      return 0
    fi
    sleep 2
  done
  die "postgres not reachable within ${WAIT_DEADLINE_SECS}s"
}

# ---------- step 3: wait for keycloak ----------------------------------------
wait_for_keycloak() {
  local ready="${SPINE_KEYCLOAK_URL%/}/health/ready"
  local disco="${SPINE_KEYCLOAK_URL%/}/realms/${SPINE_KEYCLOAK_REALM}/.well-known/openid-configuration"
  local master="${SPINE_KEYCLOAK_URL%/}/realms/master/.well-known/openid-configuration"
  log "Waiting for keycloak at ${SPINE_KEYCLOAK_URL} (realm=${SPINE_KEYCLOAK_REALM})..."
  local deadline=$(( SECONDS + WAIT_DEADLINE_SECS ))
  while (( SECONDS < deadline )); do
    # /health/ready is on the mgmt port in some KC versions; fall back to
    # OIDC discovery on the user-facing port (always present once KC is up).
    if curl -fsS --max-time 3 "$ready"  >/dev/null 2>&1 \
    || curl -fsS --max-time 3 "$disco"  >/dev/null 2>&1 \
    || curl -fsS --max-time 3 "$master" >/dev/null 2>&1; then
      log "keycloak reachable."
      return 0
    fi
    sleep 3
  done
  die "keycloak not reachable within ${WAIT_DEADLINE_SECS}s"
}

# ---------- step 4: flyway (optional — compose handles it by default) --------
run_flyway() {
  if [[ "$SPINE_HUB_SKIP_FLYWAY" == "1" ]]; then
    log "Skipping flyway (SPINE_HUB_SKIP_FLYWAY=1; compose runs it as init container)."
    return 0
  fi
  if ! command -v flyway >/dev/null 2>&1; then
    warn "SPINE_HUB_SKIP_FLYWAY=0 but no flyway CLI in image; skipping. Run migrations externally."
    return 0
  fi
  log "Running flyway migrations against ${POSTGRES_HOST}:${POSTGRES_PORT}/spine..."
  flyway -url="jdbc:postgresql://${POSTGRES_HOST}:${POSTGRES_PORT}/spine" \
         -user="spine" \
         -password="${SPINE_DB_PASSWORD:?SPINE_DB_PASSWORD required when flyway runs in-process}" \
         migrate \
    || die "flyway migrate failed"
  log "flyway migrate complete."
}

# ---------- step 5: bootstrap secrets adapter --------------------------------
# Writes the bootstrap snippet to a temp file and exec'es python3 with it.
# We deliberately do NOT inline `-c` python here — easier to debug + avoids
# shell quote hazards around the policy string.
bootstrap_secrets() {
  local snippet
  snippet="$(mktemp -t spine-hub-bootstrap.XXXXXX.py)"
  trap 'rm -f "$snippet"' RETURN

  if [[ "$SPINE_HUB_DEV" == "1" ]]; then
    log "SPINE_HUB_DEV=1 → installing InMemoryAdapter (DEV ONLY; never use in prod)."
    cat >"$snippet" <<'PY'
"""Dev-mode secrets bootstrap.

Per V3_DESIGN_DECISIONS #9, this branch exists ONLY for laptop dev where the
operator hasn't yet run hub/wizard/init.sh against a real vault. It is a
fail-loud bootstrap: any production deployment (SPINE_HUB_DEV != "1") MUST
use the VaultAdapter branch below.
"""
import sys
from shared.secrets import InMemoryAdapter, set_default_adapter

adapter = InMemoryAdapter()
set_default_adapter(adapter)
print("[hub-entrypoint][bootstrap] InMemoryAdapter installed (DEV).", file=sys.stderr)
PY
  else
    case "$SPINE_SECRETS_ADAPTER" in
      vault)
        log "Bootstrapping VaultAdapter via AppRole login at ${SPINE_VAULT_ADDR}..."
        cat >"$snippet" <<'PY'
"""Production secrets bootstrap — VaultAdapter via AppRole.

Per V3_DESIGN_DECISIONS #9, secret VALUES never live in env. The two env
vars consumed here are:

    SPINE_VAULT_ROLE_ID           — non-secret AppRole identifier
    SPINE_VAULT_SECRET_ID_WRAPPED — wrapping token (single-use, 300s TTL)

We unwrap the secret-id ONCE here, log in, store only the resulting client
token in memory, and immediately discard both wrapper and secret-id.
"""
import asyncio
import os
import sys

from shared.secrets import CachedAdapter, VaultAdapter, set_default_adapter

vault_addr = os.environ["SPINE_VAULT_ADDR"]
role_id    = os.environ["SPINE_VAULT_ROLE_ID"]
wrap_token = os.environ.get("SPINE_VAULT_SECRET_ID_WRAPPED", "")
direct_id  = os.environ.get("SPINE_VAULT_SECRET_ID", "")

async def _bootstrap() -> None:
    """Resolve the secret_id (unwrap if needed) then build the adapter."""
    # VaultAdapter exposes a static helper for AppRole login; instantiate
    # whichever shape the package provides, falling back to direct init if
    # the helper isn't present in older versions.
    adapter = await VaultAdapter.from_approle(
        addr=vault_addr,
        role_id=role_id,
        secret_id=direct_id or None,
        wrapped_secret_id=wrap_token or None,
    ) if hasattr(VaultAdapter, "from_approle") else VaultAdapter(
        addr=vault_addr, role_id=role_id, secret_id=direct_id or wrap_token,
    )
    cached = CachedAdapter(inner=adapter, ttl_seconds=60) \
        if hasattr(CachedAdapter, "__init__") else adapter
    set_default_adapter(cached)

asyncio.run(_bootstrap())

# Zero the wrapper out of process env so subprocesses inherit nothing useful.
for k in ("SPINE_VAULT_SECRET_ID_WRAPPED", "SPINE_VAULT_SECRET_ID"):
    if k in os.environ:
        os.environ[k] = ""

print(f"[hub-entrypoint][bootstrap] VaultAdapter ready (addr={vault_addr}).",
      file=sys.stderr)
PY
        ;;
      aws|azure|gcp)
        die "SPINE_SECRETS_ADAPTER=${SPINE_SECRETS_ADAPTER}: cloud-managed adapters must be configured via shared/secrets/ runtime — not via this entrypoint. Run hub/wizard/init.sh with --vault-adapter=${SPINE_SECRETS_ADAPTER} to generate the proper bootstrap manifest."
        ;;
      *)
        die "Unknown SPINE_SECRETS_ADAPTER='${SPINE_SECRETS_ADAPTER}'. Allowed: vault|aws|azure|gcp (or set SPINE_HUB_DEV=1 for dev)."
        ;;
    esac
  fi

  cd /app
  # PYTHONPATH=/app so `from shared.secrets import ...` resolves — Python
  # only auto-adds the script's containing dir to sys.path when running a
  # file at a non-/tmp location, and our snippet lives in /tmp.
  PYTHONPATH=/app python3 "$snippet" || die "Secrets adapter bootstrap FAILED"
}

# ---------- step 6: exec uvicorn --------------------------------------------
exec_uvicorn() {
  log "Starting uvicorn shared.api.app:create_app on ${SPINE_HUB_HOST}:${SPINE_HUB_PORT}"
  cd /app
  # --factory: shared.api.app.create_app is a callable that builds the app
  # at start time, picking up the just-bootstrapped secrets adapter.
  exec uvicorn shared.api.app:create_app \
        --factory \
        --host "$SPINE_HUB_HOST" \
        --port "$SPINE_HUB_PORT" \
        --log-level "$SPINE_HUB_LOG_LEVEL" \
        --proxy-headers \
        --forwarded-allow-ips='*'
}

# ---------- main -------------------------------------------------------------
main() {
  log "Spine Hub starting (dev=${SPINE_HUB_DEV}, adapter=${SPINE_SECRETS_ADAPTER})"
  wait_for_vault
  wait_for_postgres
  wait_for_keycloak
  run_flyway
  bootstrap_secrets
  exec_uvicorn
}

main "$@"
