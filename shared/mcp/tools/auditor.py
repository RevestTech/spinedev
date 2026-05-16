"""Auditor pre-Verify hook for ``BuildArtifact`` (REQ-INIT-7 FR-7, STORY-7.4.3).

Single MCP tool ``verify_build_artifact`` runs three cheap gates in order:
schema re-validation → optional path-scope (fnmatch globs) → KG-impact diff
(re-runs ``impact_radius`` per changed file and compares to engineer's
claimed ``kg_impact``). Missing callers ⇒ ``kg_impact_mismatch``; under
``strict=True`` over-claims also fail. Non-approved verdicts ship a short
remediation directive. Audit row → ``spine_audit`` (``subsystem='shared'``).

Lazy-imports ``shared.mcp.tools.kg.impact_radius`` to dodge register-time
cycles. Router wiring is a follow-up. See ``auditor_README.md``.
"""

from __future__ import annotations

import fnmatch
import logging
from time import perf_counter
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.mcp.schemas import ToolResponse, ToolStatus
from shared.mcp.tools import register_tool
from shared.schemas.build.build_artifact import BuildArtifact

logger = logging.getLogger(__name__)

Verdict = Literal[
    "approved", "kg_impact_mismatch", "scope_violation",
    "schema_invalid", "needs_review",
]


class VerifyBuildArtifactInput(BaseModel):
    """Inputs for ``verify_build_artifact`` (REQ-INIT-7 FR-7)."""
    model_config = ConfigDict(extra="forbid")
    build_artifact: BuildArtifact = Field(..., description="Artifact under verification.")
    repo: str = Field(..., min_length=1, description="Repo for impact_radius lookup.")
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="auditor", min_length=1)
    strict: bool = Field(default=True,
        description="If True, missing AND extra kg_impact nodes both fail the verdict.")
    directive_scope: list[str] | None = Field(default=None,
        description="Optional fnmatch globs the directive is allowed to touch.")
    commit_sha: str | None = Field(default=None,
        description="Point-in-time snapshot for impact_radius (NFR-6).")


class KGImpactDiff(BaseModel):
    """Engineer-claimed vs auditor-computed kg_impact diff."""
    model_config = ConfigDict(extra="forbid")
    claimed_count: int
    actual_count: int
    missing_from_claim: list[str] = Field(default_factory=list,
        description="Nodes auditor found that engineer didn't list.")
    extra_in_claim: list[str] = Field(default_factory=list,
        description="Nodes engineer listed that auditor didn't find.")


class VerifyBuildArtifactOutput(BaseModel):
    """Structured payload returned by ``verify_build_artifact``."""
    model_config = ConfigDict(extra="forbid")
    status: ToolStatus
    verdict: Verdict
    kg_impact_diff: KGImpactDiff | None = None
    scope_violations: list[str] = Field(default_factory=list)
    schema_errors: list[str] = Field(default_factory=list)
    audit_id: UUID
    rationale: str = Field(..., description="1-2 sentence verdict summary.")
    remediation_directive: str | None = Field(default=None,
        description="Composed directive the engineer can re-run with; None when approved.")
    duration_ms: int = 0


def _validate_schema(artifact: BuildArtifact) -> list[str]:
    """Round-trip through ``model_validate`` so cross-field validators
    (refuse-to-seal, runtime consistency, cost non-negative) fire even when
    the caller hand-built the instance. Empty list = clean."""
    try:
        BuildArtifact.model_validate(artifact.model_dump(mode="python"))
        return []
    except ValidationError as ve:
        return [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in ve.errors()]


def _compute_actual_impact(*, repo: str, project_id: str, commit_sha: str | None,
                           paths: list[str]) -> set[str]:
    """One ``impact_radius`` call per changed file (target_type='file'); union
    the returned node_ids. Lazy import dodges a register-time cycle with kg.py.
    Any per-path exception is logged and skipped — the hook never crashes."""
    from shared.mcp.tools.kg import ImpactRadiusInput, impact_radius

    actual: set[str] = set()
    for path in paths:
        try:
            resp = impact_radius(ImpactRadiusInput(
                project_id=project_id, target=path, target_type="file",
                repo=repo, include_tests=True, commit_sha=commit_sha))
        except Exception as exc:  # noqa: BLE001 — hook must not crash
            logger.warning("auditor_impact_radius_failed",
                           extra={"path": path, "err": str(exc)})
            continue
        for n in (resp.data or {}).get("impacted", []) or []:
            nid = n.get("node_id") if isinstance(n, dict) else None
            if nid:
                actual.add(nid)
    return actual


def _check_scope(paths: list[str], scope: list[str] | None) -> list[str]:
    """Return paths that don't match any fnmatch glob in ``scope``."""
    if not scope:
        return []
    return [p for p in paths if not any(fnmatch.fnmatch(p, pat) for pat in scope)]


def _compose_remediation(*, verdict: Verdict, diff: KGImpactDiff | None,
                         scope_violations: list[str], schema_errors: list[str],
                         directive_id: str) -> str:
    """Short, actionable directive the engineer daemon can pick up."""
    head = (f"BuildArtifact for `{directive_id}` rejected by auditor "
            f"(verdict: {verdict}).")
    if verdict == "schema_invalid":
        return head + "\n\nSchema errors:\n" + "\n".join(
            f"- {e}" for e in schema_errors[:10]) + "\n\nFix and re-seal."
    if verdict == "scope_violation":
        return head + "\n\nPaths outside declared scope:\n" + "\n".join(
            f"- `{p}`" for p in scope_violations[:10]
        ) + "\n\nRevert or request scope expansion before re-sealing."
    if verdict == "kg_impact_mismatch" and diff is not None:
        parts = [head, ""]
        if diff.missing_from_claim:
            parts.append("Missing kg_impact nodes (auditor found, you didn't list):")
            parts.extend(f"- `{n}`" for n in diff.missing_from_claim[:15])
        if diff.extra_in_claim:
            parts.append("")
            parts.append("Over-claimed nodes (you listed, auditor didn't find):")
            parts.extend(f"- `{n}`" for n in diff.extra_in_claim[:15])
        parts.append("\nRe-run `impact_radius` per changed file before re-sealing.")
        return "\n".join(parts)
    return head


def _audit(*, actor: str, artifact: BuildArtifact, verdict: Verdict,
           diff: KGImpactDiff | None, scope_violations: list[str],
           schema_errors: list[str], duration_ms: int, strict: bool) -> UUID:
    """Best-effort audit write; never blocks the verdict path on audit failure."""
    audit_uuid = uuid4()
    meta: dict = {
        "verdict": verdict, "strict": strict, "directive_id": artifact.directive_id,
        "project_id": artifact.project_id, "role": artifact.role,
        "scope_violation_count": len(scope_violations),
        "schema_error_count": len(schema_errors), "duration_ms": duration_ms,
    }
    if diff is not None:
        meta.update({"claimed_count": diff.claimed_count,
                     "actual_count": diff.actual_count,
                     "missing_count": len(diff.missing_from_claim),
                     "extra_count": len(diff.extra_in_claim)})
    try:
        from shared.audit.audit_record import AuditRecord, chain_to_previous, write_via_psql
        rec = AuditRecord(role=actor, subsystem="shared",
                          action="verify_build_artifact", actor=actor,
                          subject_type="build_artifact",
                          subject_id=str(artifact.artifact_uuid),
                          metadata=meta, event_uuid=audit_uuid)
        rec = chain_to_previous(rec, None)
        write_via_psql(rec)
    except Exception as exc:  # noqa: BLE001 — audit is best-effort
        logger.warning("verify_build_artifact_audit_write_failed",
                       extra={"err": str(exc), "verdict": verdict})
    return audit_uuid


def _emit(*, payload: VerifyBuildArtifactInput, verdict: Verdict, rationale: str,
          t0: float, diff: KGImpactDiff | None = None,
          scope_violations: list[str] | None = None,
          schema_errors: list[str] | None = None) -> ToolResponse:
    """Build the audit row + ToolResponse envelope for one verdict."""
    artifact = payload.build_artifact
    sv = scope_violations or []
    se = schema_errors or []
    duration_ms = int((perf_counter() - t0) * 1000)
    audit_id = _audit(actor=payload.actor, artifact=artifact, verdict=verdict,
                      diff=diff, scope_violations=sv, schema_errors=se,
                      duration_ms=duration_ms, strict=payload.strict)
    remediation = None if verdict == "approved" else _compose_remediation(
        verdict=verdict, diff=diff, scope_violations=sv, schema_errors=se,
        directive_id=artifact.directive_id)
    out = VerifyBuildArtifactOutput(
        status="ok", verdict=verdict, kg_impact_diff=diff,
        scope_violations=sv, schema_errors=se, audit_id=audit_id,
        rationale=rationale, remediation_directive=remediation,
        duration_ms=duration_ms)
    return ToolResponse(status="ok", data=out.model_dump(mode="json"),
                        audit_id=audit_id)


@register_tool(
    name="verify_build_artifact", input_model=VerifyBuildArtifactInput,
    story="STORY-7.4.3",
    description="Verify a BuildArtifact's claimed kg_impact matches actual graph traversal.",
    tags=("auditor", "build", "kg"),
)
def verify_build_artifact(payload: VerifyBuildArtifactInput) -> ToolResponse:
    """Order: schema (local) → scope (local) → kg_impact diff (one DB call per
    changed file). First failing gate wins so the most actionable verdict
    surfaces first."""
    t0 = perf_counter()
    artifact = payload.build_artifact
    logger.info("mcp_tool_call",
                extra={"tool": "verify_build_artifact",
                       "project_id": payload.project_id, "actor": payload.actor,
                       "artifact_uuid": str(artifact.artifact_uuid),
                       "strict": payload.strict})
    paths = [c.path for c in artifact.code_changes]

    schema_errors = _validate_schema(artifact)
    if schema_errors:
        return _emit(payload=payload, verdict="schema_invalid", t0=t0,
                     schema_errors=schema_errors,
                     rationale=f"BuildArtifact failed re-validation ({len(schema_errors)} errors).")

    scope_violations = _check_scope(paths, payload.directive_scope)
    if scope_violations:
        return _emit(payload=payload, verdict="scope_violation", t0=t0,
                     scope_violations=scope_violations,
                     rationale=f"{len(scope_violations)} path(s) outside declared scope.")

    # kg_impact diff is allowed-empty when there are no code_changes (the
    # refuse-to-seal validator catches engineer+code_changes+empty upstream).
    claimed = {n.node_id for n in artifact.kg_impact}
    actual = _compute_actual_impact(
        repo=payload.repo, project_id=payload.project_id,
        commit_sha=payload.commit_sha, paths=paths) if paths else set()
    missing, extra = sorted(actual - claimed), sorted(claimed - actual)
    diff = KGImpactDiff(claimed_count=len(claimed), actual_count=len(actual),
                        missing_from_claim=missing,
                        extra_in_claim=extra if payload.strict else [])
    mismatch = bool(missing) or (payload.strict and bool(extra))
    verdict: Verdict = "kg_impact_mismatch" if mismatch else "approved"
    rationale = (f"kg_impact matches graph ({len(claimed)} claimed, {len(actual)} actual)."
                 if verdict == "approved" else
                 f"kg_impact mismatch: {len(missing)} missing, {len(extra)} extra "
                 f"(strict={payload.strict}).")
    return _emit(payload=payload, verdict=verdict, t0=t0, diff=diff, rationale=rationale)


__all__: list[str] = [
    "KGImpactDiff", "Verdict", "VerifyBuildArtifactInput",
    "VerifyBuildArtifactOutput", "verify_build_artifact",
]
