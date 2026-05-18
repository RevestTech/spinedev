#!/usr/bin/env bash
# Pass H selftest: sources lib/db-outbox.sh, exports the SPINE_* env vars
# team.sh::cmd_up would set, calls spine_outbox_emit_instance_event three
# times (Started, Heartbeat, Stopped), and asserts:
#   (1) An instance outbox file was created.
#   (2) It has exactly 3 lines.
#   (3) Each line parses as JSON with type=instance, the expected
#       event_type, and all required fields.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/spine-instance-outbox.XXXXXX")"
cleanup() { rm -rf "$ROOT"; }
trap cleanup EXIT

# Override the outbox path so we don't write under the real project tree.
export SPINE_INSTANCE_OUTBOX="$ROOT/.instance-outbox.jsonl"

# Wave 3 (Squad A): db-outbox.sh migrated lib/ → shared/runtime/.
DBOUTBOX_SH="$REPO/shared/runtime/db-outbox.sh"
[[ -f "$DBOUTBOX_SH" ]] || DBOUTBOX_SH="$REPO/lib/db-outbox.sh"
# shellcheck source=/dev/null
source "$DBOUTBOX_SH"

export SPINE_GROUP_ID="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
export SPINE_HOST_ID="test-host.local"
export SPINE_VERSION_SHA="abcdef0123456789deadbeefcafebabefeedface"
export SPINE_PROJECT_SLUG="SpineDevelopment"
export SPINE_PROJECT_PATH="/tmp/SpineDevelopment"
export USER="${USER:-testuser}"

spine_outbox_emit_instance_event "InstanceStarted"   "{}"
spine_outbox_emit_instance_event "InstanceHeartbeat" "{}"
spine_outbox_emit_instance_event "InstanceStopped"   "{}"

if [[ ! -s "$SPINE_INSTANCE_OUTBOX" ]]; then
  echo "FAIL: instance outbox missing or empty at $SPINE_INSTANCE_OUTBOX" >&2
  exit 1
fi

line_count=$(wc -l < "$SPINE_INSTANCE_OUTBOX" | tr -d ' ')
if [[ "$line_count" != "3" ]]; then
  echo "FAIL: expected 3 lines in instance outbox, got $line_count" >&2
  cat "$SPINE_INSTANCE_OUTBOX" >&2 || true
  exit 1
fi

python3 - <<PY
import json, sys
path = "$SPINE_INSTANCE_OUTBOX"
expected = ["InstanceStarted", "InstanceHeartbeat", "InstanceStopped"]
required = ("event_type", "ts", "group_id", "host_id", "os_user",
            "project_slug", "project_path", "version_sha",
            "version_short", "spine_version", "payload")
seen = []
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
        if obj.get("type") != "instance":
            print(f"FAIL line {i} type != instance: {obj.get('type')!r}", file=sys.stderr)
            sys.exit(1)
        for k in required:
            if k not in obj:
                print(f"FAIL line {i} missing field {k!r}: {line!r}", file=sys.stderr)
                sys.exit(1)
        if obj["group_id"] != "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee":
            print(f"FAIL line {i} group_id mismatch: {obj['group_id']!r}", file=sys.stderr)
            sys.exit(1)
        if obj["host_id"] != "test-host.local":
            print(f"FAIL line {i} host_id mismatch: {obj['host_id']!r}", file=sys.stderr)
            sys.exit(1)
        if obj["version_short"] != "abcdef012345":
            print(f"FAIL line {i} version_short not truncated correctly: {obj['version_short']!r}", file=sys.stderr)
            sys.exit(1)
        seen.append(obj["event_type"])

if seen != expected:
    print(f"FAIL event_type order/values wrong: got {seen}, want {expected}", file=sys.stderr)
    sys.exit(1)

print(f"OK ({len(seen)} instance events, types: {seen})")
PY

printf '%s\n' "test-instance-outbox OK"
