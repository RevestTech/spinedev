#!/usr/bin/env bash
# tools/test_dr_rto_gate.sh — SPINE-019 dry-run RTO gate smoke.
#
# Asserts tools/dr-test.sh --dry-run:
#   * exits 0
#   * emits JSON with rto_elapsed_seconds and rto_gate_pass
#   * skips the RTO gate even when --max-rto-seconds=1
#
# Usage:
#   bash tools/test_dr_rto_gate.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DR_TEST="${REPO_ROOT}/tools/dr-test.sh"

PY=""
if   [[ -x "$REPO_ROOT/.venv/bin/python3" ]]; then PY="$REPO_ROOT/.venv/bin/python3"
elif [[ -x "$REPO_ROOT/.venv/bin/python"  ]]; then PY="$REPO_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1;       then PY="$(command -v python3)"
else
  printf 'FAIL: python3 required to parse dr-test JSON\n' >&2
  exit 1
fi

assert_dry_run_json() {
  local label="$1"
  shift
  local output rc
  if ! output=$(bash "$DR_TEST" "$@" 2>/dev/null); then
    rc=$?
    printf 'FAIL: %s exited %s\n' "$label" "$rc" >&2
    printf '%s\n' "$output" >&2
    return 1
  fi
  if ! DR_JSON="$output" "$PY" -c '
import json
import os
import sys

label = sys.argv[1]
try:
    data = json.loads(os.environ["DR_JSON"])
except json.JSONDecodeError as exc:
    print(f"FAIL: {label} output is not JSON: {exc}", file=sys.stderr)
    sys.exit(1)

for key in ("rto_elapsed_seconds", "rto_gate_pass"):
    if key not in data:
        print(f"FAIL: {label} missing {key!r}", file=sys.stderr)
        sys.exit(1)

if not isinstance(data["rto_elapsed_seconds"], int):
    print(
        f"FAIL: {label} rto_elapsed_seconds must be int, "
        f"got {data['rto_elapsed_seconds']!r}",
        file=sys.stderr,
    )
    sys.exit(1)

if data["rto_gate_pass"] is not True:
    print(
        f"FAIL: {label} expected rto_gate_pass=true, "
        f"got {data['rto_gate_pass']!r}",
        file=sys.stderr,
    )
    sys.exit(1)

if data.get("rto_gate_skipped") is not True:
    print(f"FAIL: {label} expected rto_gate_skipped=true on dry-run", file=sys.stderr)
    sys.exit(1)

print(f"PASS: {label}")
' "$label"; then
    return 1
  fi
}

fail=0
assert_dry_run_json "default dry-run" --dry-run || fail=1
assert_dry_run_json "dry-run with max-rto-seconds=1 (gate skipped)" \
  --dry-run --max-rto-seconds=1 || fail=1

exit "$fail"
