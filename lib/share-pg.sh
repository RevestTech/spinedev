#!/usr/bin/env bash
# share-pg.sh — Pass N (v3 vault-only). Print a ready-to-paste env block
# that lets a second machine connect to this hub's Postgres and join the
# fleet — WITHOUT exposing the DB password in the printed block.
#
# Per v3 design decision #9 (vault-only secrets, no exceptions), this
# script no longer reads or prints POSTGRES_PASSWORD. The remote machine
# fetches the password from the same vault Spine itself is bound to. The
# pasted env block on Machine B carries only the non-secret connection
# parameters; the password is resolved on Machine B via
# `python3 -m shared.secrets.cli get spine/postgres/password`.
#
# What it does:
#   1. Reads db/.env for NON-SECRET keys (POSTGRES_USER, POSTGRES_DB,
#      POSTGRES_HOST_PORT, POSTGRES_BIND_HOST). Any POSTGRES_PASSWORD line
#      is ignored.
#   2. Detects the host's LAN IP using ipconfig getifaddr en0 (macOS),
#      hostname -I (Linux), or `ip route get 1` parsing as a fallback.
#   3. Warns when POSTGRES_BIND_HOST is still 127.0.0.1 (i.e. Postgres
#      can't be reached from the LAN).
#   4. Verifies the local Postgres is up (pg_isready / nc).
#   5. Prints the copy-paste env block (no secret) + a connectivity test
#      command Machine B can run after fetching the password from vault.
#
# Invoked by `make -C db share-pg`. Safe to run from anywhere; resolves
# the repo root relative to its own path.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# This file lives at either lib/share-pg.sh or scripts/share-pg.sh —
# both are one level below the repo root.
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/db/.env"

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

# Allow tests to override which .env we read.
if [[ -n "${SPINE_SHARE_PG_ENV:-}" ]]; then
  ENV_FILE="$SPINE_SHARE_PG_ENV"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  err "Missing $ENV_FILE — copy db/.env.example to db/.env first."
  exit 2
fi

POSTGRES_USER=""
POSTGRES_DB=""
POSTGRES_HOST_PORT=""
POSTGRES_BIND_HOST=""

# Parse a minimal subset of db/.env. Tolerates surrounding quotes and
# blank/comment lines but does not source the file (no command exec).
# POSTGRES_PASSWORD is intentionally NOT read — secrets live in vault.
while IFS='=' read -r key val; do
  [[ -z "$key" || "$key" == \#* ]] && continue
  val="${val%$'\r'}"
  val="${val%\"}"; val="${val#\"}"
  val="${val%\'}"; val="${val#\'}"
  case "$key" in
    POSTGRES_USER)      POSTGRES_USER="$val" ;;
    POSTGRES_DB)        POSTGRES_DB="$val" ;;
    POSTGRES_HOST_PORT) POSTGRES_HOST_PORT="$val" ;;
    POSTGRES_BIND_HOST) POSTGRES_BIND_HOST="$val" ;;
  esac
done < "$ENV_FILE"

: "${POSTGRES_USER:=spine}"
: "${POSTGRES_DB:=spine}"
: "${POSTGRES_HOST_PORT:=33000}"
: "${POSTGRES_BIND_HOST:=127.0.0.1}"

# ---------------------------------------------------------------------
# Detect the host's primary LAN IPv4.
# ---------------------------------------------------------------------
detect_lan_ip() {
  local ip=""
  # macOS: ipconfig getifaddr <iface>. Try common interface names in order.
  if command -v ipconfig >/dev/null 2>&1; then
    for iface in en0 en1 en2 en3 en4 en5; do
      ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
      if [[ -n "$ip" ]]; then
        printf '%s' "$ip"
        return 0
      fi
    done
  fi
  # Linux: hostname -I returns space-separated IPs.
  if command -v hostname >/dev/null 2>&1; then
    ip="$(hostname -I 2>/dev/null | awk '{for(i=1;i<=NF;i++){if($i!="127.0.0.1" && $i!~/^::/){print $i; exit}}}')"
    if [[ -n "$ip" ]]; then
      printf '%s' "$ip"
      return 0
    fi
  fi
  # Linux: ip route get 1 — emits "1.0.0.0 via X src LAN_IP ..."
  if command -v ip >/dev/null 2>&1; then
    ip="$(ip route get 1 2>/dev/null | awk '{for(i=1;i<=NF;i++){if($i=="src"){print $(i+1); exit}}}')"
    if [[ -n "$ip" ]]; then
      printf '%s' "$ip"
      return 0
    fi
  fi
  # Last resort: parse `ifconfig` output. Pick the first non-loopback IPv4.
  if command -v ifconfig >/dev/null 2>&1; then
    ip="$(ifconfig 2>/dev/null | awk '/inet / && $2 !~ /^127\./ && $2 !~ /^169\.254\./ {print $2; exit}')"
    if [[ -n "$ip" ]]; then
      printf '%s' "$ip"
      return 0
    fi
  fi
  return 1
}

LAN_IP="$(detect_lan_ip || true)"
if [[ -z "$LAN_IP" ]]; then
  LAN_IP="<your-lan-ip>"
fi

# ---------------------------------------------------------------------
# Verify the local Postgres is up. Tries pg_isready first, falls back
# to nc, then to a tcp probe via /dev/tcp (bash builtin) so we have at
# least one path that works on a barebones host.
# ---------------------------------------------------------------------
step "Checking local Postgres on 127.0.0.1:$POSTGRES_HOST_PORT"
if command -v pg_isready >/dev/null 2>&1; then
  if pg_isready -h 127.0.0.1 -p "$POSTGRES_HOST_PORT" -q -t 2 2>/dev/null; then
    ok "Postgres reachable on 127.0.0.1:$POSTGRES_HOST_PORT"
  else
    warn "pg_isready says Postgres is NOT reachable on 127.0.0.1:$POSTGRES_HOST_PORT — is it running? Try: make -C db up"
  fi
elif command -v nc >/dev/null 2>&1; then
  if nc -z 127.0.0.1 "$POSTGRES_HOST_PORT" 2>/dev/null; then
    ok "Port 127.0.0.1:$POSTGRES_HOST_PORT is open (nc)"
  else
    warn "Port 127.0.0.1:$POSTGRES_HOST_PORT is not accepting connections — is Postgres running? Try: make -C db up"
  fi
else
  # /dev/tcp is a bash builtin pseudo-device; works without nc.
  if (exec 3<>"/dev/tcp/127.0.0.1/$POSTGRES_HOST_PORT") 2>/dev/null; then
    exec 3>&- 3<&- 2>/dev/null || true
    ok "Port 127.0.0.1:$POSTGRES_HOST_PORT is open (/dev/tcp)"
  else
    warn "Port 127.0.0.1:$POSTGRES_HOST_PORT not reachable (no pg_isready/nc/tcp) — verify Postgres is up."
  fi
fi
echo

# ---------------------------------------------------------------------
# Bind-host warning. The user has to set 0.0.0.0 in db/.env or the
# remote machine cannot reach Postgres regardless of what's printed.
# ---------------------------------------------------------------------
if [[ "$POSTGRES_BIND_HOST" != "0.0.0.0" && "$POSTGRES_BIND_HOST" != "$LAN_IP" ]]; then
  warn "Postgres is bound to $POSTGRES_BIND_HOST — other machines can't reach it."
  dim  "  Edit db/.env: set POSTGRES_BIND_HOST=0.0.0.0, then:"
  dim  "    make -C db down && make -C db up"
  echo
fi

# ---------------------------------------------------------------------
# Emit the hub URL + paste-ready env block (NO password — vault-only).
# ---------------------------------------------------------------------
SPINE_DB_URL_MASKED="postgresql://${POSTGRES_USER}:<from-vault>@${LAN_IP}:${POSTGRES_HOST_PORT}/${POSTGRES_DB}"

printf 'Hub LAN IP:       %s\n' "$LAN_IP"
printf 'Hub Postgres URL: %s\n' "$SPINE_DB_URL_MASKED"
echo

ok "The block below carries NO secret. Machine B fetches the DB password from the vault."
dim "  Vault path (canonical): spine/postgres/password"
dim "  Machine B must be enrolled with the same Spine vault before connecting."
echo

cat <<EOF
# Paste this on Machine B, then run: bash scripts/spine-connect.sh
export POSTGRES_USER="$POSTGRES_USER"
export POSTGRES_HOST_PORT="$POSTGRES_HOST_PORT"
export POSTGRES_DB="$POSTGRES_DB"
export POSTGRES_HOST="$LAN_IP"
export SPINE_TENANT="default"
export SPINE_HOST_ID="\$(hostname)"
# Note: no SPINE_DB_URL export — spine-connect.sh assembles it after fetching
# the password from vault via: python3 -m shared.secrets.cli get spine/postgres/password
EOF
echo

step "Test connectivity from Machine B (run one of these on Machine B):"
# shellcheck disable=SC2016  # literal text showing the env var names
printf '  PGPASSWORD="$(python3 -m shared.secrets.cli get spine/postgres/password)" \\\n'
printf '    psql -h %s -p %s -U %s -d %s -c "SELECT 1;"\n' \
  "$LAN_IP" "$POSTGRES_HOST_PORT" "$POSTGRES_USER" "$POSTGRES_DB"
printf '  nc -zv %s %s\n' "$LAN_IP" "$POSTGRES_HOST_PORT"
echo
dim "  Then on Machine B: bash scripts/spine-connect.sh"

exit 0
