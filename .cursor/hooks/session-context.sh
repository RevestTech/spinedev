#!/usr/bin/env bash
# Session start: record canonical local root and warn if workspace is on iCloud.
set -euo pipefail

CANONICAL="${SPINE_LOCAL_ROOT:-$HOME/dev/SpineDevelopment}"
INPUT="$(cat)"

python3 - "$CANONICAL" "$INPUT" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

canonical = Path(sys.argv[1]).expanduser().resolve()
raw = sys.argv[2] if len(sys.argv) > 2 else "{}"

try:
    payload = json.loads(raw) if raw.strip() else {}
except json.JSONDecodeError:
    payload = {}

workspace_roots = payload.get("workspace_roots") or payload.get("workspaceRoots") or []
if isinstance(workspace_roots, str):
    workspace_roots = [workspace_roots]

marker_dir = canonical / ".spine"
marker_dir.mkdir(parents=True, exist_ok=True)
marker = marker_dir / "cursor-session.json"
marker.write_text(
    json.dumps(
        {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "canonical_root": str(canonical),
            "workspace_roots": workspace_roots,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

icloud_fragments = ("CloudStorage/iCloudDrive", "com~apple~CloudDocs")
for root in workspace_roots:
    root_s = str(root)
    if any(fragment in root_s for fragment in icloud_fragments):
        sys.stderr.write(
            "Spine hook: workspace is on iCloud. "
            f"Open ~/dev/SpineDevelopment for npm/Docker. Canonical: {canonical}\n"
        )
        break
PY

exit 0
