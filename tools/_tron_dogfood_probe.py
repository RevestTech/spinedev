"""Reproduce the verify_audit dogfood probe after wiring TRON imports.

Run from repo root:
    PYTHONPATH=.:verify .venv/bin/python tools/_tron_dogfood_probe.py
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timezone

# Honor a CLI flag to drop the LLM keys so we can prove the "no keys"
# path returns ``tron_keys_missing`` past the import wall.
if "--no-keys" in sys.argv:
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "verify"))

from shared.mcp.tools import discover_tools, TOOL_REGISTRY  # noqa: E402

discover_tools()

# Trivial source file with SQL injection + exec bait (Bandit B102, B608).
tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="spine-dogfood-", dir=str(REPO_ROOT)))
src = tmpdir / "app.py"
src.write_text(
    "import sqlite3\n"
    "import os\n"
    "name = os.environ.get('NAME', '')\n"
    "q = 'SELECT * FROM x WHERE name = ' + name\n"
    "exec(name)  # bandit B102\n"
)

spec = TOOL_REGISTRY["verify_audit"]
now = datetime.now(timezone.utc)

payload = spec.input_model.model_validate({
    "project_id": "999",
    "actor": "dogfood",
    "sandbox_layer": False,
    "cross_llm_validation": False,
    "build_artifact": {
        "directive_id": "dir_dogfood_1",
        "project_id": "999",
        "phase": "build_in_progress",
        "role": "engineer",
        "pipeline_version": "1.0.0",
        "rationale": "dogfood probe",
        "status": "sealed",
        "code_changes": [{
            "path": str(src),
            "change_type": "create",
            "diff_hash": "0" * 64,
            "lines_added": 5,
            "lines_removed": 0,
            "language": "python",
        }],
        "kg_impact": [{
            "node_id": "app.py",
            "node_type": "Module",
            "impact_distance": 0,
        }],
        "cost": {
            "tokens_input": 1,
            "tokens_output": 1,
            "model": "m",
            "cost_usd": "0",
            "tier": "low",
        },
        "runtime": {
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "duration_seconds": 0,
        },
        "metadata": {"created_by": "dogfood"},
    },
    "blueprint": {
        "file_patterns": ["*.py"],
        "check_types": ["sql_injection"],
        "not_in_scope": [],
    },
})

import shutil
try:
    result = spec.fn(payload).model_dump(mode="json")
    print(json.dumps(result, default=str, indent=2))
finally:
    shutil.rmtree(str(tmpdir), ignore_errors=True)
