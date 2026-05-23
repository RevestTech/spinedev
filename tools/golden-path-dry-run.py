#!/usr/bin/env python3
"""Golden path dry-run — bridge + MCP contract without LLM calls."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from shared.api.routes._role_dispatch_bridge import KIND_ROLE_DISPATCH
from shared.api.tests.test_golden_path_e2e import GOLDEN_PATH_APPROVAL_KINDS
from shared.mcp.tools import TOOL_REGISTRY, discover_tools


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _q(sql: str) -> str:
    db = os.environ.get("SPINE_DB_URL")
    if not db:
        return ""
    proc = subprocess.run(
        ["psql", db, "-At", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def main() -> None:
    discover_tools()

    missing = [k for k in GOLDEN_PATH_APPROVAL_KINDS if k not in KIND_ROLE_DISPATCH]
    if missing:
        _fail(f"bridge missing kinds: {missing}")

    for tool in ("plan_dispatch", "build_dispatch", "verify_hub_review"):
        if tool not in TOOL_REGISTRY:
            _fail(f"MCP tool missing: {tool}")

    db = os.environ.get("SPINE_DB_URL")
    if not db:
        print("INFO: SPINE_DB_URL unset — skipping DB-backed build brief check")
        print("OK: bridge + MCP registry")
        return

    prefix = os.environ.get("SMOKE_NAME", "golden-dry")
    spec = TOOL_REGISTRY["project_create"]
    created = spec.fn(spec.input_model.model_validate({
        "name": f"{prefix}-dry",
        "project_type": "feature",
        "owner": "golden-dry-run",
    })).model_dump(mode="json")
    if created.get("status") != "ok":
        _fail(f"project_create failed: {json.dumps(created)[:300]}")

    pid = created["data"]["id"]
    uuid = created["data"]["project_uuid"]

    # build_dispatch default = SYNTHESIZE_BRIEF — must refuse without PRD.
    bspec = TOOL_REGISTRY["build_dispatch"]
    no_prd = bspec.fn(bspec.input_model.model_validate({
        "project_id": str(pid),
        "pipeline_version": "1.0.0",
        "actor": "golden-dry-run",
    })).model_dump(mode="json")
    err = (no_prd.get("error") or {}).get("code")
    if no_prd.get("status") != "error" or err != "no_validated_prd":
        _fail(f"expected no_validated_prd, got: {json.dumps(no_prd)[:300]}")

    # Hub runner path must be reachable (will fail project load or LLM — not brief path).
    hub_try = bspec.fn(bspec.input_model.model_validate({
        "project_id": uuid,
        "pipeline_version": "1.0.0",
        "role": "engineer",
        "directive": "PRODUCE_CODE",
        "actor": "golden-dry-run",
    })).model_dump(mode="json")
    if hub_try.get("status") == "ok" and (hub_try.get("data") or {}).get("brief_id"):
        _fail("PRODUCE_CODE must not return build brief_id")

    repo = _q(
        f"SELECT metadata->>'repo' FROM spine_lifecycle.project WHERE id={pid};"
    )
    if not repo:
        _fail("project workspace repo metadata missing after create")

    print(f"OK: golden path dry-run (project_uuid={uuid}, repo={repo})")


if __name__ == "__main__":
    main()
