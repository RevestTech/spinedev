"""Spine plan-phase product runner — charter-grounded PRD from intake answers.

Replaces the template-only ``synthesize_prd_draft`` path for HTTP-facing
intake: when intake answers (from the YAML question loop or the Hub chat
transcript) are available, the product role produces ``prd_md`` via the
configured LLM + product charter.

Boundaries:
- Reads intake answers only — does not drive the interactive question loop
  (that remains ``intake_runner.run_intake``).
- Reads / writes ``spine_lifecycle.project.metadata`` (``prd_md``,
  optional ``prd_draft`` from the deterministic synthesizer when template
  answers are present).
- Audits via ``shared.audit.audit_record.write_via_psql``.
- Directive bus via ``shared.runtime.role_runtime`` (one row per run).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from plan.runtime.hub_role_runner import _PRODUCT_PROMPT
from plan.runtime.intake_runner import synthesize_prd_draft
from shared.llm import LLMRequest, Message, call_async

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHARTERS_DIR = _REPO_ROOT / "shared" / "charters"
_DEFAULT_MODEL = os.environ.get("SPINE_INTAKE_MODEL", "claude-sonnet-4-6")
_ARTIFACT_KEY = "prd_md"

_CANONICAL_SECTIONS = (
    "Problem statement",
    "Users / stakeholders",
    "In scope",
    "Out of scope",
    "Goals",
    "Acceptance criteria",
    "Open questions",
)


@dataclass
class ProductResult:
    """What ``run_product()`` produced."""

    ok: bool
    prd_md: str = ""
    directive_id: str = ""
    artifact_key: str = _ARTIFACT_KEY
    error_class: str | None = None
    error_message: str | None = None
    project_uuid: str = ""
    project_name: str = ""
    prd_draft_valid: bool = False
    audit_event_count: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def _load_charter(role: str) -> str:
    path = _CHARTERS_DIR / f"{role}.md"
    if not path.exists():
        return f"# Charter for {role} (not found at {path})"
    return path.read_text(encoding="utf-8")


def _format_intake_context(intake_answers: dict[str, Any]) -> str:
    """Render intake answers for the LLM system prompt."""
    if not intake_answers:
        return "_No intake answers supplied._"

    transcript_text = intake_answers.get("transcript_text")
    if isinstance(transcript_text, str) and transcript_text.strip():
        return "## Intake conversation\n\n" + transcript_text.strip()

    transcript = intake_answers.get("transcript")
    if isinstance(transcript, list) and transcript:
        lines: list[str] = []
        for turn in transcript:
            if isinstance(turn, dict):
                role = str(turn.get("role", "user")).upper()
                content = str(turn.get("content", "")).strip()
                if content:
                    lines.append(f"**{role}:** {content}")
        if lines:
            return "## Intake conversation\n\n" + "\n\n".join(lines)

    lines = ["## Intake answers\n"]
    for key, value in sorted(intake_answers.items()):
        if key.startswith("_") or key in {"transcript", "transcript_text", "source"}:
            continue
        if isinstance(value, list):
            rendered = ", ".join(str(v) for v in value)
        else:
            rendered = str(value)
        lines.append(f"- **{key}**: {rendered}")
    return "\n".join(lines) if len(lines) > 1 else "_No intake answers supplied._"


# ── DB helpers (psql shell-outs; matches intake_runner.py) ─────────────


def _db_url() -> str | None:
    return os.environ.get("SPINE_DB_URL")


def _psql(sql: str, *, timeout: int = 15) -> str:
    url = _db_url()
    if not url:
        raise RuntimeError("SPINE_DB_URL not set")
    cmd = ["psql", url, "-At", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"psql rc={proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _write_audit(
    *,
    action: str,
    project_id: int,
    actor: str,
    metadata: dict[str, Any],
    rationale: str | None = None,
    subject_id: str | None = None,
) -> bool:
    try:
        from shared.audit.audit_record import (
            AuditRecord,
            chain_to_previous,
            write_via_psql,
        )
    except Exception:
        return False
    try:
        try:
            tip = _psql(
                "SELECT content_hash FROM spine_audit.audit_event "
                "ORDER BY event_id DESC LIMIT 1;"
            )
        except Exception:
            tip = ""
        rec = AuditRecord(
            project_id=project_id,
            phase="plan_in_progress",
            role="product",
            subsystem="plan",
            action=action,
            actor=actor,
            subject_type="prd",
            subject_id=subject_id or f"product:{project_id}",
            rationale=rationale,
            metadata=metadata,
        )
        rec = chain_to_previous(rec, tip or None)
        write_via_psql(rec)
        return True
    except Exception:
        return False


def _persist_metadata(
    project: dict[str, Any],
    patch: dict[str, Any],
    *,
    role: str,
    directive_id: str,
) -> None:
    from build.runtime.build_dispatcher import _load_project, _merge_metadata  # noqa: PLC0415
    from shared.runtime.project_workspace import promote_plan_artifacts  # noqa: PLC0415

    project_id = str(project.get("project_uuid") or project.get("id"))
    row = _load_project(project_id)
    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}

    commit_patch = promote_plan_artifacts(
        project_id,
        patch,
        metadata=metadata,
        role=role,
        directive_id=directive_id,
        project_name=str(project.get("name") or row.get("name") or ""),
    )
    merged = {**patch, **commit_patch} if commit_patch else patch
    _merge_metadata(int(row["id"]), merged)


def _maybe_synthesize_prd_draft(
    *,
    project: dict[str, Any],
    intake_answers: dict[str, Any],
    actor: str,
) -> tuple[dict[str, Any], bool]:
    """Deterministic PRDv1 draft when template-shaped answers are present."""
    template = intake_answers.get("template") or (
        (project.get("metadata") or {}).get("intake") or {}
    ).get("template")
    if not template:
        source = intake_answers.get("source")
        if source not in (None, "intake_template"):
            return {}, False
        # Chat-sourced answers have no template — skip deterministic draft.
        return {}, False

    answers = {
        k: v
        for k, v in intake_answers.items()
        if k not in {"template", "source", "transcript", "transcript_text"}
    }
    if not answers:
        intake_meta = (project.get("metadata") or {}).get("intake") or {}
        answers = intake_meta.get("answers") or {}
        template = template or intake_meta.get("template")
    if not template or not answers:
        return {}, False

    try:
        prd = synthesize_prd_draft(
            project_uuid=str(project.get("project_uuid") or ""),
            project_name=str(project.get("name") or ""),
            template_name=str(template),
            answers=answers,
            actor=actor,
        )
        prd_dump = prd.model_dump(mode="json")
        from plan.artifacts.prd_v1 import PRDv1

        PRDv1.model_validate(prd_dump)
        return prd_dump, True
    except Exception:
        return {}, False


async def _run_product_async(
    project: dict[str, Any],
    intake_answers: dict[str, Any],
    *,
    actor: str = "product",
    directive: str = "PRODUCE_PRD",
) -> ProductResult:
    from shared.runtime.role_runtime import (
        begin_directive,
        complete_directive,
        fail_directive,
    )

    project_uuid = str(project.get("project_uuid") or "")
    project_name = str(project.get("name") or "")
    project_id = project.get("id")
    project_type = (
        project.get("project_type")
        or project.get("work_item_type")
        or "feature"
    )

    handle = begin_directive(
        project_uuid,
        "product",
        directive,
        actor,
    )
    directive_id = handle.directive_id
    audit_count = 0

    if project_id is not None:
        audit_count += int(_write_audit(
            action="product_prd_started",
            project_id=int(project_id),
            actor=actor,
            metadata={
                "directive_id": directive_id,
                "answer_keys": sorted(intake_answers.keys()),
            },
            subject_id=f"product:{project_id}:{directive_id}",
        ))

    intake_block = _format_intake_context(intake_answers)
    system = (
        _PRODUCT_PROMPT
        + "\n\n---\n\n## Project metadata\n"
        + f"- Name: **{project_name}**\n"
        + f"- Type: **{project_type}**\n\n"
        + "---\n\n## Your charter\n\n"
        + _load_charter("product")
        + "\n\n---\n\n"
        + intake_block
    )

    try:
        resp = await call_async(LLMRequest(
            model=_DEFAULT_MODEL,
            messages=[
                Message(
                    role="user",
                    content=f"Produce the PRD for {project_name} now.",
                ),
            ],
            system=system,
            max_tokens=8000,
            temperature=0.3,
        ))
        prd_md = resp.content.strip()
    except Exception as exc:  # noqa: BLE001
        fail_directive(handle, str(exc))
        if project_id is not None:
            audit_count += int(_write_audit(
                action="product_prd_failed",
                project_id=int(project_id),
                actor=actor,
                metadata={
                    "directive_id": directive_id,
                    "error_class": type(exc).__name__,
                },
                subject_id=f"product:{project_id}:{directive_id}",
            ))
        return ProductResult(
            ok=False,
            directive_id=directive_id,
            artifact_key=_ARTIFACT_KEY,
            error_class=type(exc).__name__,
            error_message=str(exc)[:500],
            project_uuid=project_uuid,
            project_name=project_name,
            audit_event_count=audit_count,
        )

    patch: dict[str, Any] = {_ARTIFACT_KEY: prd_md}
    prd_draft, prd_draft_valid = _maybe_synthesize_prd_draft(
        project=project,
        intake_answers=intake_answers,
        actor=actor,
    )
    if prd_draft:
        patch["prd_draft"] = prd_draft

    try:
        _persist_metadata(
            project,
            patch,
            role="product",
            directive_id=directive_id,
        )
    except Exception as exc:  # noqa: BLE001
        fail_directive(handle, str(exc))
        return ProductResult(
            ok=False,
            directive_id=directive_id,
            artifact_key=_ARTIFACT_KEY,
            error_class=type(exc).__name__,
            error_message=str(exc)[:500],
            project_uuid=project_uuid,
            project_name=project_name,
            audit_event_count=audit_count,
        )

    complete_directive(
        handle,
        prd_md,
        ok=True,
        extra={"artifact_key": _ARTIFACT_KEY},
    )

    if project_id is not None:
        audit_count += int(_write_audit(
            action="product_prd_persisted",
            project_id=int(project_id),
            actor=actor,
            metadata={
                "directive_id": directive_id,
                "prd_chars": len(prd_md),
                "prd_draft_valid": prd_draft_valid,
            },
            subject_id=f"product:{project_id}:{directive_id}",
        ))

    return ProductResult(
        ok=True,
        prd_md=prd_md,
        directive_id=directive_id,
        artifact_key=_ARTIFACT_KEY,
        project_uuid=project_uuid,
        project_name=project_name,
        prd_draft_valid=prd_draft_valid,
        audit_event_count=audit_count,
    )


def run_product(
    project: dict[str, Any],
    intake_answers: dict[str, Any],
    *,
    actor: str = "product",
    directive: str = "PRODUCE_PRD",
) -> ProductResult:
    """Sync entry for HTTP intake + MCP callers (runs asyncio internally)."""
    return asyncio.run(_run_product_async(
        project,
        intake_answers,
        actor=actor,
        directive=directive,
    ))


def intake_answers_from_transcript(
    transcript: list[dict[str, str]],
) -> dict[str, Any]:
    """Shape Hub chat transcript into the intake_answers dict."""
    lines = [
        f"**{str(turn.get('role', 'user')).upper()}:** {str(turn.get('content', '')).strip()}"
        for turn in transcript
        if str(turn.get("content", "")).strip()
    ]
    return {
        "source": "intake_chat",
        "transcript": list(transcript),
        "transcript_text": "\n\n".join(lines),
    }


__all__ = [
    "ProductResult",
    "intake_answers_from_transcript",
    "run_product",
    "_CANONICAL_SECTIONS",
]
