#!/usr/bin/env bash
# Block Node/Docker tooling when cwd or command targets iCloud-synced repo path.
set -euo pipefail

INPUT="$(cat)"

python3 - "$INPUT" <<'PY'
import json
import re
import sys

raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
try:
    payload = json.loads(raw) if raw.strip() else {}
except json.JSONDecodeError:
    payload = {}

command = payload.get("command") or ""
cwd = payload.get("cwd") or payload.get("working_directory") or ""

icloud = re.compile(r"CloudStorage/iCloudDrive|com~apple~CloudDocs")
risky = re.compile(
    r"\b(npm|npx|node|vite|vitest|docker|hub-up\.sh|local-dev-setup\.sh)\b",
    re.I,
)

def on_icloud(text: str) -> bool:
    return bool(text and icloud.search(text))

def is_risky(text: str) -> bool:
    return bool(text and risky.search(text))

if (on_icloud(command) or on_icloud(cwd)) and (is_risky(command) or on_icloud(cwd)):
    print(
        json.dumps(
            {
                "permission": "deny",
                "user_message": (
                    "Node and Docker commands must run from ~/dev/SpineDevelopment. "
                    "The iCloud-synced path breaks vite and is not supported for Hub/SPA work."
                ),
                "agent_message": (
                    "Use cd ~/dev/SpineDevelopment (SPINE_LOCAL_ROOT) before npm, vite, "
                    "vitest, docker, or hub-up.sh. See LOCAL_DEV.md and spine-local-dev skill."
                ),
            }
        )
    )
    sys.exit(2)

print(json.dumps({"permission": "allow"}))
PY
