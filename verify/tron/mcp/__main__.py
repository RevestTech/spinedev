"""Run: python -m tron.mcp  (stdio MCP server; set TRON_API_URL, TRON_API_KEY)."""

from __future__ import annotations

import json
import os
from typing import Any
from uuid import UUID

import httpx

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("tron")


def _base_url() -> str:
    return os.environ.get("TRON_API_URL", "http://127.0.0.1:8000").rstrip("/")


def _headers() -> dict[str, str]:
    key = os.environ.get("TRON_API_KEY")
    if not key:
        raise RuntimeError("TRON_API_KEY is not set")
    return {"X-API-Key": key}


def _api_json(method: str, path: str, **kwargs: Any) -> str:
    url = f"{_base_url()}/api{path}"
    try:
        with httpx.Client(timeout=120.0) as client:
            r = client.request(method, url, headers=_headers(), **kwargs)
        if r.status_code >= 400:
            return json.dumps(
                {"error": r.text, "status_code": r.status_code},
                indent=2,
            )
        if not r.content:
            return json.dumps({"ok": True})
        return json.dumps(r.json(), indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)


@mcp.tool()
def tron_list_projects(page: int = 1, page_size: int = 20) -> str:
    """List Tron projects (paginated)."""
    return _api_json(
        "GET",
        "/projects",
        params={"page": page, "page_size": page_size},
    )


@mcp.tool()
def tron_get_project(project_id: str) -> str:
    """Get one project by UUID (includes plan artifact, gates, last build if present)."""
    UUID(project_id)  # validate
    return _api_json("GET", f"/projects/{project_id}")


@mcp.tool()
def tron_start_audit(project_id: str, branch: str = "main") -> str:
    """Start a full audit run for a project."""
    UUID(project_id)
    return _api_json(
        "POST",
        "/audits",
        json={
            "project_id": project_id,
            "branch": branch,
            "trigger_type": "mcp",
        },
    )


@mcp.tool()
def tron_get_audit(audit_id: str) -> str:
    """Get audit run status and counts."""
    UUID(audit_id)
    return _api_json("GET", f"/audits/{audit_id}")


@mcp.tool()
def tron_start_plan(
    project_id: str,
    goals: str = "",
    constraints: str = "",
    write_tron_files: bool = True,
    questionnaire_json: str = "",
) -> str:
    """Start PLAN workflow (Temporal). Optional questionnaire_json: JSON object string from interactive wizard."""
    UUID(project_id)
    payload: dict = {
        "goals": goals,
        "constraints": constraints,
        "write_tron_files": write_tron_files,
    }
    if questionnaire_json and questionnaire_json.strip():
        try:
            payload["questionnaire"] = json.loads(questionnaire_json)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"invalid questionnaire_json: {exc}"}, indent=2)
    return _api_json(
        "POST",
        f"/plan/{project_id}",
        json=payload,
    )


@mcp.tool()
def tron_start_build(project_id: str, task: str) -> str:
    """Start BUILD workflow (Temporal)."""
    UUID(project_id)
    return _api_json(
        "POST",
        f"/build/{project_id}",
        json={"task": task},
    )


@mcp.tool()
def tron_start_evolve(project_id: str, directive: str) -> str:
    """Start EVOLVE workflow (Temporal) — iterative improvement; saves evolve_artifact_json."""
    UUID(project_id)
    return _api_json(
        "POST",
        f"/evolve/{project_id}",
        json={"directive": directive},
    )


@mcp.tool()
def tron_start_fix(finding_id: str) -> str:
    """Start FIX workflow for a finding."""
    UUID(finding_id)
    return _api_json("POST", f"/findings/{finding_id}/fix")


@mcp.tool()
def tron_list_actionable_findings(
    audit_id: str,
    severity: str = "high,critical",
    limit: int = 20,
) -> str:
    """List the highest-priority findings from an audit, ready to feed
    back into a coding agent for in-IDE fixing.

    Designed for the agent-handoff workflow: an in-IDE Claude/Cursor
    session gets the audit_id from the post-scan handoff file, calls
    this tool, and walks the returned findings one at a time — calling
    ``tron_start_fix(finding_id)`` for each to spawn the FixWorkflow.

    Filters out anything that's already dismissed or has a fix in
    progress so the IDE agent doesn't re-fight resolved issues.

    Args:
        audit_id: UUID of the audit run.
        severity: Comma-separated severities to include
                  (default ``"high,critical"``). Use ``"all"`` for everything.
        limit: Max findings to return (default 20, capped at 200 server-side
               by the underlying findings API).
    """
    UUID(audit_id)
    sev_list = [s.strip() for s in severity.split(",") if s.strip()]
    if sev_list == ["all"]:
        sev_param = None
    else:
        sev_param = ",".join(sev_list)

    params = {"page": 1, "page_size": min(max(limit, 1), 200), "status": "open"}
    if sev_param:
        params["severity"] = sev_param

    return _api_json(
        "GET", f"/audits/{audit_id}/findings", params=params,
    )


@mcp.tool()
def tron_get_audit_cost(audit_id: str) -> str:
    """Per-audit LLM cost breakdown (provider × model × agent).

    Surfaces what each scan cost the operator. Useful when an IDE agent
    is iterating fixes and wants to budget further calls — or when a
    customer wants the spend number for their internal chargeback.
    """
    UUID(audit_id)
    return _api_json("GET", f"/audits/{audit_id}/cost")


@mcp.tool()
def tron_standards_defaults() -> str:
    """Return built-in default quality gates JSON."""
    return _api_json("GET", "/standards/defaults")


@mcp.tool()
def tron_standards_merged(project_id: str) -> str:
    """Merged quality gates: defaults → company_quality_gates_json → quality_gates_json."""
    UUID(project_id)
    return _api_json("GET", "/standards/merged", params={"project_id": project_id})


@mcp.tool()
def tron_list_control_packs() -> str:
    """List built-in compliance reference pack ids (GET /api/standards/control-packs)."""
    return _api_json("GET", "/standards/control-packs")


@mcp.tool()
def tron_get_control_pack(pack_id: str) -> str:
    """Fetch one built-in compliance reference pack JSON (GET /api/standards/control-packs/{id})."""
    return _api_json("GET", f"/standards/control-packs/{pack_id}")


@mcp.tool()
def tron_list_workflow_runs(status: str = "", limit: int = 50, offset: int = 0) -> str:
    """List audit runs with Temporal workflow_id / workflow_run_id (GET /api/workflow-runs)."""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status.strip():
        params["status"] = status.strip()
    return _api_json("GET", "/workflow-runs", params=params)


@mcp.tool()
def tron_evaluate_audit_quality_gates(audit_id: str) -> str:
    """Evaluate merged quality gates for a completed audit (POST /api/audits/{id}/evaluate-quality-gates)."""
    UUID(audit_id)
    return _api_json("POST", f"/audits/{audit_id}/evaluate-quality-gates")


@mcp.tool()
def tron_project_graph(project_id: str, limit_nodes: int = 500) -> str:
    """Dependency graph (code_files + import edges) after an audit has run."""
    UUID(project_id)
    return _api_json(
        "GET",
        f"/projects/{project_id}/graph",
        params={"limit_nodes": limit_nodes},
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
