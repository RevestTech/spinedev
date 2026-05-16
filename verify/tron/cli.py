"""Typer CLI for Tron HTTP API (TRON_API_URL + TRON_API_KEY)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import httpx
import typer

app = typer.Typer(help="Tron API client", no_args_is_help=True)


def _base_url() -> str:
    return os.environ.get("TRON_API_URL", "http://127.0.0.1:8000").rstrip("/")


def _api_key() -> str:
    key = os.environ.get("TRON_API_KEY")
    if not key:
        typer.echo("Set TRON_API_KEY in the environment.", err=True)
        raise typer.Exit(1)
    return key


def _api_request(
    method: str,
    path: str,
    *,
    params: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
    timeout: float = 120.0,
) -> Any:
    url = f"{_base_url()}/api{path}"
    headers = {"X-API-Key": _api_key()}
    with httpx.Client(timeout=timeout) as client:
        r = client.request(
            method, url, headers=headers, params=params, json=json_body
        )
    if r.status_code >= 400:
        typer.echo(f"HTTP {r.status_code}: {r.text}", err=True)
        raise typer.Exit(1)
    if not r.content:
        return None
    return r.json()


@app.command("ping")
def cmd_ping() -> None:
    """GET /health (no API key)."""
    url = f"{_base_url()}/health"
    with httpx.Client(timeout=10.0) as client:
        r = client.get(url)
    r.raise_for_status()
    typer.echo(json.dumps(r.json(), indent=2))


projects_app = typer.Typer(help="Projects")
app.add_typer(projects_app, name="projects")


@projects_app.command("list")
def projects_list(
    page: int = typer.Option(1, min=1),
    page_size: int = typer.Option(20, min=1, max=100),
) -> None:
    out = _api_request(
        "GET",
        "/projects",
        params={"page": page, "page_size": page_size},
    )
    typer.echo(json.dumps(out, indent=2))


@projects_app.command("get")
def projects_get(project_id: UUID) -> None:
    out = _api_request("GET", f"/projects/{project_id}")
    typer.echo(json.dumps(out, indent=2))


@projects_app.command("graph")
def projects_graph(
    project_id: UUID,
    limit: int = typer.Option(500, "--limit", "-n", ge=1, le=5000),
) -> None:
    """GET /api/projects/{id}/graph — import graph from last audit scan."""
    out = _api_request(
        "GET",
        f"/projects/{project_id}/graph",
        params={"limit_nodes": limit},
    )
    typer.echo(json.dumps(out, indent=2))


@projects_app.command("create")
def projects_create(
    name: str,
    description: Optional[str] = None,
    repo_url: Optional[str] = None,
    branch: str = typer.Option("main", "--branch"),
) -> None:
    body: dict[str, Any] = {"name": name, "default_branch": branch}
    if description is not None:
        body["description"] = description
    if repo_url is not None:
        body["repo_url"] = repo_url
    out = _api_request("POST", "/projects", json_body=body)
    typer.echo(json.dumps(out, indent=2))


audit_app = typer.Typer(help="Audits")
app.add_typer(audit_app, name="audit")


@audit_app.command("start")
def audit_start(
    project_id: UUID,
    branch: str = typer.Option("main", "--branch"),
    commit: Optional[str] = typer.Option(None, "--commit"),
) -> None:
    body: dict[str, Any] = {
        "project_id": str(project_id),
        "branch": branch,
        "trigger_type": "cli",
    }
    if commit:
        body["commit_hash"] = commit
    out = _api_request("POST", "/audits", json_body=body)
    typer.echo(json.dumps(out, indent=2))


@audit_app.command("get")
def audit_get(audit_id: UUID) -> None:
    out = _api_request("GET", f"/audits/{audit_id}")
    typer.echo(json.dumps(out, indent=2))


@audit_app.command("handoff")
def audit_handoff(
    audit_id: UUID,
    dest: str = typer.Option(
        ...,
        "--dest",
        "-d",
        help="Path to the scanned application repository root (files written here)",
    ),
    tron_ui_base: Optional[str] = typer.Option(
        None,
        "--tron-ui-base",
        help="Tron UI URL for links in breadcrumbs (default: TRON_UI_BASE or http://localhost:13080)",
    ),
    app_name: Optional[str] = typer.Option(
        None,
        "--app-name",
        help="Display name in handoff files (default: Tron project name from API)",
    ),
) -> None:
    """Write TRON_POST_SCAN.md + Cursor/Claude/Codex context files into the target repo (API must be reachable)."""
    from tron.services.scan_handoff_export import (
        paginate_audit_findings,
        write_audit_handoff_bundle,
    )

    base = (
        tron_ui_base or os.environ.get("TRON_UI_BASE") or "http://localhost:13080"
    ).rstrip("/")
    audit = _api_request("GET", f"/audits/{audit_id}", timeout=60.0)
    project = _api_request("GET", f"/projects/{audit['project_id']}", timeout=60.0)
    name = app_name or project.get("name") or "application"

    def _fetch(
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> Any:
        return _api_request(method, path, params=params, json_body=json_body, timeout=300.0)

    from tron.api.config import settings

    findings = paginate_audit_findings(_fetch, str(audit_id))
    dest_path = Path(dest).expanduser().resolve()
    dest_path.mkdir(parents=True, exist_ok=True)
    paths = write_audit_handoff_bundle(
        dest_path,
        app_name=name,
        audit_id=str(audit_id),
        tron_ui_base=base,
        audit=audit,
        findings=findings,
        append_tron_md_activity=settings.tron_handoff_append_tron_md,
    )
    for p in paths:
        typer.echo(f"Wrote {p}")


@audit_app.command("reconcile-stale-queued")
def audit_reconcile_stale_queued(
    older_than_minutes: int = typer.Option(
        None,
        "--older-than-minutes",
        "-m",
        help="Default from API (TRON_STALE_QUEUED_AUDIT_MINUTES, usually 120).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="List matching audit IDs without updating rows.",
    ),
) -> None:
    """POST /audits/reconcile-stale-queued (master key only)."""
    body: dict[str, object] = {"dry_run": dry_run}
    if older_than_minutes is not None:
        body["older_than_minutes"] = older_than_minutes
    out = _api_request("POST", "/audits/reconcile-stale-queued", json_body=body)
    typer.echo(json.dumps(out, indent=2))


plan_app = typer.Typer(help="Plan workflow")
app.add_typer(plan_app, name="plan")


@plan_app.command("start")
def plan_start(
    project_id: UUID,
    goals: str = typer.Option("", "--goals", "-g", help="Goals (or use --questionnaire-file)"),
    constraints: str = typer.Option("", "--constraints", "-c"),
    questionnaire_file: Optional[str] = typer.Option(
        None,
        "--questionnaire-file",
        "-q",
        help="JSON file: interactive wizard answers (see UI Plan wizard export shape)",
    ),
    write_tron: bool = typer.Option(
        True,
        "--write-tron/--no-write-tron",
        help="Request worker git push of .tron (needs TRON_PLAN_GIT_TOKEN on worker)",
    ),
) -> None:
    q: Optional[dict] = None
    if questionnaire_file:
        with open(questionnaire_file, encoding="utf-8") as f:
            q = json.load(f)
    body: dict[str, Any] = {
        "goals": goals,
        "constraints": constraints,
        "write_tron_files": write_tron,
    }
    if q is not None:
        body["questionnaire"] = q
    out = _api_request("POST", f"/plan/{project_id}", json_body=body)
    typer.echo(json.dumps(out, indent=2))


build_app = typer.Typer(help="Build workflow")
app.add_typer(build_app, name="build")

evolve_app = typer.Typer(help="Evolve workflow")
app.add_typer(evolve_app, name="evolve")


@evolve_app.command("start")
def evolve_start(
    project_id: UUID,
    directive: str = typer.Option(
        ...,
        "--directive",
        "-d",
        help="Evolve directive for iterative improvement (min 3 chars)",
    ),
) -> None:
    out = _api_request(
        "POST",
        f"/evolve/{project_id}",
        json_body={"directive": directive},
    )
    typer.echo(json.dumps(out, indent=2))


@build_app.command("start")
def build_start(
    project_id: UUID,
    task: str = typer.Option(..., "--task", "-t", help="Build task for Builder ISO"),
) -> None:
    out = _api_request(
        "POST",
        f"/build/{project_id}",
        json_body={"task": task},
    )
    typer.echo(json.dumps(out, indent=2))


fix_app = typer.Typer(help="Fix workflow")
app.add_typer(fix_app, name="fix")


@fix_app.command("start")
def fix_start(finding_id: UUID) -> None:
    out = _api_request("POST", f"/findings/{finding_id}/fix")
    typer.echo(json.dumps(out, indent=2))


admin_app = typer.Typer(help="Admin operations (Calibration, Drift, etc.)")
app.add_typer(admin_app, name="admin")


@admin_app.command("calibration-run")
def admin_calibration_run() -> None:
    """GET /api/admin/calibration — Fetch confidence calibration metrics."""
    out = _api_request("GET", "/admin/calibration")
    typer.echo(json.dumps(out, indent=2))


@admin_app.command("drift-check")
def admin_drift_check(
    template_id: str,
    current_text: str,
    baseline_text: str,
    threshold: float = 0.95,
) -> None:
    """POST /api/admin/drift/check — Detect semantic or hash-based drift."""
    body = {
        "template_id": template_id,
        "current_text": current_text,
        "baseline_text": baseline_text,
        "threshold": threshold,
    }
    out = _api_request("POST", "/admin/drift/check", json_body=body)
    typer.echo(json.dumps(out, indent=2))


@admin_app.command("regression-run")
def admin_regression_run(
    template_id: str,
    test_input: str,
    expected: bool = typer.Option(True, "--expected/--no-expected"),
    actual: bool = typer.Option(True, "--actual/--no-actual"),
) -> None:
    """POST /api/admin/regression/run — Trigger a simple regression test."""
    body = {
        "template_id": template_id,
        "test_input": test_input,
        "expected_behavior": expected,
        "actual_behavior": actual,
    }
    out = _api_request("POST", "/admin/regression/run", json_body=body)
    typer.echo(json.dumps(out, indent=2))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
