#!/usr/bin/env bash
# tools/kmac-fetch-secret.sh — read one secret from local KMac Vault container.
#
# Prints the secret value to stdout (no trailing newline). Errors go to stderr.
# Token: KMAC_TOKEN env, else file at KMAC_TOKEN_PATH (default
# ~/.config/kmac/docker-vault-token). URL: KMAC_VAULT_URL (default
# http://127.0.0.1:9999).
#
# Usage:
#   bash tools/kmac-fetch-secret.sh tron:llm_anthropic_key

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $(basename "$0") <vault-key>" >&2
  exit 64
fi

readonly VAULT_KEY="$1"
readonly KMAC_VAULT_URL="${KMAC_VAULT_URL:-http://127.0.0.1:9999}"
readonly KMAC_TOKEN_PATH="${KMAC_TOKEN_PATH:-${HOME}/.config/kmac/docker-vault-token}"

_resolve_token() {
  if [[ -n "${KMAC_TOKEN:-}" ]]; then
    printf '%s' "${KMAC_TOKEN}"
    return 0
  fi
  if [[ -f "${KMAC_TOKEN_PATH}" ]]; then
    tr -d '[:space:]' <"${KMAC_TOKEN_PATH}"
    return 0
  fi
  echo "kmac-fetch-secret: no token (set KMAC_TOKEN or ${KMAC_TOKEN_PATH})" >&2
  return 1
}

TOKEN="$(_resolve_token)" || exit 1

RESP="$(curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  "${KMAC_VAULT_URL%/}/get/${VAULT_KEY}" 2>/dev/null)" || {
  echo "kmac-fetch-secret: fetch failed for ${VAULT_KEY} (is kmac-vault up?)" >&2
  exit 1
}

python3 -c 'import json,sys; print(json.load(sys.stdin)["value"], end="")' <<<"${RESP}"
