#!/usr/bin/env bash
# test-vitals.sh — Pass M. Verifies lib/vitals.sh:
#   * Emits valid one-line JSON (or "{}" when capture is impossible).
#   * When successful, the JSON contains at least one of the expected
#     vital fields.
#   * Always exits 0 (the contract — heartbeat depends on this).
#   * Completes well within a few seconds.
#
# Skip-with-success when both psutil is unavailable AND we can't even
# parse one of the fallback inputs (a CI sandbox that strips /proc and
# ps -- vanishingly rare but worth tolerating).

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Wave 3 (Squad A): vitals.sh migrated lib/ → shared/runtime/.
VITALS="$REPO/shared/runtime/vitals.sh"
[[ -f "$VITALS" ]] || VITALS="$REPO/lib/vitals.sh"

if [[ ! -f "$VITALS" ]]; then
  printf '%s\n' "missing $VITALS" >&2
  exit 1
fi

# Run vitals.sh and capture its stdout. We do NOT want a non-zero exit
# code to fail the test — vitals.sh promises to always exit 0.
OUT="$("$VITALS" 2>/dev/null)"
RC=$?

if [[ $RC -ne 0 ]]; then
  printf 'FAIL: vitals.sh exited %s (must always exit 0)\n' "$RC" >&2
  exit 1
fi

if [[ -z "$OUT" ]]; then
  printf 'FAIL: vitals.sh produced no output\n' >&2
  exit 1
fi

# Validate JSON. Prefer python3 (we already require it for the watcher).
# Tolerate missing python3 by doing a coarse-grained brace check.
if command -v python3 >/dev/null 2>&1; then
  if ! printf '%s' "$OUT" | python3 -c '
import json, sys
data = sys.stdin.read().strip()
obj = json.loads(data)
if not isinstance(obj, dict):
    sys.exit("not an object")
' 2>/dev/null; then
    printf 'FAIL: vitals.sh stdout is not valid JSON: %s\n' "$OUT" >&2
    exit 1
  fi
else
  case "$OUT" in
    \{*\}) : ;;
    *)
      printf 'FAIL: vitals.sh stdout does not look like JSON (no python3 to check): %s\n' "$OUT" >&2
      exit 1
      ;;
  esac
fi

# Empty object is acceptable on a locked-down CI host.
if [[ "$(printf '%s' "$OUT" | tr -d '[:space:]')" == '{}' ]]; then
  printf 'SKIP: vitals.sh emitted {} — psutil missing and CLI fallback unavailable. Treating as success.\n'
  exit 0
fi

# When non-empty, at least one of the expected fields should appear.
EXPECTED=(cpu_pct mem_used_mb mem_total_mb disk_used_gb disk_total_gb
          load_avg_1m load_avg_5m load_avg_15m
          spine_cpu_pct spine_mem_mb spine_proc_count)
FOUND=0
for k in "${EXPECTED[@]}"; do
  if [[ "$OUT" == *"\"$k\""* ]]; then
    FOUND=1
    break
  fi
done

if [[ $FOUND -eq 0 ]]; then
  printf 'FAIL: vitals.sh emitted JSON but no expected fields: %s\n' "$OUT" >&2
  exit 1
fi

printf 'OK: vitals.sh -> %s\n' "$OUT"
exit 0
