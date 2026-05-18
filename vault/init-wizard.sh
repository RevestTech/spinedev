#!/usr/bin/env bash
# Spine v3 — Vault (OpenBao) Day-0 init wizard
#
# Per V3_DESIGN_DECISIONS #9 (Vault-only secrets, OpenBao Day-0 default) and
# #32 layer 8 (Vault unseal recovery — Shamir OR cloud-KMS auto-unseal).
#
# Responsibilities:
#   1. Confirm OpenBao container is reachable.
#   2. Ask operator: Shamir secret-sharing (humans hold key shares) OR cloud
#      KMS auto-unseal (AWS / Azure / GCP).
#   3. Initialize Vault.
#   4. Display recovery keys ONCE; do NOT write to disk unless the operator
#      explicitly opted in via --recovery-output=<path>.
#   5. Unseal (Shamir path) or confirm auto-unseal (KMS path).
#   6. Enable KV v2 at spine/.
#   7. Write the spine-hub + spine-readonly policies.
#   8. Create an AppRole for the Spine Hub container and print the role-id +
#      a wrapped secret-id for the operator to hand off to Hub Day-0.
#
# Interactive by default. CI / scripted use:
#   ./init-wizard.sh --no-interactive --unseal=shamir --shares=5 --threshold=3 \
#       --recovery-output=/secure/path/init.json
#
# Hard constraints (from agent brief):
#   - Recovery keys displayed ONCE.
#   - --recovery-output writes chmod 600 with a loud "MOVE THIS OFFLINE" warning.
#   - No secret values committed to git (the .gitignore excludes wizard outputs).

set -euo pipefail

# --- Config / defaults -------------------------------------------------------
VAULT_ADDR_DEFAULT="${BAO_ADDR:-${VAULT_ADDR:-http://127.0.0.1:8200}}"
KV_MOUNT="spine"               # mount path for KV v2 (rationale in README)
APPROLE_NAME="spine-hub"
POLICY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/policies"

# Flags
INTERACTIVE=1
UNSEAL_MODE=""                 # shamir | aws | azure | gcp
SHARES=5
THRESHOLD=3
RECOVERY_OUTPUT=""
VAULT_ADDR_OVERRIDE=""

# --- Helpers -----------------------------------------------------------------
log()  { printf '[wizard] %s\n' "$*" >&2; }
warn() { printf '[wizard][WARN] %s\n' "$*" >&2; }
err()  { printf '[wizard][ERROR] %s\n' "$*" >&2; exit 1; }

# bao CLI is the canonical OpenBao client. vault CLI works against OpenBao for
# now (compatible API). Prefer bao when present.
pick_cli() {
  if command -v bao >/dev/null 2>&1; then
    echo "bao"
  elif command -v vault >/dev/null 2>&1; then
    warn "Using hashicorp/vault CLI against OpenBao (compatible)."
    echo "vault"
  else
    err "Neither 'bao' nor 'vault' CLI found. Install OpenBao: https://openbao.org"
  fi
}

usage() {
  cat <<'EOF'
Usage: init-wizard.sh [OPTIONS]

Interactive Day-0 Vault initialization for Spine v3.

Options:
  --no-interactive            Run without prompts (CI mode). Requires --unseal.
  --unseal=MODE               shamir | aws | azure | gcp
  --shares=N                  Shamir key shares to generate (default 5).
  --threshold=N               Shamir threshold to unseal (default 3).
  --recovery-output=PATH      Write init output (recovery keys + root token)
                              to PATH with chmod 600. WARNING: you MUST move
                              this file offline immediately.
  --vault-addr=URL            Override Vault address (default $BAO_ADDR or
                              http://127.0.0.1:8200).
  -h, --help                  Show this help.

Examples:
  ./init-wizard.sh
  ./init-wizard.sh --no-interactive --unseal=shamir --shares=5 --threshold=3 \
      --recovery-output=/secure/init.json
  ./init-wizard.sh --no-interactive --unseal=aws

EOF
}

# --- Arg parsing -------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-interactive)        INTERACTIVE=0; shift ;;
    --unseal=*)              UNSEAL_MODE="${1#*=}"; shift ;;
    --shares=*)              SHARES="${1#*=}"; shift ;;
    --threshold=*)           THRESHOLD="${1#*=}"; shift ;;
    --recovery-output=*)     RECOVERY_OUTPUT="${1#*=}"; shift ;;
    --vault-addr=*)          VAULT_ADDR_OVERRIDE="${1#*=}"; shift ;;
    -h|--help)               usage; exit 0 ;;
    *)                       err "Unknown flag: $1 (try --help)" ;;
  esac
done

VAULT_ADDR_USE="${VAULT_ADDR_OVERRIDE:-$VAULT_ADDR_DEFAULT}"
export BAO_ADDR="$VAULT_ADDR_USE"
export VAULT_ADDR="$VAULT_ADDR_USE"  # vault CLI compatibility

CLI="$(pick_cli)"

# --- Step 1: reachability ----------------------------------------------------
log "Target Vault: $VAULT_ADDR_USE"
log "Checking reachability..."
if ! curl -sf --max-time 5 "${VAULT_ADDR_USE}/v1/sys/health?standbyok=true&sealedcode=200&uninitcode=200" >/dev/null; then
  err "Cannot reach Vault at ${VAULT_ADDR_USE}. Start the container first (docker compose -f vault/docker-compose.yml up -d) and retry."
fi
log "Vault reachable."

# Determine current init state.
INIT_STATUS_JSON="$(curl -sf "${VAULT_ADDR_USE}/v1/sys/init" || true)"
ALREADY_INIT="false"
if echo "$INIT_STATUS_JSON" | grep -q '"initialized":true'; then
  ALREADY_INIT="true"
fi

if [[ "$ALREADY_INIT" == "true" ]]; then
  warn "Vault is already initialized. The wizard will only configure the"
  warn "KV mount + policies + AppRole if you provide a root token via env"
  warn "BAO_TOKEN. To start over, destroy the data volume first."
  if [[ -z "${BAO_TOKEN:-${VAULT_TOKEN:-}}" ]]; then
    err "Set BAO_TOKEN (or VAULT_TOKEN) to continue configuring an existing Vault."
  fi
  SKIP_INIT=1
else
  SKIP_INIT=0
fi

# --- Step 2: pick unseal mode ------------------------------------------------
if [[ -z "$UNSEAL_MODE" ]]; then
  if [[ "$INTERACTIVE" -eq 0 ]]; then
    err "--no-interactive requires --unseal=<shamir|aws|azure|gcp>"
  fi
  cat <<'EOM'

Choose unseal strategy:
  1) Shamir secret-sharing   — humans hold key shares (default 3-of-5).
                               Best for laptop / dev / small-team deployments.
  2) AWS KMS auto-unseal     — Vault auto-unseals via AWS KMS on restart.
  3) Azure Key Vault auto-unseal
  4) GCP KMS auto-unseal

EOM
  read -r -p "Selection [1-4, default 1]: " sel
  case "${sel:-1}" in
    1) UNSEAL_MODE="shamir" ;;
    2) UNSEAL_MODE="aws" ;;
    3) UNSEAL_MODE="azure" ;;
    4) UNSEAL_MODE="gcp" ;;
    *) err "Invalid selection: $sel" ;;
  esac
fi

case "$UNSEAL_MODE" in
  shamir|aws|azure|gcp) : ;;
  *) err "Invalid --unseal mode: $UNSEAL_MODE (use shamir|aws|azure|gcp)" ;;
esac

log "Unseal mode: $UNSEAL_MODE"

# --- Step 3: init ------------------------------------------------------------
INIT_RESPONSE=""
if [[ "$SKIP_INIT" -eq 0 ]]; then
  log "Initializing Vault..."
  if [[ "$UNSEAL_MODE" == "shamir" ]]; then
    INIT_RESPONSE="$(curl -sf -X POST "${VAULT_ADDR_USE}/v1/sys/init" \
      -H 'Content-Type: application/json' \
      -d "{\"secret_shares\": ${SHARES}, \"secret_threshold\": ${THRESHOLD}}")" \
      || err "Init failed (Shamir mode). Check Vault logs."
  else
    # KMS modes use recovery shares (not unseal shares) because the unseal
    # mechanism is the cloud KMS, not human key holders. We still issue a
    # recovery share set so humans can recover in a KMS-loss disaster.
    INIT_RESPONSE="$(curl -sf -X POST "${VAULT_ADDR_USE}/v1/sys/init" \
      -H 'Content-Type: application/json' \
      -d "{\"recovery_shares\": ${SHARES}, \"recovery_threshold\": ${THRESHOLD}}")" \
      || err "Init failed. For KMS modes, the OpenBao server config MUST include the seal stanza BEFORE running this wizard. See vault/unseal/kms-config-${UNSEAL_MODE}.md."
  fi
  log "Vault initialized."
else
  log "Skipping init (existing Vault)."
fi

# --- Step 4: handle recovery keys -------------------------------------------
# Display ONCE. Only write to disk if --recovery-output was given.
if [[ -n "$INIT_RESPONSE" ]]; then
  cat <<'EOM'

================================================================================
 RECOVERY KEYS + ROOT TOKEN  ---  DISPLAYED ONCE  ---  CAPTURE NOW
================================================================================
EOM
  echo "$INIT_RESPONSE"
  cat <<'EOM'
================================================================================
 You will NOT see these again. If you lose them:
   - Shamir: you lose the Vault. No vendor recovery is possible. Backups
     restored from snapshot will require the SAME unseal keys.
   - KMS:    recovery keys are your last resort if the KMS key is destroyed
     or your cloud account is locked out.
 Distribute Shamir shares to separate humans / safes / locations.
 Store the root token offline; generate scoped tokens for daily ops.
================================================================================
EOM

  if [[ -n "$RECOVERY_OUTPUT" ]]; then
    warn "Writing init output to: $RECOVERY_OUTPUT"
    warn "MOVE THIS FILE OFFLINE IMMEDIATELY. Do NOT leave it on disk."
    # Ensure parent dir exists; refuse to overwrite.
    mkdir -p "$(dirname "$RECOVERY_OUTPUT")"
    if [[ -e "$RECOVERY_OUTPUT" ]]; then
      err "Refusing to overwrite existing file: $RECOVERY_OUTPUT"
    fi
    umask 077
    printf '%s\n' "$INIT_RESPONSE" > "$RECOVERY_OUTPUT"
    chmod 600 "$RECOVERY_OUTPUT"
    warn "Wrote $RECOVERY_OUTPUT (mode 600). MOVE IT OFFLINE NOW."
  else
    if [[ "$INTERACTIVE" -eq 1 ]]; then
      read -r -p "Press ENTER once you have captured the keys (this prompt blocks until you confirm)... " _
    fi
  fi
fi

# --- Step 5: unseal (Shamir only) -------------------------------------------
ROOT_TOKEN=""
if [[ -n "$INIT_RESPONSE" ]]; then
  # Extract root_token via python (always present on any modern macOS/Linux)
  if command -v python3 >/dev/null 2>&1; then
    ROOT_TOKEN="$(printf '%s' "$INIT_RESPONSE" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("root_token",""))')"
  fi
fi
if [[ -z "$ROOT_TOKEN" ]]; then
  ROOT_TOKEN="${BAO_TOKEN:-${VAULT_TOKEN:-}}"
fi
[[ -n "$ROOT_TOKEN" ]] || err "No root token available. Cannot continue configuration."
export BAO_TOKEN="$ROOT_TOKEN"
export VAULT_TOKEN="$ROOT_TOKEN"

if [[ "$UNSEAL_MODE" == "shamir" && "$SKIP_INIT" -eq 0 ]]; then
  log "Unsealing with first $THRESHOLD shares (Shamir)..."
  if ! command -v python3 >/dev/null 2>&1; then
    err "python3 required to parse keys for automatic unseal. Unseal manually with: bao operator unseal <key>"
  fi
  # Extract keys array. THRESHOLD passed via env to avoid quoting hazards.
  KEYS="$(printf '%s' "$INIT_RESPONSE" | THRESHOLD="$THRESHOLD" python3 -c '
import sys, json, os
n = int(os.environ["THRESHOLD"])
d = json.load(sys.stdin)
for k in d.get("keys_base64", d.get("keys", []))[:n]:
    print(k)
')"
  while IFS= read -r key; do
    [[ -z "$key" ]] && continue
    curl -sf -X POST "${VAULT_ADDR_USE}/v1/sys/unseal" \
      -H 'Content-Type: application/json' \
      -d "{\"key\":\"${key}\"}" >/dev/null
  done <<< "$KEYS"
  log "Unseal complete."
elif [[ "$UNSEAL_MODE" != "shamir" ]]; then
  log "Skipping unseal step — KMS auto-unseal handles this on startup."
fi

# Sanity: confirm unsealed.
SEALED="$(curl -sf "${VAULT_ADDR_USE}/v1/sys/seal-status" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("sealed",True))' 2>/dev/null || echo "true")"
if [[ "$SEALED" == "True" || "$SEALED" == "true" ]]; then
  err "Vault is still sealed. Aborting configuration. See vault/unseal/*.md for recovery."
fi

# --- Step 6: enable KV v2 at spine/ -----------------------------------------
log "Enabling KV v2 secrets engine at '${KV_MOUNT}/' ..."
# Idempotent: 400 means already enabled, which is fine.
curl -s -X POST "${VAULT_ADDR_USE}/v1/sys/mounts/${KV_MOUNT}" \
  -H "X-Vault-Token: ${ROOT_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"type":"kv","options":{"version":"2"},"description":"Spine v3 secrets (per #9 Vault-only)"}' \
  >/dev/null || true

# --- Step 7: write policies --------------------------------------------------
write_policy() {
  local name="$1" file="$2"
  [[ -f "$file" ]] || err "Policy file missing: $file"
  local payload
  # JSON-encode the HCL string so embedded quotes / newlines round-trip safely.
  payload="$(python3 -c 'import sys,json;print(json.dumps({"policy": open(sys.argv[1]).read()}))' "$file")"
  curl -sf -X PUT "${VAULT_ADDR_USE}/v1/sys/policies/acl/${name}" \
    -H "X-Vault-Token: ${ROOT_TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "${payload}" >/dev/null || err "Failed writing policy: $name"
  log "Wrote policy: $name"
}

write_policy "spine-hub"      "${POLICY_DIR}/spine-hub.hcl"
write_policy "spine-readonly" "${POLICY_DIR}/spine-readonly.hcl"

# --- Step 8: enable AppRole + create spine-hub role -------------------------
log "Enabling auth/approle..."
curl -s -X POST "${VAULT_ADDR_USE}/v1/sys/auth/approle" \
  -H "X-Vault-Token: ${ROOT_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"type":"approle"}' >/dev/null || true

log "Creating AppRole: ${APPROLE_NAME}"
curl -sf -X POST "${VAULT_ADDR_USE}/v1/auth/approle/role/${APPROLE_NAME}" \
  -H "X-Vault-Token: ${ROOT_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"token_policies":["spine-hub"],"token_ttl":"1h","token_max_ttl":"24h","secret_id_ttl":"24h"}' >/dev/null \
  || err "Failed creating AppRole: ${APPROLE_NAME}"

ROLE_ID="$(curl -sf -H "X-Vault-Token: ${ROOT_TOKEN}" "${VAULT_ADDR_USE}/v1/auth/approle/role/${APPROLE_NAME}/role-id" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["role_id"])')"

# Wrapped secret-id: the operator passes the wrapping token to Hub Day-0; Hub
# unwraps once to get the real secret-id. Limits exposure to a single use.
WRAPPED="$(curl -sf -X POST "${VAULT_ADDR_USE}/v1/auth/approle/role/${APPROLE_NAME}/secret-id" \
  -H "X-Vault-Token: ${ROOT_TOKEN}" \
  -H 'X-Vault-Wrap-TTL: 300' \
  -H 'Content-Type: application/json' \
  -d '{}')"
WRAP_TOKEN="$(printf '%s' "$WRAPPED" | python3 -c 'import sys,json;print(json.load(sys.stdin)["wrap_info"]["token"])')"

cat <<EOM

================================================================================
 SPINE HUB APP-ROLE CREDENTIALS
================================================================================
 role_id:                 ${ROLE_ID}
 wrapped_secret_id_token: ${WRAP_TOKEN}   (TTL: 300s, single-unwrap)

 Hand these to the Spine Hub container (env vars):
   SPINE_VAULT_ADDR=${VAULT_ADDR_USE}
   SPINE_VAULT_ROLE_ID=${ROLE_ID}
   SPINE_VAULT_SECRET_ID_WRAPPED=${WRAP_TOKEN}

 shared/secrets/ (VaultAdapter) consumes these on Hub startup, unwraps the
 secret-id once, logs in, and discards both wrapper and secret-id.
================================================================================
EOM

log "Wizard complete."
