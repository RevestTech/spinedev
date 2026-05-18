#!/usr/bin/env bash
# Pass D selftest: sources lib/db-outbox.sh, writes a mix of cost + event lines
# to a temp outbox.jsonl, and asserts:
#   (1) Both line types co-exist in the file (one .jsonl per role/state dir).
#   (2) Every line parses as valid JSON via python3.
#   (3) Outer `type` field correctly differentiates "cost" vs "event".
#   (4) Lifecycle envelope carries event_type, role, host_id, instance_id, payload.
#
# Negative assertions under set -euo — use explicit `if` per sibling tests.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/spine-outbox-events.XXXXXX")"
cleanup() { rm -rf "$ROOT"; }
trap cleanup EXIT

STATE_DIR="$ROOT/state"
mkdir -p "$STATE_DIR"

# Source the helper. spine_outbox_emit_event reads MODE/SLOT/SPINE_HOST_ID/
# SPINE_INSTANCE_ID from the env; populate them as the daemon would.
# Wave 3 (Squad A): db-outbox.sh migrated lib/ → shared/runtime/.
DBOUTBOX_SH="$REPO/shared/runtime/db-outbox.sh"
[[ -f "$DBOUTBOX_SH" ]] || DBOUTBOX_SH="$REPO/lib/db-outbox.sh"
# shellcheck source=/dev/null
source "$DBOUTBOX_SH"

export MODE=manager
export SLOT=-
export SPINE_HOST_ID=test-host
export SPINE_INSTANCE_ID=test-instance-pid

ROLE=datawright
OUTBOX="$STATE_DIR/outbox.jsonl"

# 1. Cost line (legacy shape) — built by hand to match the daemon's log_cost
#    envelope. We only care that the outer "type":"cost" survives co-existence
#    with new event lines; the inner shape can be minimal.
cost_json='{"type":"cost","ts":"2026-05-11T00:00:00Z","role":"datawright","mode":"manager","slot":"-","phase":"pickup","tier":"medium","wall_s":1,"rc":0,"outcome":"completed","host_id":"test-host","instance_id":"test-instance-pid","tokens_in":0,"tokens_out":0,"cost_usd":0,"model_id":""}'
spine_outbox_emit_cost "$ROLE" "$STATE_DIR" "$cost_json"

# 2. A handful of event lines covering the Pass-D types.
spine_outbox_emit_event "$ROLE" "$STATE_DIR" "DirectivePickup" \
  '{"hash":"abc123","classification":"directive","tier":"medium","requires_approval":false}'
spine_outbox_emit_event "$ROLE" "$STATE_DIR" "PlanWritten" \
  '{"workers_dispatched":3}'
spine_outbox_emit_event "$ROLE" "$STATE_DIR" "AwaitingApproval" \
  '{"file":"/tmp/dir/directive.md"}'
spine_outbox_emit_event "$ROLE" "$STATE_DIR" "Approved" \
  '{"approver":"khash @ 2026-05-11"}'
spine_outbox_emit_event "$ROLE" "$STATE_DIR" "ReportWritten" \
  '{"kind":"manager_report"}'
spine_outbox_emit_event "$ROLE" "$STATE_DIR" "AggregateCompleted" \
  '{"workers_aggregated":3}'
spine_outbox_emit_event "$ROLE" "$STATE_DIR" "Reaped" \
  '{"outcome":"timeout","exit_code":124,"wall_s":1500}'

# Empty payload should normalise to {} not break.
spine_outbox_emit_event "$ROLE" "$STATE_DIR" "DirectivePickup" ""

if [[ ! -s "$OUTBOX" ]]; then
  echo "FAIL: outbox.jsonl missing or empty" >&2
  exit 1
fi

# Assertion (2): every line is valid JSON.
# Assertion (3): outer `type` field is "cost" XOR "event"; capture counts.
python3 - <<PY
import json, sys
path = "$OUTBOX"
n_cost = 0
n_event = 0
seen_event_types = set()
with open(path, "r", encoding="utf-8") as fh:
    for i, raw in enumerate(fh, start=1):
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"FAIL line {i} not valid JSON: {e}: {line!r}", file=sys.stderr)
            sys.exit(1)
        t = obj.get("type")
        if t == "cost":
            n_cost += 1
        elif t == "event":
            n_event += 1
            for required in ("event_type", "ts", "role", "mode", "slot",
                             "host_id", "instance_id", "payload"):
                if required not in obj:
                    print(f"FAIL event line {i} missing field {required!r}: {line!r}", file=sys.stderr)
                    sys.exit(1)
            seen_event_types.add(obj["event_type"])
        else:
            print(f"FAIL line {i} has unexpected outer type {t!r}", file=sys.stderr)
            sys.exit(1)

if n_cost < 1:
    print(f"FAIL expected >=1 cost line, got {n_cost}", file=sys.stderr); sys.exit(1)
if n_event < 7:
    print(f"FAIL expected >=7 event lines, got {n_event}", file=sys.stderr); sys.exit(1)

expected_types = {"DirectivePickup","PlanWritten","AwaitingApproval","Approved",
                  "ReportWritten","AggregateCompleted","Reaped"}
missing = expected_types - seen_event_types
if missing:
    print(f"FAIL missing event types: {sorted(missing)}", file=sys.stderr); sys.exit(1)

# Empty-payload normalisation: at least one event must have payload == {}.
found_empty = False
with open(path, "r", encoding="utf-8") as fh:
    for raw in fh:
        line = raw.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("type") == "event" and obj.get("payload") == {}:
            found_empty = True
            break
if not found_empty:
    print("FAIL empty-payload event did not normalise to {}", file=sys.stderr); sys.exit(1)

print(f"OK ({n_cost} cost lines, {n_event} event lines, {len(seen_event_types)} unique event_types)")
PY

printf '%s\n' "test-outbox-events OK"
