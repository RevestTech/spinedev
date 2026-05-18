#!/usr/bin/env bash
# run-standalone-watcher.sh — Pass N (v3 vault-only). Run
# db/watcher/spine_watcher.py outside Docker, pointing at a remote
# Postgres hub. The watcher reads this machine's local outbox files
# and writes to the shared hub.
#
# Per v3 design decision #9 (vault-only secrets, no exceptions), this
# script does NOT accept a pre-built DSN from the environment. It
# assembles the DSN at runtime by combining non-secret connection
# parameters (POSTGRES_USER / POSTGRES_HOST / POSTGRES_HOST_PORT /
# POSTGRES_DB — env or share-pg.sh paste-block) with the password
# fetched from the vault via shared.secrets.cli.
#
# Required env (non-secret):
#   POSTGRES_HOST       (or PGHOST)
#   POSTGRES_HOST_PORT  (or PGPORT)
#   POSTGRES_USER       (or PGUSER, default 'spine')
#   POSTGRES_DB         (or PGDATABASE, default 'spine')
# Vault:
#   spine/postgres/password   — fetched at runtime; never echoed.
#
# Optional env: POLL_INTERVAL_S (default 5), LOG_LEVEL (default INFO),
#               SPINE_TENANT (default 'default'), TEAM_BASE (default
#               $REPO/.planning/orchestration/agent-handoff/teams),
#               SPINE_PG_PASSWORD_VAULT_PATH (override vault key).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

# Resolve non-secret connection parameters from env aliases.
PGHOST="${POSTGRES_HOST:-${PGHOST:-}}"
PGPORT="${POSTGRES_HOST_PORT:-${PGPORT:-}}"
PGUSER="${POSTGRES_USER:-${PGUSER:-spine}}"
PGDATABASE="${POSTGRES_DB:-${PGDATABASE:-spine}}"

if [[ -z "$PGHOST" || -z "$PGPORT" ]]; then
  echo "FATAL: POSTGRES_HOST and POSTGRES_HOST_PORT must be set (paste from share-pg.sh)." >&2
  exit 2
fi

# Fetch password from vault. Never echo. Never write to disk.
VAULT_PATH="${SPINE_PG_PASSWORD_VAULT_PATH:-spine/postgres/password}"
if ! command -v python3 >/dev/null 2>&1; then
  echo "FATAL: python3 not on PATH — required for vault read." >&2
  exit 2
fi

# Run the secret fetch with xtrace explicitly disabled so a caller-set
# `set -x` doesn't leak the password into logs.
{
  _xtrace_was_on=0
  case "$-" in *x*) _xtrace_was_on=1 ;; esac
  set +x
} 2>/dev/null

PGPASSWORD="$(python3 -m shared.secrets.cli get "$VAULT_PATH" 2>/dev/null)" \
  || PGPASSWORD=""

if [[ -z "$PGPASSWORD" ]]; then
  if [[ "$_xtrace_was_on" -eq 1 ]]; then set -x; fi
  unset _xtrace_was_on
  echo "FATAL: vault read of '$VAULT_PATH' failed — run the Spine vault wizard." >&2
  exit 4
fi

# Assemble the DSN. Done with xtrace OFF and never logged.
DATABASE_URL="postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${PGDATABASE}"
export PGPASSWORD DATABASE_URL

# Re-enable xtrace ONLY after the secret-bearing line is past.
if [[ "$_xtrace_was_on" -eq 1 ]]; then set -x; fi
unset _xtrace_was_on

export TEAM_BASE="${TEAM_BASE:-$REPO/.planning/orchestration/agent-handoff/teams}"
export POLL_INTERVAL_S="${POLL_INTERVAL_S:-5}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export SPINE_TENANT="${SPINE_TENANT:-default}"

# Cursors live next to the outbox files for the standalone case (the
# watcher's default fallback when CURSOR_BASE is unset).
unset CURSOR_BASE

WATCHER_PY="$REPO/db/watcher/spine_watcher.py"
if [[ ! -f "$WATCHER_PY" ]]; then
  echo "FATAL: $WATCHER_PY not found." >&2
  exit 3
fi

exec python3 "$WATCHER_PY"
