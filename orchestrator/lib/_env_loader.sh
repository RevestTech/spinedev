# _env_loader.sh — Spine shared connection-string loader.
#
# Source-only module (no shebang, no main). Loads `db/.env` if present and
# exports SPINE_DB_URL so every bash script reaches the same Postgres the
# Docker stack actually publishes (port 33001, real password) instead of
# the legacy hardcoded `spine:spine@localhost:33000` default that ships
# with the .env.example.
#
# Usage (sibling in orchestrator/lib/):
#     source "$(dirname "${BASH_SOURCE[0]}")/_env_loader.sh"
# Usage (caller elsewhere — adjust relative path):
#     source "$(dirname "${BASH_SOURCE[0]}")/../../orchestrator/lib/_env_loader.sh"
#
# Precedence (highest first):
#   1. SPINE_DB_URL already exported by caller / shell env
#   2. POSTGRES_* exported by caller (compose) — composed into SPINE_DB_URL
#   3. db/.env at the repo root — parsed for POSTGRES_* keys
#   4. Hardcoded fallback: postgresql://spine:spine@127.0.0.1:33001/spine
#      (matches the current db/.env shipped with the dev stack)
#
# Fixes wave-8 smoke test F8 + F9.

if [[ -z "${SPINE_DB_URL:-}" ]]; then
  # Locate this file's directory robustly under `set -u`.
  _spine_env_loader_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # Repo root is two levels up (orchestrator/lib/ -> repo root).
  _spine_env_repo_root="$(cd "${_spine_env_loader_dir}/../.." && pwd)"
  _spine_env_file="${SPINE_ENV_FILE:-${_spine_env_repo_root}/db/.env}"

  if [[ -f "${_spine_env_file}" ]]; then
    # Only read the keys we recognise; never blanket-source untrusted .env.
    # Skip comment / blank lines; strip optional surrounding quotes; do not
    # interpret backslash escapes (we want the raw password byte-for-byte).
    for _spine_env_key in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_HOST_PORT \
                          POSTGRES_DB POSTGRES_BIND_HOST; do
      _spine_env_val="$(
        grep -E "^[[:space:]]*${_spine_env_key}=" "${_spine_env_file}" \
          | head -1 \
          | sed -E "s/^[[:space:]]*${_spine_env_key}=//; s/^['\"]//; s/['\"][[:space:]]*$//"
      )" || _spine_env_val=""
      if [[ -n "${_spine_env_val}" ]]; then
        # Only set if caller hasn't already exported it.
        if [[ -z "${!_spine_env_key:-}" ]]; then
          printf -v "${_spine_env_key}" '%s' "${_spine_env_val}"
          export "${_spine_env_key?}"
        fi
      fi
    done
    unset _spine_env_key _spine_env_val
  fi

  # Hardcoded fallbacks — match the current db/.env defaults so the bash
  # tooling works out of the box on a fresh `make up`.
  : "${POSTGRES_USER:=spine}"
  : "${POSTGRES_PASSWORD:=spine}"
  : "${POSTGRES_BIND_HOST:=127.0.0.1}"
  : "${POSTGRES_HOST_PORT:=33001}"
  : "${POSTGRES_DB:=spine}"

  export POSTGRES_USER POSTGRES_PASSWORD POSTGRES_BIND_HOST \
         POSTGRES_HOST_PORT POSTGRES_DB

  SPINE_DB_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_BIND_HOST}:${POSTGRES_HOST_PORT}/${POSTGRES_DB}"
  export SPINE_DB_URL

  unset _spine_env_loader_dir _spine_env_repo_root _spine_env_file
fi
