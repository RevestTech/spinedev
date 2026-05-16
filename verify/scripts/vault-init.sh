#!/bin/sh
# vault-init.sh — Provision all Tron secrets into the container keyvault
# Runs once at startup via the vault-init sidecar container.
#
# For development: generates random passwords if not already set.
# For production: this script is replaced by your CI/CD secret provisioning.

set -e

echo "[vault-init] Waiting for Vault to be ready..."
until vault status > /dev/null 2>&1; do
    sleep 1
done
echo "[vault-init] Vault is ready."

# Enable KV v2 secrets engine (idempotent)
vault secrets enable -path=secret -version=2 kv 2>/dev/null || true

# Helper: write secret only if it doesn't exist yet (don't overwrite on restart)
put_if_absent() {
    local path="$1"
    shift
    if vault kv get "$path" > /dev/null 2>&1; then
        echo "[vault-init] Secret $path already exists, skipping."
    else
        vault kv put "$path" "$@"
        echo "[vault-init] Provisioned $path"
    fi
}

# Generate random passwords for dev (32 hex chars)
gen_password() {
    cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 32
}

# ── Database ──
put_if_absent secret/tron/db \
    password="$(gen_password)"

# ── Redis ──
put_if_absent secret/tron/redis \
    password="$(gen_password)"

# ── MinIO ──
put_if_absent secret/tron/minio \
    user="tron-minio-admin" \
    password="$(gen_password)" \
    kms-key="tron-minio-key:$(cat /dev/urandom | tr -dc 'a-f0-9' | head -c 32)"

# ── Auth ──
put_if_absent secret/tron/auth \
    secret-key="$(gen_password)" \
    jwt-secret="$(gen_password)" \
    master-key="$(gen_password)"

# ── LLM API Keys ──
# In development, these are placeholders. Replace with real keys in the vault UI
# or via: vault kv put secret/tron/llm openai-key=sk-... anthropic-key=sk-ant-...
put_if_absent secret/tron/llm \
    openai-key="${OPENAI_API_KEY:-REPLACE_ME_IN_VAULT}" \
    anthropic-key="${ANTHROPIC_API_KEY:-REPLACE_ME_IN_VAULT}"

# ── Grafana ──
put_if_absent secret/tron/grafana \
    password="$(gen_password)"

echo ""
echo "[vault-init] All secrets provisioned. Access Vault UI at http://localhost:8200"
echo "[vault-init] Dev token: ${VAULT_TOKEN}"
echo "[vault-init] Done."
