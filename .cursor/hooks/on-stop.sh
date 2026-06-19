#!/usr/bin/env bash
# Session stop: append lightweight handoff note for the next agent turn.
set -euo pipefail

CANONICAL="${SPINE_LOCAL_ROOT:-$HOME/dev/SpineDevelopment}"
INPUT="$(cat)"

python3 - "$CANONICAL" "$INPUT" <<'PY'
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

canonical = Path(sys.argv[1]).expanduser()
raw = sys.argv[2] if len(sys.argv) > 2 else "{}"

try:
    payload = json.loads(raw) if raw.strip() else {}
except json.JSONDecodeError:
    payload = {}

handoff_dir = canonical / ".spine"
handoff_dir.mkdir(parents=True, exist_ok=True)
handoff = handoff_dir / "last-stop.json"

git_dirty = None
try:
    result = subprocess.run(
        ["git", "-C", str(canonical), "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode == 0:
        git_dirty = bool(result.stdout.strip())
except (OSError, subprocess.TimeoutExpired):
    git_dirty = None

harness_state = canonical / ".spine" / "harness" / "state.json"
record = {
    "stopped_at": datetime.now(timezone.utc).isoformat(),
    "canonical_root": str(canonical),
    "git_dirty": git_dirty,
    "harness_state_present": harness_state.is_file(),
    "status": payload.get("status"),
}

handoff.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
PY

exit 0
