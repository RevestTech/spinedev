"""Post-processing: suppressions, path roles, follow-up flags (SEC-4, SEC-5)."""
from __future__ import annotations

from typing import Dict, List, Set
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tron.api.config import settings
from tron.domain.models import FindingSuppression
from tron.schemas.verification import FindingOutput, SeverityLevel
from tron.services.audit_path_filters import classify_path_role


async def load_suppressed_fingerprints_for_project(
    session: AsyncSession, project_id: UUID
) -> Set[str]:
    r = await session.execute(
        select(FindingSuppression.fingerprint).where(FindingSuppression.project_id == project_id)
    )
    return {row[0] for row in r.all()}


def filter_findings_by_suppression(
    findings: List[FindingOutput], suppressed: Set[str]
) -> List[FindingOutput]:
    if not suppressed:
        return findings
    return [f for f in findings if f.finding_fingerprint not in suppressed]


def filter_finding_dicts_by_suppression(
    findings: List[dict], suppressed: Set[str]
) -> List[dict]:
    if not suppressed:
        return findings
    out: List[dict] = []
    for f in findings:
        fp = f.get("finding_fingerprint")
        if fp and fp in suppressed:
            continue
        out.append(f)
    return out


def apply_path_role_to_outputs(
    findings: List[FindingOutput], test_globs: List[str] | None
) -> List[FindingOutput]:
    if not test_globs:
        return findings
    out: List[FindingOutput] = []
    for f in findings:
        role = classify_path_role(f.file_path, test_globs)
        if role:
            out.append(f.model_copy(update={"path_role": role}))
        else:
            out.append(f)
    return out


def apply_follow_up_flags_to_outputs(findings: List[FindingOutput], top_n: int) -> List[FindingOutput]:
    if top_n <= 0 or not findings:
        return findings
    order = {
        SeverityLevel.CRITICAL: 0,
        SeverityLevel.HIGH: 1,
        SeverityLevel.MEDIUM: 2,
        SeverityLevel.LOW: 3,
        SeverityLevel.INFO: 4,
    }
    candidates = [
        f
        for f in findings
        if f.severity in (SeverityLevel.CRITICAL, SeverityLevel.HIGH)
        and f.layer3_execution == "unverified"
    ]
    candidates.sort(
        key=lambda f: (order.get(f.severity, 9), -float(f.confidence or 0.0))
    )
    mark = {c.finding_fingerprint for c in candidates[:top_n]}
    return [
        f.model_copy(update={"follow_up_recommended": True})
        if f.finding_fingerprint in mark
        else f
        for f in findings
    ]


def apply_path_role_to_dicts(findings: List[dict], test_globs: List[str] | None) -> List[dict]:
    if not test_globs:
        return findings
    out: List[dict] = []
    for f in findings:
        role = classify_path_role(f.get("file_path", ""), test_globs)
        if role:
            g = dict(f)
            g["path_role"] = role
            out.append(g)
        else:
            out.append(f)
    return out


def apply_follow_up_flags_to_dicts(findings: List[dict], top_n: int) -> List[dict]:
    if top_n <= 0 or not findings:
        return findings
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    candidates: List[dict] = []
    for f in findings:
        sev = str(f.get("severity", "medium"))
        l3 = f.get("layer3_execution")
        if sev in ("critical", "high") and l3 == "unverified":
            candidates.append(f)
    candidates.sort(
        key=lambda f: (
            order.get(str(f.get("severity", "medium")), 9),
            -float(f.get("confidence") or 0.0),
        )
    )
    mark_fp = {c.get("finding_fingerprint") for c in candidates[:top_n] if c.get("finding_fingerprint")}
    out: List[dict] = []
    for f in findings:
        fp = f.get("finding_fingerprint")
        if fp and fp in mark_fp:
            g = dict(f)
            g["follow_up_recommended"] = True
            out.append(g)
        else:
            out.append(f)
    return out


def recompute_severity_counts(findings: List[dict]) -> Dict[str, int]:
    sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        sev = f.get("severity", "medium")
        if sev in sev_counts:
            sev_counts[str(sev)] += 1
    return sev_counts


def triage_top_n() -> int:
    return int(getattr(settings, "tron_deep_verify_top_n", 0) or 0)
