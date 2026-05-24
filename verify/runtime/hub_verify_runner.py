"""Hub code review via ``verify_audit`` (TRON) with LLM fallback."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from shared.llm import LLMRequest, Message, call_async
from shared.mcp.tools.iso import Blueprint
from shared.runtime.mcp_invoke import invoke_mcp_tool

PassFail = Literal["pass", "fail", "needs_user_review"]


@dataclass
class HubVerifyResult:
    ok: bool
    directive_id: str
    review_md: str = ""
    blocked: bool = False
    pass_fail: PassFail = "pass"
    findings_count: int = 0
    used_tron: bool = False
    error_class: str | None = None
    error_message: str | None = None
    project_uuid: str = ""
    project_name: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _load_project(project_id: str) -> dict[str, Any]:
    from build.runtime.build_dispatcher import _load_project as load  # noqa: PLC0415

    return load(project_id)


def _persist_metadata(project_id: str, patch: dict[str, Any]) -> None:
    from build.runtime.build_dispatcher import _load_project, _merge_metadata  # noqa: PLC0415

    row = _load_project(project_id)
    _merge_metadata(int(row["id"]), patch)


def _findings_to_markdown(
    *,
    project_name: str,
    pass_fail: PassFail,
    findings: list[dict[str, Any]],
    used_tron: bool,
) -> str:
    by_sev: dict[str, list[dict[str, Any]]] = {
        "critical": [], "high": [], "medium": [], "low": [],
    }
    for f in findings:
        sev = str(f.get("severity") or "low").lower()
        if sev not in by_sev:
            sev = "low"
        by_sev[sev].append(f)

    blocked = pass_fail == "fail" or bool(by_sev["critical"] or by_sev["high"])
    posture = "**REVIEW BLOCK**" if blocked else "**REVIEW PASS**"
    source = "TRON verify_audit" if used_tron else "LLM security_engineer fallback"

    lines = [
        f"# Code review — {project_name}",
        "",
        f"## Summary",
        "",
        f"Source: {source}. Posture: {posture}.",
        f"Findings: {len(findings)} total "
        f"({len(by_sev['critical'])} critical / {len(by_sev['high'])} high / "
        f"{len(by_sev['medium'])} medium / {len(by_sev['low'])} low).",
        "",
    ]

    for heading, key in (
        ("Critical findings", "critical"),
        ("High findings", "high"),
        ("Medium findings", "medium"),
        ("Low findings", "low"),
    ):
        lines.append(f"## {heading}")
        lines.append("")
        items = by_sev[key]
        if not items:
            lines.append("_None._")
            lines.append("")
            continue
        for item in items:
            path = item.get("file") or item.get("path") or "unknown"
            line_no = item.get("line") or item.get("line_start") or 0
            rule = item.get("rule") or item.get("title") or "finding"
            detail = item.get("detail") or item.get("message") or ""
            lines.append(f"- **{rule}** — `{path}:{line_no}`")
            if detail:
                lines.append(f"  {detail}")
            lines.append("")

    return "\n".join(lines).strip()


async def _llm_code_review(project: dict[str, Any]) -> HubVerifyResult:
    """Fallback when TRON is unavailable — mirrors legacy ``_dispatch_code_review``."""
    from shared.api.routes._post_ack import (  # noqa: PLC0415
        _CODE_REVIEW_PROMPT,
        _load_charter,
        _load_enterprise_directives,
    )
    from shared.runtime.role_activity import role_log  # noqa: PLC0415

    project_uuid = project["project_uuid"]
    project_name = project["name"]
    role_log(project_uuid, "security_engineer", "LLM security review started")
    prior = project.get("metadata") or {}
    from shared.runtime.project_workspace import count_workspace_files, resolve_code_dir  # noqa: PLC0415

    on_disk = count_workspace_files(project_uuid, prior)
    if on_disk == 0:
        return HubVerifyResult(
            ok=False,
            directive_id=f"dir_{uuid4().hex[:12]}",
            error_class="workspace_empty",
            error_message=(
                "No files on disk in the project workspace — metadata is stale or "
                "the Hub was rebuilt. Re-run **Engineer** from Pipeline controls, then "
                "re-submit for security review."
            ),
            project_uuid=project_uuid,
            project_name=project_name,
        )

    workspace = resolve_code_dir(project_uuid, prior).resolve()
    code_blocks: list[str] = []
    manifest: list[str] = []
    skip_dirs = {".next", "node_modules", ".git", ".claude"}
    if workspace.exists():
        for f in sorted(workspace.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(workspace)
            if any(part in skip_dirs for part in rel.parts):
                continue
            manifest.append(f"- `{rel}` ({f.stat().st_size:,} bytes)")
            if f.stat().st_size <= 80_000:
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    code_blocks.append(f"### `{rel}`\n```\n{content}\n```")
                except OSError:
                    continue
    code_dump = "\n\n".join(code_blocks)
    if len(code_dump) > 700_000:
        code_dump = code_dump[:700_000] + "\n\n[trimmed]"
    file_manifest = "\n".join(manifest) or "_(no files)_"

    context_blocks = []
    if prior.get("prd_md"):
        context_blocks.append("## Approved PRD\n\n" + prior["prd_md"])
    if prior.get("trd_md"):
        context_blocks.append("## Approved TRD\n\n" + prior["trd_md"])
    if prior.get("sprint_plan_md"):
        context_blocks.append("## Approved sprint plan\n\n" + prior["sprint_plan_md"])
    context_blocks.append(
        "## Complete file manifest\n\n" + file_manifest
        + "\n\n## Generated code\n\n" + code_dump
    )
    system = (
        _CODE_REVIEW_PROMPT
        + "\n\n---\n\n## Project metadata\n"
        + f"- Name: **{project_name}**\n\n"
        + "---\n\n## Spine enterprise SDLC directives\n\n"
        + _load_enterprise_directives()
        + "\n\n---\n\n## security_engineer charter\n\n"
        + _load_charter("security_engineer")
        + "\n\n---\n\n## auditor charter\n\n"
        + _load_charter("auditor")
        + "\n\n---\n\n" + "\n\n---\n\n".join(context_blocks)
    )
    model = os.environ.get("SPINE_INTAKE_MODEL", "claude-sonnet-4-6")
    role_log(project_uuid, "security_engineer", f"Scanning workspace ({on_disk} files) via {model}")
    resp = await call_async(LLMRequest(
        model=model,
        messages=[Message(role="user", content=f"Review {project_name} now.")],
        system=system,
        max_tokens=12000,
        temperature=0.1,
    ))
    review_md = resp.content.strip()
    blocked = (
        "REVIEW BLOCK" in review_md.upper()
        or (
            "## Critical findings" in review_md
            and "_None._" not in review_md.split("## Critical findings", 1)[1].split("##", 1)[0]
        )
    )
    role_log(
        project_uuid,
        "security_engineer",
        f"LLM review complete — {'BLOCKED' if blocked else 'PASS'}",
        level="error" if blocked else "success",
    )
    return HubVerifyResult(
        ok=True,
        directive_id=f"dir_{uuid4().hex[:12]}",
        review_md=review_md,
        blocked=blocked,
        pass_fail="fail" if blocked else "pass",
        findings_count=0,
        used_tron=False,
        project_uuid=project_uuid,
        project_name=project_name,
    )


def run_hub_code_review(
    *,
    project_id: str,
    pipeline_version: str,
    actor: str = "orchestrator",
) -> HubVerifyResult:
    """Sync entry: TRON ``verify_audit`` first, LLM fallback on failure."""
    directive_id = f"dir_{uuid4().hex[:12]}"
    try:
        project = _load_project(project_id)
    except RuntimeError as exc:
        return HubVerifyResult(
            ok=False,
            directive_id=directive_id,
            error_class="project_not_found",
            error_message=str(exc),
        )

    project_uuid = project["project_uuid"]
    project_name = project["name"]
    from shared.runtime.role_activity import role_log  # noqa: PLC0415

    role_log(project_uuid, "security_engineer", "Security review started")

    from shared.runtime.project_workspace import count_workspace_files  # noqa: PLC0415

    prior = project.get("metadata") or {}
    if count_workspace_files(project_uuid, prior) == 0:
        return HubVerifyResult(
            ok=False,
            directive_id=directive_id,
            error_class="workspace_empty",
            error_message=(
                "No files on disk in the project workspace — re-run engineer before "
                "security review (Hub rebuild may have wiped ephemeral dogfood storage)."
            ),
            project_uuid=project_uuid,
            project_name=project_name,
        )

    from build.runtime.workspace_artifact import (  # noqa: PLC0415
        build_sealed_artifact_from_workspace,
        persist_build_artifact,
    )

    artifact = build_sealed_artifact_from_workspace(
        project_id=project_uuid,
        project_uuid=project_uuid,
        phase=project.get("current_phase") or "build_in_progress",
        pipeline_version=pipeline_version,
        directive_id=directive_id,
        actor=actor,
        metadata=project.get("metadata") or {},
    )
    persist_build_artifact(project_id, artifact)
    role_log(project_uuid, "security_engineer", "Workspace artifact sealed for TRON audit")

    blueprint = Blueprint(
        file_patterns=["**/*"],
        check_types=["security", "quality", "performance"],
        not_in_scope=[],
    )
    payload = {
        "project_id": project_uuid,
        "actor": actor,
        "pipeline_version": pipeline_version,
        "build_artifact": artifact.model_dump(mode="json"),
        "blueprint": blueprint.model_dump(mode="json"),
        "sandbox_layer": False,
    }
    raw = invoke_mcp_tool("verify_audit", payload)
    if raw.get("status") != "ok":
        err = raw.get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else str(err)
        # TRON unavailable — fall back to legacy LLM review path.
        if msg and any(tok in str(msg).lower() for tok in (
            "tron", "not importable", "docker", "no_source_files", "artifact_not_sealed",
        )):
            role_log(project_uuid, "security_engineer", "TRON unavailable — falling back to LLM review", level="warn")
            return asyncio.run(_llm_code_review({
                "project_uuid": project_uuid,
                "name": project_name,
                "metadata": project.get("metadata") or {},
            }))
        return HubVerifyResult(
            ok=False,
            directive_id=directive_id,
            error_class="verify_audit_failed",
            error_message=str(msg)[:500],
            project_uuid=project_uuid,
            project_name=project_name,
        )

    data = raw.get("data") or {}
    findings = data.get("findings") or []
    pass_fail: PassFail = data.get("pass_fail") or "pass"
    blocked = pass_fail == "fail" or any(
        str(f.get("severity", "")).lower() in ("critical", "high") for f in findings
    )
    review_md = _findings_to_markdown(
        project_name=project_name,
        pass_fail=pass_fail,
        findings=findings,
        used_tron=True,
    )
    _persist_metadata(project_uuid, {
        "code_review_md": review_md,
        "code_review_blocked": bool(blocked),
        "verify_findings": data,
    })
    role_log(
        project_uuid,
        "security_engineer",
        f"TRON review complete — {'BLOCKED' if blocked else 'PASS'} ({len(findings)} findings)",
        level="error" if blocked else "success",
    )
    return HubVerifyResult(
        ok=True,
        directive_id=directive_id,
        review_md=review_md,
        blocked=blocked,
        pass_fail=pass_fail,
        findings_count=len(findings),
        used_tron=True,
        project_uuid=project_uuid,
        project_name=project_name,
        extra={"verify_audit_id": str(data.get("audit_id") or "")},
    )


__all__ = ["HubVerifyResult", "run_hub_code_review"]
