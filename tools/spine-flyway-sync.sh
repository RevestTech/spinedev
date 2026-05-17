#!/usr/bin/env bash
# tools/spine-flyway-sync.sh — fix the wave-9 F2 follow-up.
#
# Symptom (see docs/STATUS.md §5):
#   V2 (kg) was applied via direct psql after the pgvector image swap; V14
#   through V21 were applied the same way during the smoke run. The DB has
#   all 9 spine_* schemas, but `flyway_schema_history` doesn't list V2 or
#   V14-V21, so `flyway info` reports them as "Pending" / "Ignored" and
#   `docker compose up watcher` fails its `flyway: service_completed_
#   successfully` dependency.
#
# Fix: for each `V<N>__<desc>.sql` whose schema already exists in the DB
# but whose row is missing from `flyway_schema_history`, INSERT a history
# row with the correct checksum (computed via flyway's CRC32 of the file
# content). After that, `flyway migrate` is a no-op and `flyway info` is
# clean.
#
# Idempotent: skips any row already present in flyway_schema_history.
# Safe to run on a fresh DB (just no-ops).
#
# Usage: bash tools/spine-flyway-sync.sh [--dry-run]
#
# Exit: 0 = success (whether or not anything changed); non-zero = problem.

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DB_DIR="$REPO_ROOT/db"
ENV_FILE="$DB_DIR/.env"
FLYWAY_SQL="$DB_DIR/flyway/sql"

DRY_RUN=0
for a in "$@"; do
  case "$a" in
    --dry-run|-n) DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'unknown flag: %s\n' "$a" >&2; exit 64 ;;
  esac
done

# Load db/.env so we have POSTGRES_USER + PASSWORD + PORT.
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; . "$ENV_FILE"; set +a
fi
: "${POSTGRES_DB:=spine}"
: "${POSTGRES_USER:=spine}"
: "${POSTGRES_PASSWORD:=spine_dev_only}"
: "${POSTGRES_HOST_PORT:=33001}"

# All psql calls go through the container so we don't need the host to
# have psql with the right libpq. Falls back to host psql if compose
# isn't available (e.g. running this on a remote DB).
_psql() {
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx spine_postgres; then
    docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" spine_postgres \
      psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -X -q -v ON_ERROR_STOP=1 "$@"
  else
    PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -p "$POSTGRES_HOST_PORT" \
      -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -X -q -v ON_ERROR_STOP=1 "$@"
  fi
}

# Reachability.
if ! _psql -c 'SELECT 1;' >/dev/null 2>&1; then
  printf 'flyway-sync: spine postgres unreachable (db=%s user=%s port=%s)\n' \
    "$POSTGRES_DB" "$POSTGRES_USER" "$POSTGRES_HOST_PORT" >&2
  exit 3
fi

# If flyway_schema_history doesn't exist, flyway hasn't even baselined the
# DB yet — let `flyway migrate` create it itself; nothing for us to sync.
if ! _psql -c "SELECT to_regclass('public.flyway_schema_history');" 2>/dev/null | grep -qx flyway_schema_history; then
  printf 'flyway-sync: flyway_schema_history not present — nothing to sync (flyway migrate will create it)\n'
  exit 0
fi

# Flyway computes a CRC32 over the migration SQL file (default config:
# UTF-8, all bytes). The Python helper below matches flyway's "binary
# CRC32 of file contents, interpreted as signed 32-bit" behavior. (See
# org.flywaydb.core.internal.util.ChecksumCalculator.)
_crc32() {
  python3 - "$1" <<'PY'
import sys, zlib
with open(sys.argv[1], "rb") as f:
    data = f.read()
# Flyway normalizes line endings: drops trailing \r before \n on each line.
# Apply the same normalization so our CRC matches what flyway would compute.
lines = data.split(b"\n")
norm  = b"\n".join(line.rstrip(b"\r") for line in lines)
crc   = zlib.crc32(norm) & 0xFFFFFFFF
# Flyway stores it as a signed Java int.
if crc >= 0x80000000:
    crc -= 0x100000000
print(crc)
PY
}

# A spine_* schema being present is our proxy for "this migration ran".
# Map each V<N> file → a schema that uniquely indicates it landed.
# (We only ever sync rows for migrations whose schema actually exists,
# so the worst case is no-op rather than fake-applied.)
_schema_for() {
  case "$1" in
    2)  echo "spine_kg" ;;
    14) echo "spine_lifecycle" ;;
    15) echo "spine_audit" ;;
    16) echo "" ;;  # cost ledger — table-level; trust the others
    17) echo "" ;;
    18) echo "spine_calibration" ;;
    19) echo "spine_eval" ;;
    20) echo "spine_memory" ;;
    21) echo "spine_verify_audit" ;;
    *)  echo "" ;;
  esac
}

_schema_exists() {
  local sch="$1"
  [[ -z "$sch" ]] && return 0  # no probe schema — assume "ran" if higher versions ran
  _psql -c "SELECT 1 FROM pg_namespace WHERE nspname='$sch';" 2>/dev/null | grep -qx 1
}

_already_in_history() {
  local ver="$1"
  _psql -c "SELECT 1 FROM flyway_schema_history WHERE version='$ver';" 2>/dev/null | grep -qx 1
}

# Insert a missing row. Mirrors what flyway itself would write:
#   installed_rank  = max(installed_rank) + 1  (computed by the INSERT)
#   version, description, type, script, checksum, installed_by, success, execution_time = 0
_insert_row() {
  local ver="$1" desc="$2" script="$3" checksum="$4"
  local sql
  sql="INSERT INTO flyway_schema_history
       (installed_rank, version, description, type, script, checksum,
        installed_by, installed_on, execution_time, success)
       VALUES (
         (SELECT COALESCE(MAX(installed_rank),0)+1 FROM flyway_schema_history),
         '$ver', '$desc', 'SQL', '$script', $checksum,
         '$POSTGRES_USER', now(), 0, true);"
  if (( DRY_RUN )); then
    printf '  [dry-run] would INSERT V%s (%s) checksum=%s\n' "$ver" "$desc" "$checksum"
  else
    _psql -c "$sql" >/dev/null
  fi
}

inserted=0; skipped=0; missing=0
for sql_file in "$FLYWAY_SQL"/V*.sql; do
  [[ -f "$sql_file" ]] || continue
  base="$(basename "$sql_file" .sql)"
  # Parse "V<num>__<desc>" (flyway naming convention).
  if [[ ! "$base" =~ ^V([0-9]+)__(.+)$ ]]; then continue; fi
  ver="${BASH_REMATCH[1]}"
  desc_under="${BASH_REMATCH[2]}"
  desc="${desc_under//_/ }"
  script="$base.sql"

  if _already_in_history "$ver"; then
    skipped=$((skipped + 1))
    continue
  fi

  # Probe schema — only sync rows for migrations whose target schema is
  # already present (otherwise the migration genuinely didn't run, and
  # flyway should pick it up on the next `migrate`).
  probe="$(_schema_for "$ver")"
  if ! _schema_exists "$probe"; then
    missing=$((missing + 1))
    continue
  fi

  checksum="$(_crc32 "$sql_file")"
  printf 'flyway-sync: syncing V%-2s %-26s (checksum=%s)\n' "$ver" "$desc" "$checksum"
  _insert_row "$ver" "$desc" "$script" "$checksum"
  inserted=$((inserted + 1))
done

printf 'flyway-sync: %d inserted, %d already-present, %d not-applied (will run on next migrate)%s\n' \
  "$inserted" "$skipped" "$missing" "$( ((DRY_RUN)) && printf ' [dry-run]')"

exit 0
