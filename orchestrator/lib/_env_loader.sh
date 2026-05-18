# _env_loader.sh — Spine shared connection-string loader (vault-backed).
#
# Source-only module (no shebang, no main). Builds SPINE_DB_URL by combining
# the NON-SECRET Postgres connection parameters (host / port / user / db) with
# the password fetched from the configured vault — per v3 design decision #9,
# secret VALUES never come from env files or environment variables.
#
# Usage (sibling in orchestrator/lib/):
#     source "$(dirname "${BASH_SOURCE[0]}")/_env_loader.sh"
# Usage (caller elsewhere — adjust relative path):
#     source "$(dirname "${BASH_SOURCE[0]}")/../../orchestrator/lib/_env_loader.sh"
#
# Precedence (highest first):
#   1. SPINE_DB_URL already exported by caller / shell env (assembled URL ok;
#      callers that pre-build the URL accept responsibility for keeping the
#      password off-disk — typically the result of THIS file running earlier).
#   2. Non-secret POSTGRES_* env vars exported by caller (compose, etc.) —
#      composed with the vault-fetched password into SPINE_DB_URL.
#   3. db/.env at the repo root — parsed for NON-SECRET POSTGRES_* keys only
#      (POSTGRES_USER / POSTGRES_HOST_PORT / POSTGRES_DB / POSTGRES_BIND_HOST).
#      Any POSTGRES_PASSWORD entry in that file is IGNORED and explicitly
#      unset to defeat accidental promotion of plaintext secrets.
#   4. Hardcoded non-secret fallbacks for the dev stack (user=spine,
#      host=127.0.0.1, port=33001, db=spine).
#
# The password is always sourced from the vault at `spine/postgres/password`.
# If the vault is not yet configured, SPINE_DB_URL is NOT exported and a
# diagnostic is printed to stderr — refusing to fall back to env-borne
# secrets is the whole point of #9.

if [[ -z "${SPINE_DB_URL:-}" ]]; then
  # Locate this file's directory robustly under `set -u`.
  _spine_env_loader_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # Repo root is two levels up (orchestrator/lib/ -> repo root).
  _spine_env_repo_root="$(cd "${_spine_env_loader_dir}/../.." && pwd)"
  _spine_env_file="${SPINE_ENV_FILE:-${_spine_env_repo_root}/db/.env}"

  # Defensive: never propagate a password from the calling environment.
  # The vault is the only source of truth for the password byte.
  unset POSTGRES_PASSWORD PGPASSWORD

  if [[ -f "${_spine_env_file}" ]]; then
    # Read ONLY non-secret keys. POSTGRES_PASSWORD is intentionally excluded.
    for _spine_env_key in POSTGRES_USER POSTGRES_HOST_PORT \
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

  # Non-secret fallbacks for the dev stack.
  : "${POSTGRES_USER:=spine}"
  : "${POSTGRES_BIND_HOST:=127.0.0.1}"
  : "${POSTGRES_HOST_PORT:=33001}"
  : "${POSTGRES_DB:=spine}"

  export POSTGRES_USER POSTGRES_BIND_HOST POSTGRES_HOST_PORT POSTGRES_DB

  # Fetch the password from the vault. The path is canonical per
  # `docs/V3_DESIGN_DECISIONS.md` #9. Errors here are fatal for SPINE_DB_URL
  # construction — we refuse to compose a URL without a vault-backed secret.
  _spine_pgpass_path="${SPINE_PG_PASSWORD_VAULT_PATH:-spine/postgres/password}"
  _spine_pgpass=""
  if command -v python3 >/dev/null 2>&1; then
    _spine_pgpass="$(python3 -m shared.secrets.cli get "${_spine_pgpass_path}" 2>/dev/null)" \
      || _spine_pgpass=""
  fi

  if [[ -z "${_spine_pgpass}" ]]; then
    printf '_env_loader.sh: refusing to build SPINE_DB_URL — vault read of "%s" failed.\n' \
      "${_spine_pgpass_path}" >&2
    printf '_env_loader.sh: run the Spine Day-0 vault wizard, then re-source this file.\n' >&2
  else
    # Assemble the password-bearing line with shell tracing off so a
    # caller that ran `set -x` doesn't accidentally log the secret.
    { _spine_xtrace_was_on=0
      case "$-" in *x*) _spine_xtrace_was_on=1 ;; esac
      set +x
    } 2>/dev/null
    PGPASSWORD="${_spine_pgpass}"
    SPINE_DB_URL="postgresql://${POSTGRES_USER}:${PGPASSWORD}@${POSTGRES_BIND_HOST}:${POSTGRES_HOST_PORT}/${POSTGRES_DB}"
    export PGPASSWORD SPINE_DB_URL
    if [[ "${_spine_xtrace_was_on}" -eq 1 ]]; then
      set -x
    fi
    unset _spine_xtrace_was_on
  fi

  unset _spine_pgpass _spine_pgpass_path \
        _spine_env_loader_dir _spine_env_repo_root _spine_env_file
fi
