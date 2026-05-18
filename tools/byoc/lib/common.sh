#!/usr/bin/env bash
# tools/byoc/lib/common.sh — shared helpers for BYOC provisioners.
#
# Sourced by tools/byoc/provision.sh AND each tools/byoc/clouds/<cloud>.sh.
# Pure-bash, no external deps. Provides:
#
#   * Logging + banner + diag
#   * Flag parsing helpers
#   * Vault-ref resolution wrapper (NEVER reads secret values into env vars)
#   * Idempotency / lock-file
#   * Dry-run helpers (echo-the-command-not-run-it)
#   * Stub-mode helpers (BYOC_STUB_CALLS=1 → never call the real cloud API)
#
# Design constraints honoured (docs/V3_DESIGN_DECISIONS.md):
#   #9   Vault-only secrets. We accept vault refs as flags; we resolve them
#        via `shared.secrets.get_secret` at runtime — never write the value
#        anywhere, never log it. The reference itself is safe to log.
#   #15  BYOC ≠ SaaS. We are VENDOR code running with a CUSTOMER-DELEGATED
#        role; the script is run from vendor infra, but every cloud API
#        call uses the customer's delegated credentials.
#   #21  Every interactive prompt MUST have a non-interactive equivalent
#        via a flag — so an AI agent can drive every flow.

set -uo pipefail

# Re-entrancy guard.
if [[ -n "${_SPINE_BYOC_COMMON_LOADED:-}" ]]; then
  return 0
fi
_SPINE_BYOC_COMMON_LOADED=1

# ─── paths ──────────────────────────────────────────────────────────
BYOC_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BYOC_DIR="$(cd "$BYOC_LIB_DIR/.." && pwd)"
BYOC_REPO_ROOT="$(cd "$BYOC_DIR/../.." && pwd)"

# ─── logging ────────────────────────────────────────────────────────
_byoc_ts()  { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
byoc_log()  { printf '%s [byoc:%s] %s\n' "$(_byoc_ts)" "${BYOC_LOG_TAG:-provision}" "$*" >&2; }
byoc_warn() { printf '%s [byoc:%s][WARN] %s\n' "$(_byoc_ts)" "${BYOC_LOG_TAG:-provision}" "$*" >&2; }
byoc_die()  { printf '%s [byoc:%s][FATAL] %s\n' "$(_byoc_ts)" "${BYOC_LOG_TAG:-provision}" "$*" >&2; exit "${BYOC_DIE_CODE:-1}"; }

byoc_banner() {
  printf '\n================================================================================\n' >&2
  printf ' %s\n' "$*" >&2
  printf '================================================================================\n\n' >&2
}

# ─── exit codes (shared) ────────────────────────────────────────────
# 0  ok
# 1  generic failure
# 2  bad input / unknown flag
# 3  delegated-role validation failed
# 4  cloud API failure
# 5  resource already exists, --force not given
# 6  unsupported cloud / mode / region

# ─── flag helper: extract value from `--key=value` or fail ──────────
byoc_flag_value() {
  # Usage: byoc_flag_value "--cloud=aws"  →  prints "aws"
  printf '%s' "${1#*=}"
}

byoc_require() {
  # byoc_require "<varname>" "<flag-name>"  → die if empty
  local var="$1" flag="$2"
  local val="${!var:-}"
  [[ -n "$val" ]] || byoc_die "missing required flag: $flag"
}

# ─── dry-run + stub-mode helpers ────────────────────────────────────
# BYOC_DRY_RUN=1   → print the plan, do not execute
# BYOC_STUB_CALLS=1 → execute everything EXCEPT the real cloud API calls;
#                    use byoc_run_or_stub to wrap a cloud-API call.
byoc_run_or_stub() {
  # Usage: byoc_run_or_stub "<human label>" <argv...>
  local label="$1"; shift
  if [[ "${BYOC_DRY_RUN:-0}" == "1" ]]; then
    byoc_log "[dry-run] would run: $label  →  $*"
    return 0
  fi
  if [[ "${BYOC_STUB_CALLS:-0}" == "1" ]]; then
    byoc_log "[stub] would call cloud API: $label  →  $*"
    return 0
  fi
  byoc_log "running: $label"
  "$@"
}

# ─── vault-ref resolution wrapper ───────────────────────────────────
# NEVER prints the value. NEVER writes it to a file.
# Returns it on stdout; callers should pipe into the consumer process
# (`<( … )` or `--password-stdin`) instead of into a variable.
#
# Form: byoc_resolve_vault_ref "<vault-ref-spec>"
#   e.g.  byoc_resolve_vault_ref "vault://kv/byoc/<account>/aws_access_key_id"
byoc_resolve_vault_ref() {
  local ref="${1:-}"
  [[ -n "$ref" ]] || byoc_die "byoc_resolve_vault_ref: empty ref"
  case "$ref" in
    vault://*)
      local path="${ref#vault://}"
      if [[ "${BYOC_STUB_CALLS:-0}" == "1" || "${BYOC_DRY_RUN:-0}" == "1" ]]; then
        # Synthesise an obviously-fake placeholder so downstream `aws sts`
        # calls fail loudly if accidentally not stubbed.
        printf '__STUB__:%s' "$path"
        return 0
      fi
      # Real resolution via shared.secrets. Single-line python so we do
      # not write the value to disk.
      python3 -c "from shared.secrets import get_secret; import sys; sys.stdout.write(get_secret(sys.argv[1]))" "$path"
      ;;
    *)
      byoc_die "byoc_resolve_vault_ref: refs MUST start with 'vault://' (per #9). Got: ${ref%%[!a-zA-Z0-9_./:-]*}…"
      ;;
  esac
}

# ─── lock file (idempotency) ────────────────────────────────────────
byoc_acquire_lock() {
  # Usage: byoc_acquire_lock "<cloud>" "<account-ref>"
  local cloud="$1" account="$2"
  local lock_dir="${SPINE_BYOC_STATE_DIR:-${BYOC_REPO_ROOT}/.spine/byoc}"
  mkdir -p "$lock_dir"
  local lock="${lock_dir}/${cloud}.${account//[^a-zA-Z0-9_-]/_}.lock"
  if [[ -e "$lock" ]]; then
    if [[ "${BYOC_FORCE:-0}" == "1" ]]; then
      byoc_warn "lock $lock exists; --force set; continuing."
    else
      byoc_die "lock $lock exists (another provision in flight, or stale). Re-run with --force or remove it."
    fi
  fi
  printf 'pid=%s\nstarted=%s\n' "$$" "$(_byoc_ts)" > "$lock"
  BYOC_LOCK_PATH="$lock"
  trap 'rm -f "$BYOC_LOCK_PATH"' EXIT
}

# ─── delegated-role validation hook ─────────────────────────────────
# Each cloud script implements byoc_validate_credentials() that returns
# 0 if the delegated role assumes successfully and the caller can manage
# the customer account. Returning non-zero aborts before any provisioning.
byoc_assert_credentials() {
  if ! declare -f byoc_validate_credentials >/dev/null 2>&1; then
    byoc_die "cloud script did not define byoc_validate_credentials()"
  fi
  byoc_log "validating delegated-role credentials..."
  if ! byoc_validate_credentials; then
    BYOC_DIE_CODE=3 byoc_die "delegated-role validation failed (per #15: vendor cannot act without customer's scoped role)"
  fi
  byoc_log "credentials OK."
}

# ─── output helpers ─────────────────────────────────────────────────
byoc_emit_handoff() {
  # Print the customer-facing "Hub is up" banner. Pure text; no secrets.
  # Args: HUB_URL ADMIN_EMAIL VAULT_UNSEAL_LOCATION
  local hub_url="$1" admin_email="$2" unseal_loc="$3"
  printf '\n'
  printf '┌──────────────────────────────────────────────────────────────────────────────┐\n'
  printf '│ Spine Hub provisioned in your %-44s │\n' "${SPINE_BYOC_CLOUD:-cloud account}"
  printf '├──────────────────────────────────────────────────────────────────────────────┤\n'
  printf '│ Hub URL:           %-58s │\n' "$hub_url"
  printf '│ Admin email:       %-58s │\n' "$admin_email"
  printf '│ Vault unseal:      %-58s │\n' "$unseal_loc"
  printf '│ Hub container:     spine/hub:%-50s │\n' "${SPINE_HUB_VERSION:-?}"
  printf '│ Bundle id:         %-58s │\n' "${SPINE_BYOC_BUNDLE_ID:-?}"
  printf '└──────────────────────────────────────────────────────────────────────────────┘\n'
  printf '\n'
  printf 'Next steps for the customer:\n'
  printf '  1. Save the vault unseal shares from %s OFFLINE.\n' "$unseal_loc"
  printf '  2. Sign in at %s with your admin email (%s).\n' "$hub_url" "$admin_email"
  printf '  3. Run the Day-0 wizard inside the Hub UI.\n'
  printf '  4. Exit ramp at any time: revoke the delegated role and the Hub keeps\n'
  printf '     running (see tools/byoc/runbooks/<cloud>.md §Exit ramp).\n\n'
}
