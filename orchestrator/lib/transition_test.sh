#!/usr/bin/env bash
# transition_test.sh — smoke test for orchestrator/lib/transition.sh.
#
# Covers STORY-9.2.1 (valid transition succeeds) and STORY-9.2.2 (invalid
# skip is rejected with a structured error). Style matches lib/tests/test-*.sh:
# skips cleanly when Postgres is unavailable, prints PASS/FAIL lines, cleans
# up its own data.
#
# Env:
#   SPINE_DB_URL — defaults to postgresql://spine:spine@localhost:33000/spine
#   SKIP_TRANSITION_SMOKE=1 — skip entirely.

set -euo pipefail
IFS=$'\n\t'

if [[ "${SKIP_TRANSITION_SMOKE:-}" == 1 ]]; then
  echo "SKIP_TRANSITION_SMOKE=1 — skipping transition smoke"
  exit 0
fi

if ! command -v pg_isready >/dev/null 2>&1 \
   || ! pg_isready -h localhost -p 33000 -q; then
  echo "SKIP: postgres not running on localhost:33000"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRANSITION_SH="$SCRIPT_DIR/transition.sh"
SPINE_DB_URL="${SPINE_DB_URL:-postgresql://spine:spine@localhost:33000/spine}"
export SPINE_DB_URL

_psql() { psql "$SPINE_DB_URL" -v ON_ERROR_STOP=1 -A -t -X -q "$@"; }

PROJECT_NAME="transition-smoke-$$-$(date +%s)"
PID=""

cleanup() {
  if [[ -n "$PID" ]]; then
    _psql -c "DELETE FROM spine_lifecycle.project WHERE id = $PID;" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "==> seeding test project '$PROJECT_NAME' at phase 'intake'"
PID="$(_psql <<SQL
INSERT INTO spine_lifecycle.project
       (name, project_type, current_phase, pipeline_version,
        pipeline_manifest_path, owner_user)
VALUES ('$PROJECT_NAME', 'internal_tool', 'intake', '1',
        'orchestrator/state/phases.yaml', 'smoke-test')
RETURNING id;
SQL
)"
PID="${PID//[[:space:]]/}"
[[ -n "$PID" ]] || { echo "FAIL: could not insert test project"; exit 1; }
_psql -c "INSERT INTO spine_lifecycle.phase_history (project_id, phase) VALUES ($PID, 'intake');" >/dev/null

# ─────────────────────────────────────────────────────────────────────
# Case 1: valid transition intake → plan_in_progress
# ─────────────────────────────────────────────────────────────────────
echo "==> case 1: valid transition intake → plan_in_progress"
if out="$(bash "$TRANSITION_SH" execute "$PID" plan_in_progress smoke-actor "valid" 2>&1)"; then
  echo "$out" | grep -q '"ok":true' \
    && echo "PASS: valid transition accepted" \
    || { echo "FAIL: expected ok:true in output: $out"; exit 1; }
else
  echo "FAIL: valid transition rejected unexpectedly: $out"; exit 1
fi

current="$(_psql -c "SELECT current_phase FROM spine_lifecycle.project WHERE id = $PID;")"
current="${current//[[:space:]]/}"
[[ "$current" == "plan_in_progress" ]] \
  && echo "PASS: project.current_phase is plan_in_progress" \
  || { echo "FAIL: expected plan_in_progress, got '$current'"; exit 1; }

# ─────────────────────────────────────────────────────────────────────
# Case 2: invalid skip plan_in_progress → build_in_progress (STORY-9.2.2)
# ─────────────────────────────────────────────────────────────────────
echo "==> case 2: invalid skip plan_in_progress → build_in_progress"
set +e
out="$(bash "$TRANSITION_SH" execute "$PID" build_in_progress smoke-actor "should-fail" 2>&1)"
rc=$?
set -e
if [[ $rc -eq 0 ]]; then
  echo "FAIL: invalid skip should have failed but exit=0; out=$out"; exit 1
fi
echo "$out" | grep -q '"code":"rejected_invalid"' \
  && echo "PASS: invalid skip rejected with rejected_invalid" \
  || { echo "FAIL: missing rejected_invalid in output: $out"; exit 1; }

echo "==> all transition smoke cases passed"
