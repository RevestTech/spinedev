#!/usr/bin/env bash
# Copy Tron post-scan handoff templates into a SCANNED APPLICATION repository root
# so Cursor / Claude / Codex agents in that repo see audit follow-ups.
#
# Usage (from Tron repo root):
#   export TRON_AUDIT_ID='uuid-from-tron'
#   export TRON_UI_BASE='http://localhost:13080'
#   ./scripts/init_tron_scan_handoff.sh /path/to/scanned-app-repo "Display Name"
#
# TRON_AUDIT_ID and TRON_UI_BASE are optional; placeholders remain if unset.

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
export REPO_ROOT
SRC="$REPO_ROOT/tron/agent_handoff_templates"
DEST=${1:?"Usage: $0 /path/to/scanned-application-repo [APP_DISPLAY_NAME]"}
NAME=${2:-$(basename "$DEST")}
TRON_AUDIT_ID="${TRON_AUDIT_ID:-PASTE_FROM_TRON_UI}"
TRON_UI_BASE="${TRON_UI_BASE:-http://localhost:13080}"

export REPO_ROOT SRC DEST NAME TRON_AUDIT_ID TRON_UI_BASE
python3 <<'PY'
import os
import sys
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"]).resolve()
sys.path.insert(0, str(repo_root))

from tron.services.scan_handoff_export import (
    UnmarkedExistingStrategy,
    merge_or_write_managed_file,
)

src = Path(os.environ["SRC"])
dest = Path(os.environ["DEST"]).expanduser().resolve()
name = os.environ["NAME"]
audit = os.environ["TRON_AUDIT_ID"]
base = os.environ["TRON_UI_BASE"]

subs = {
    "{{APP_NAME}}": name,
    "{{TRON_AUDIT_ID}}": audit,
    "{{TRON_UI_BASE}}": base,
}

def sub(txt: str) -> str:
    for k, v in subs.items():
        txt = txt.replace(k, v)
    return txt

(dest / ".cursor" / "rules").mkdir(parents=True, exist_ok=True)

mapping = [
    ("TRON_POST_SCAN.md.template", dest / "TRON_POST_SCAN.md", UnmarkedExistingStrategy.REPLACE),
    (
        "tron-scan-followups.mdc.template",
        dest / ".cursor" / "rules" / "tron-scan-followups.mdc",
        UnmarkedExistingStrategy.PREPEND,
    ),
    ("CLAUDE.md.template", dest / "CLAUDE.md", UnmarkedExistingStrategy.PREPEND),
    ("AGENTS.md.template", dest / "AGENTS.md", UnmarkedExistingStrategy.PREPEND),
]
for tmpl_name, outpath, strategy in mapping:
    t = src / tmpl_name
    if not t.is_file():
        raise SystemExit(f"Missing template: {t}")
    merge_or_write_managed_file(outpath, sub(t.read_text(encoding="utf-8")), unmarked_existing=strategy)
    print("Wrote", outpath)
print("\nNext: edit the managed block in", dest / "TRON_POST_SCAN.md", "or run Tron `audit handoff`; put durable notes outside the markers or in tron.md. Commit in the application repo.")
PY
