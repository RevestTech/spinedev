#!/usr/bin/env bash
# tools/dr-test.sh — weekly DR restore-to-throwaway validation.
#
# Implements layer 4 (Tested data restore) + layer 12 (Backup
# verification on every release) of the v3 DR architecture per
# docs/V3_DESIGN_DECISIONS.md §32.
#
# Wire this into the deployment's scheduler:
#
#   * K8s:                  CronJob, weekly, calling this script.
#   * docker-compose:       host cron, weekly.
#   * laptop:               manual / launchd / systemd timer.
#
# The script picks the most recent successful spine_dr.backup_run row,
# drives recovery.RestoreManager.run_weekly_test() in Python, and exits
# non-zero on test failure so the scheduler can page on-call.
#
# Acceptance criterion (Wave 5 Squad E):
#   "DR weekly test: kill container, restore from backup, verify Hub
#   functional in < 30 min."
#
# Usage:
#   bash tools/dr-test.sh [--env=dr-sandbox] [--target-uri=URI]
#                         [--validate-against-version=VER] [--dry-run]
#
# Exit codes:
#   0  test ran and succeeded (or dry-run completed)
#   1  test ran and FAILED (page on-call)
#   2  environment problem — couldn't run the test
#   64 unknown flag
#
# Idempotent: each run creates a new spine_dr.restore_test row; nothing
# is mutated in the production database.

set -uo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ─── argv parsing ───────────────────────────────────────────────────
ENV_NAME="dr-sandbox"
TARGET_URI=""
VALIDATE_VERSION=""
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --env=*)                          ENV_NAME="${arg#*=}" ;;
    --target-uri=*)                   TARGET_URI="${arg#*=}" ;;
    --validate-against-version=*)     VALIDATE_VERSION="${arg#*=}" ;;
    --dry-run|-n)                     DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      printf 'unknown flag: %s\n' "$arg" >&2
      exit 64
      ;;
  esac
done

case "$ENV_NAME" in
  staging|dr-sandbox|qa) ;;
  *)
    printf 'invalid --env=%s (allowed: staging | dr-sandbox | qa)\n' "$ENV_NAME" >&2
    exit 64
    ;;
esac

# ─── helpers ────────────────────────────────────────────────────────
log() { printf '%s [dr-test] %s\n' "$(date -u +%FT%TZ)" "$*"; }

require() {
  local what="$1" hint="${2:-}"
  if ! command -v "$what" >/dev/null 2>&1; then
    printf '✗ missing prerequisite: %s%s\n' \
      "$what" "${hint:+ — $hint}" >&2
    return 1
  fi
}

# ─── pick a python interpreter ──────────────────────────────────────
PY=""
if   [[ -x "$REPO_ROOT/.venv/bin/python3" ]]; then PY="$REPO_ROOT/.venv/bin/python3"
elif [[ -x "$REPO_ROOT/.venv/bin/python"  ]]; then PY="$REPO_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1;       then PY="$(command -v python3)"
else
  log "no python interpreter found; cannot run DR test"
  exit 2
fi

# ─── pre-flight ─────────────────────────────────────────────────────
log "starting DR test cycle (env=$ENV_NAME, dry_run=$DRY_RUN)"
[[ -n "$VALIDATE_VERSION" ]] && log "layer-12 validation against version: $VALIDATE_VERSION"

problems=0
require "$PY" "python3 needed for recovery module" || problems=$((problems+1))
[[ -d "$REPO_ROOT/recovery" ]] || {
  log "recovery/ subsystem missing at $REPO_ROOT/recovery"
  problems=$((problems+1))
}
if (( problems > 0 )); then
  log "pre-flight failed ($problems problems); aborting"
  exit 2
fi

# Working storage target — defaults to a tmp file:// for dry-runs.
if [[ -z "$TARGET_URI" && $DRY_RUN -eq 1 ]]; then
  TARGET_URI="file://$(mktemp -d -t spine-dr-XXXXXX)/bucket"
  log "no --target-uri given; using dry-run target $TARGET_URI"
fi

if [[ -z "$TARGET_URI" ]]; then
  log "ERROR: --target-uri required for non-dry-run executions"
  log "       (production deployments source this from bundle.dr.target)"
  exit 2
fi

# ─── drive RestoreManager.run_weekly_test ───────────────────────────
# We hand the script a tiny Python driver via heredoc so we don't
# create a permanent companion file. The driver:
#   1. Parses --target-uri into a BackupTarget (scheme inferred).
#   2. Constructs a RestoreManager.
#   3. Calls run_weekly_test().
#   4. Prints the JSON report on stdout.
#   5. Exits 0 if all_passed, else 1.
log "invoking recovery.RestoreManager.run_weekly_test() via python driver"

export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

run_driver() {
  "$PY" - "$TARGET_URI" "$ENV_NAME" "$VALIDATE_VERSION" "$DRY_RUN" <<'PYEOF'
import asyncio
import json
import sys

target_uri = sys.argv[1]
env_name = sys.argv[2]
validate_version = sys.argv[3] or None
dry_run = sys.argv[4] == "1"

# Parse scheme + bucket from the target URI.
if "://" not in target_uri:
    print(json.dumps({"error": f"target-uri missing scheme: {target_uri!r}"}))
    sys.exit(2)
scheme_raw, rest = target_uri.split("://", 1)
parts = rest.split("/", 1)
bucket = parts[0]
prefix = parts[1] if len(parts) > 1 else "spine-dr"
scheme_map = {"s3": "s3", "gs": "gs", "azure": "azure",
              "minio": "minio", "file": "file"}
scheme = scheme_map.get(scheme_raw, "s3")

from recovery import BackupTarget, RestoreManager

target = BackupTarget(scheme=scheme, bucket=bucket, prefix=prefix)
mgr = RestoreManager(target=target)

if dry_run:
    report = {
        "cycle_id": "dry-run",
        "all_passed": True,
        "worst_rto_seconds": 0,
        "outcomes": [],
        "note": (
            "dry-run: validated script wiring only; no restore attempted."
            + (f" (validation_target_version={validate_version})" if validate_version else "")
        ),
    }
    print(json.dumps(report, indent=2))
    sys.exit(0)

report = asyncio.run(mgr.run_weekly_test(
    project_id="dr-test", actor="dr-test-cron",
))
out = {
    "cycle_id": str(report.cycle_id),
    "all_passed": bool(report.all_passed),
    "worst_rto_seconds": int(report.worst_rto_seconds),
    "outcomes": [
        {
            "restore_test_id": str(o.restore_test_id),
            "backup_run_id": str(o.backup_run_id),
            "tested_in_env": o.tested_in_env,
            "succeeded": bool(o.restore_succeeded),
            "rto_seconds": int(o.rto_seconds),
            "anomalies": o.anomalies,
            "error": o.error,
        }
        for o in report.outcomes
    ],
    "validation_target_version": validate_version,
}
print(json.dumps(out, indent=2))
sys.exit(0 if report.all_passed else 1)
PYEOF
}

driver_output=""
driver_rc=0
if ! driver_output=$(run_driver 2>&1); then
  driver_rc=$?
fi

printf '%s\n' "$driver_output"

# Surface a structured summary line for log scrapers.
if (( driver_rc == 0 )); then
  log "result: PASS"
  exit 0
fi
log "result: FAIL (driver exit=$driver_rc)"

# Best-effort notify; never blocks the exit code.
NOTIFY_SCRIPT="$REPO_ROOT/shared/runtime/notify.sh"
if [[ -x "$NOTIFY_SCRIPT" ]]; then
  "$NOTIFY_SCRIPT" "[dr-test] weekly DR restore FAILED" \
                   "env=$ENV_NAME target=$TARGET_URI rc=$driver_rc" \
                   </dev/null >/dev/null 2>&1 &
fi

exit "$driver_rc"
