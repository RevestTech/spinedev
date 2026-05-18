#!/usr/bin/env bash
# spine-connect.sh — Pass N (v3 vault-only). One-command bootstrap on
# Machine B that joins this workspace to a remote Spine hub.
#
# Per v3 design decision #9 (vault-only secrets, no exceptions), this
# script does NOT accept a raw DSN containing a plaintext password from
# argv or env. It assembles the DSN at runtime from:
#   - non-secret connection parameters paste-blocked from share-pg.sh
#     (POSTGRES_HOST / POSTGRES_HOST_PORT / POSTGRES_USER / POSTGRES_DB)
#     OR a parameter-only entry in .planning/orchestration/.hub-url (see
#     format below)
#   - the password fetched from the Spine vault at
#     spine/postgres/password (override with SPINE_PG_PASSWORD_VAULT_PATH)
#
# Usage:
#   bash scripts/spine-connect.sh
#
# .hub-url format (per-line, NO secret):
#   POSTGRES_HOST=10.0.0.5
#   POSTGRES_HOST_PORT=33001
#   POSTGRES_USER=spine
#   POSTGRES_DB=spine
#
# Behavior:
#   1. Verify required tools (python3, git, bash).
#   2. Resolve non-secret POSTGRES_* parameters from env or .hub-url.
#   3. Fetch DB password from vault (NEVER from env / .env).
#   4. Verify the DB connection works (auto-install psycopg if missing).
#   5. Ensure the team scaffold exists.
#   6. Start a standalone watcher reading the local outbox files
#      (PID file is the lock so re-running is idempotent).
#   7. Run `bash scripts/team.sh up` so this machine appears as a
#      separate instance against the shared Postgres.
#
# Companion: scripts/spine-disconnect.sh stops both halves.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

if [[ -t 1 ]]; then
  C_BLUE='\033[0;34m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'
  C_RED='\033[0;31m'; C_DIM='\033[2m'; C_RESET='\033[0m'
else
  C_BLUE=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_DIM=''; C_RESET=''
fi
step() { printf "${C_BLUE}>${C_RESET} %s\n" "$*"; }
ok()   { printf "${C_GREEN}OK${C_RESET}  %s\n" "$*"; }
warn() { printf "${C_YELLOW}!${C_RESET}  %s\n" "$*"; }
err()  { printf "${C_RED}x${C_RESET}  %s\n" "$*" >&2; }
dim()  { printf "${C_DIM}%s${C_RESET}\n" "$*"; }

HANDOFF=".planning/orchestration/agent-handoff"
WATCHER_PID_FILE="$HANDOFF/.watcher.pid"
WATCHER_LOG_FILE="$HANDOFF/watcher.log"
HUB_URL_FILE=".planning/orchestration/.hub-url"
TEAMS_DIR="$HANDOFF/teams"

# ---------------------------------------------------------------------
# 1. Tool checks.
# ---------------------------------------------------------------------
step "Checking required tools"
missing=0
for bin in python3 git bash; do
  if command -v "$bin" >/dev/null 2>&1; then
    ok "$bin: $(command -v "$bin")"
  else
    warn "$bin not on PATH — Spine may not function correctly."
    missing=$((missing + 1))
  fi
done
# bash >= 4 is preferred but not strictly required; macOS ships 3.2.
bash_major="$(bash -c 'echo "${BASH_VERSINFO[0]}"' 2>/dev/null || echo 3)"
if (( bash_major < 4 )); then
  warn "bash $bash_major detected — bash >= 4 recommended (you'll be fine for the default flow)."
fi
echo

# ---------------------------------------------------------------------
# 2. Resolve NON-SECRET connection parameters.
# ---------------------------------------------------------------------
# Refuse any pre-set SPINE_DB_URL that came in via env — secret values
# must originate from vault, not from caller env.
if [[ -n "${SPINE_DB_URL:-}" ]]; then
  warn "Ignoring inbound SPINE_DB_URL — v3 requires the password to come from vault."
  unset SPINE_DB_URL
fi

# Parse the .hub-url file for the non-secret params if env doesn't already
# carry them. We accept ONLY KEY=VALUE lines for the recognised non-secret
# keys; anything else is ignored.
if [[ -f "$HUB_URL_FILE" ]]; then
  while IFS='=' read -r key val; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    val="${val%$'\r'}"
    val="${val%\"}"; val="${val#\"}"
    val="${val%\'}"; val="${val#\'}"
    case "$key" in
      POSTGRES_HOST)      : "${POSTGRES_HOST:=$val}" ;;
      POSTGRES_HOST_PORT) : "${POSTGRES_HOST_PORT:=$val}" ;;
      POSTGRES_USER)      : "${POSTGRES_USER:=$val}" ;;
      POSTGRES_DB)        : "${POSTGRES_DB:=$val}" ;;
      # Anything else (including any POSTGRES_PASSWORD line written by an
      # older share-pg.sh) is intentionally ignored.
    esac
  done < "$HUB_URL_FILE"
fi

HUB_HOST="${POSTGRES_HOST:-${PGHOST:-}}"
HUB_PORT="${POSTGRES_HOST_PORT:-${PGPORT:-}}"
HUB_USER="${POSTGRES_USER:-${PGUSER:-spine}}"
HUB_DB="${POSTGRES_DB:-${PGDATABASE:-spine}}"

if [[ -z "$HUB_HOST" || -z "$HUB_PORT" ]]; then
  err "Hub host/port not configured."
  err "  Paste the export block from Machine A's \`make -C db share-pg\`, then re-run."
  err "  OR write POSTGRES_HOST=, POSTGRES_HOST_PORT=, POSTGRES_USER=, POSTGRES_DB= lines into:"
  err "    $HUB_URL_FILE"
  exit 2
fi

# ---------------------------------------------------------------------
# 3. Fetch DB password from vault (NEVER from env / .env).
# ---------------------------------------------------------------------
VAULT_PATH="${SPINE_PG_PASSWORD_VAULT_PATH:-spine/postgres/password}"
step "Fetching DB password from vault: $VAULT_PATH"

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
  err "vault read of '$VAULT_PATH' failed."
  err "  Run the Spine Day-0 vault wizard on this machine (or set SPINE_PG_PASSWORD_VAULT_PATH)."
  exit 4
fi

# Assemble the DSN with xtrace OFF. Never echo $SPINE_DB_URL.
SPINE_DB_URL="postgresql://${HUB_USER}:${PGPASSWORD}@${HUB_HOST}:${HUB_PORT}/${HUB_DB}"
export PGPASSWORD SPINE_DB_URL

if [[ "$_xtrace_was_on" -eq 1 ]]; then set -x; fi
unset _xtrace_was_on
ok "Vault returned password; DSN assembled in memory."
echo

# ---------------------------------------------------------------------
# 4. DB connectivity test. Auto-installs psycopg[binary] on first miss.
# ---------------------------------------------------------------------
step "Testing connection to hub Postgres at $HUB_HOST:$HUB_PORT"
if ! command -v python3 >/dev/null 2>&1; then
  err "python3 not on PATH — cannot test DB connection."
  exit 3
fi

# Try once. If psycopg is missing, install and retry.
test_psycopg_connect() {
  SPINE_DB_URL="$SPINE_DB_URL" python3 - <<'PY' 2>&1
import os, sys
try:
    import psycopg
except ImportError:
    sys.stdout.write("MISSING_PSYCOPG\n")
    sys.exit(0)
try:
    conn = psycopg.connect(os.environ["SPINE_DB_URL"], connect_timeout=5)
    conn.close()
except Exception as e:
    sys.stdout.write("CONNECT_ERROR: %s\n" % e)
    sys.exit(1)
sys.stdout.write("OK\n")
PY
}

attempt=1
while :; do
  out="$(test_psycopg_connect)"
  rc=$?
  case "$out" in
    OK*)
      ok "Connected to hub successfully."
      break
      ;;
    MISSING_PSYCOPG*)
      if (( attempt > 1 )); then
        err "psycopg still missing after install attempt — giving up."
        exit 4
      fi
      step "psycopg not installed — installing 'psycopg[binary]' (one-time)"
      if pip3 install --break-system-packages -q 'psycopg[binary]' 2>/dev/null \
         || pip3 install -q 'psycopg[binary]' 2>/dev/null \
         || python3 -m pip install --break-system-packages -q 'psycopg[binary]' 2>/dev/null \
         || python3 -m pip install -q 'psycopg[binary]' 2>/dev/null; then
        ok "psycopg installed."
      else
        err "Could not install psycopg automatically. Run: pip3 install 'psycopg[binary]'"
        exit 4
      fi
      attempt=$((attempt + 1))
      continue
      ;;
    CONNECT_ERROR*)
      # NOTE: deliberately does NOT echo SPINE_DB_URL — would leak password.
      err "Could not connect to hub at $HUB_HOST:$HUB_PORT (DSN redacted)."
      err "  $out"
      echo >&2
      err "Diagnostic checklist:"
      err "  - Is Machine A's POSTGRES_BIND_HOST=0.0.0.0 in db/.env?"
      err "    After changing it, run on Machine A: make -C db down && make -C db up"
      err "  - Is the hub reachable at TCP layer?  nc -zv $HUB_HOST $HUB_PORT"
      err "  - Is Machine A's firewall allowing inbound on $HUB_PORT?"
      err "  - Are the vault credentials current on this machine?"
      exit 5
      ;;
    *)
      err "Unexpected connection test output: $out (rc=$rc)"
      exit 6
      ;;
  esac
done
echo

# ---------------------------------------------------------------------
# 5. Pre-flight ENSURE_SCAFFOLD.
# ---------------------------------------------------------------------
step "Verifying team scaffold"
if [[ ! -d "$TEAMS_DIR" ]]; then
  warn "No team scaffold at $TEAMS_DIR — creating minimal directories."
  # Use roles.sh to scaffold each role's working tree. Don't fail here —
  # team.sh up's ensure_scaffold() will also fill in the gaps.
  mkdir -p "$TEAMS_DIR"
  if [[ -f "$SCRIPT_DIR/roles.sh" ]]; then
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/roles.sh"
    for r in "${SPINE_TEAM_ROLES[@]}"; do
      mkdir -p "$TEAMS_DIR/$r/workers/archive" "$TEAMS_DIR/$r/state" "$TEAMS_DIR/$r/log"
    done
  fi
  warn "If this is a fresh checkout, also run: bash install.sh ."
fi
ok "Team scaffold at $TEAMS_DIR"
echo

# ---------------------------------------------------------------------
# 6. Required env vars (HOST_ID, TENANT).
# ---------------------------------------------------------------------
export SPINE_TENANT="${SPINE_TENANT:-default}"
export SPINE_HOST_ID="${SPINE_HOST_ID:-$(hostname 2>/dev/null || echo local)}"
dim "  SPINE_TENANT=$SPINE_TENANT"
dim "  SPINE_HOST_ID=$SPINE_HOST_ID"
echo

# ---------------------------------------------------------------------
# 7. Start the standalone watcher (idempotent via PID file).
# ---------------------------------------------------------------------
mkdir -p "$(dirname "$WATCHER_PID_FILE")"
WATCHER_SCRIPT=""
for cand in "$SCRIPT_DIR/run-standalone-watcher.sh" "scripts/run-standalone-watcher.sh" "lib/run-standalone-watcher.sh"; do
  if [[ -f "$cand" ]]; then WATCHER_SCRIPT="$cand"; break; fi
done

step "Starting standalone watcher"
existing_watcher_pid=""
if [[ -f "$WATCHER_PID_FILE" ]]; then
  pid="$(cat "$WATCHER_PID_FILE" 2>/dev/null | tr -d '[:space:]')"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    existing_watcher_pid="$pid"
  else
    rm -f "$WATCHER_PID_FILE"
  fi
fi

if [[ -n "$existing_watcher_pid" ]]; then
  ok "Watcher already running (pid $existing_watcher_pid). Logs: $WATCHER_LOG_FILE"
elif [[ -z "$WATCHER_SCRIPT" ]]; then
  err "Cannot find run-standalone-watcher.sh in scripts/ or lib/ — re-run installer."
  exit 7
else
  : > "$WATCHER_LOG_FILE"
  # Pass non-secret params to the watcher; watcher re-fetches the password
  # from vault itself (each process owns its secret lifetime).
  POSTGRES_HOST="$HUB_HOST" POSTGRES_HOST_PORT="$HUB_PORT" \
    POSTGRES_USER="$HUB_USER" POSTGRES_DB="$HUB_DB" \
    SPINE_TENANT="$SPINE_TENANT" \
    nohup bash "$WATCHER_SCRIPT" >>"$WATCHER_LOG_FILE" 2>&1 &
  watcher_pid=$!
  disown 2>/dev/null || true
  echo "$watcher_pid" > "$WATCHER_PID_FILE"
  sleep 1
  if kill -0 "$watcher_pid" 2>/dev/null; then
    ok "Watcher started (pid $watcher_pid). Logs: $WATCHER_LOG_FILE"
  else
    err "Watcher exited immediately. Last log lines:"
    tail -n 20 "$WATCHER_LOG_FILE" >&2 || true
    rm -f "$WATCHER_PID_FILE"
    exit 8
  fi
fi
echo

# ---------------------------------------------------------------------
# 8. Start the daemons (team.sh up inherits SPINE_DB_URL etc).
# ---------------------------------------------------------------------
step "Starting Spine daemons (team.sh up)"
TEAM_SH=""
for cand in "$SCRIPT_DIR/team.sh" "scripts/team.sh"; do
  if [[ -f "$cand" ]]; then TEAM_SH="$cand"; break; fi
done
if [[ -z "$TEAM_SH" ]]; then
  err "Cannot find team.sh — re-run installer."
  exit 9
fi
bash "$TEAM_SH" up || warn "team.sh up reported issues — see output above."
echo

# ---------------------------------------------------------------------
# Done.
# ---------------------------------------------------------------------
watcher_pid_now="$(cat "$WATCHER_PID_FILE" 2>/dev/null || echo '?')"
printf "${C_GREEN}Connected to hub at %s:%s.${C_RESET} Watcher pid=%s. Daemons up.\n" \
  "$HUB_HOST" "$HUB_PORT" "$watcher_pid_now"
dim "  Refresh the hub dashboard to see this machine appear in the Fleet card."
dim "  To stop later:  bash scripts/spine-disconnect.sh"
exit 0
