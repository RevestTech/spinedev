"""Layer 3 execution verification for in-process audit runs (AuditExecutor path)."""

from __future__ import annotations

import logging
from typing import List, Set

from tron.schemas.verification import FindingOutput, SeverityLevel
from tron.services.sandbox_client import SandboxClient
from tron.verification.execution_verifier import (
    ExecutionVerifier,
    FindingSnapshot,
    VerificationStatus,
)


def _with_layer3(fo: FindingOutput, layer3_execution: str) -> FindingOutput:
    return fo.model_copy(update={"layer3_execution": layer3_execution})


async def apply_layer3_to_findings(
    findings: List[FindingOutput],
    *,
    logger: logging.Logger | None = None,
) -> List[FindingOutput]:
    """Verify critical/high findings in sandbox; drop rejected; boost verified.

    Sets ``layer3_execution`` on each retained finding: not_applicable (lower
    severities), verified, unverified, or skipped when sandbox is unavailable.
    """
    log = logger or logging.getLogger(__name__)
    client = SandboxClient(logger=log)
    if not client.is_available():
        log.warning("Layer 3: sandbox unavailable — skipping execution verification")
        return [
            _with_layer3(
                fo,
                "skipped"
                if fo.severity in (SeverityLevel.CRITICAL, SeverityLevel.HIGH)
                else "not_applicable",
            )
            for fo in findings
        ]

    verifier = ExecutionVerifier(sandbox_client=client, logger=log)
    kept: List[FindingOutput] = []

    for fo in findings:
        if fo.severity not in (SeverityLevel.CRITICAL, SeverityLevel.HIGH):
            kept.append(_with_layer3(fo, "not_applicable"))
            continue

        snap = FindingSnapshot(
            category=fo.vulnerability_type.value,
            severity=fo.severity.value,
            title="",
            description=fo.description,
            file_path=fo.file_path,
            line_number=fo.line_number,
            code_snippet=fo.code_snippet,
            confidence=fo.confidence,
        )
        result = await verifier.verify_finding(snap)

        if result.status == VerificationStatus.REJECTED:
            log.info(
                "Layer 3: rejected finding %s:%s — %s",
                fo.file_path,
                fo.line_number,
                result.reason,
            )
            continue
        if result.status == VerificationStatus.VERIFIED:
            new_conf = min(1.0, fo.confidence + result.confidence_adjustment)
            kept.append(
                fo.model_copy(
                    update={
                        "confidence": new_conf,
                        "deterministic_tool_confirmed": True,
                        "layer3_execution": "verified",
                    }
                )
            )
            continue
        # UNVERIFIED or SKIPPED (e.g. no test for category): still in play, not proven
        kept.append(_with_layer3(fo, "unverified"))

    return kept


async def apply_deep_verify_retry_pass_to_outputs(
    findings: List[FindingOutput],
    *,
    logger: logging.Logger | None = None,
    top_n: int,
) -> List[FindingOutput]:
    """SEC-5: optional second sandbox attempt for top-N critical/high findings still unverified."""
    log = logger or logging.getLogger(__name__)
    if top_n <= 0:
        return findings

    client = SandboxClient(logger=log)
    if not client.is_available():
        return findings

    verifier = ExecutionVerifier(sandbox_client=client, logger=log)

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
        and str(f.layer3_execution or "").lower() == "unverified"
    ]
    candidates.sort(
        key=lambda f: (order.get(f.severity, 9), -float(f.confidence or 0.0))
    )
    targets = candidates[:top_n]
    if not targets:
        return findings

    target_fps: Set[str] = {t.finding_fingerprint for t in targets}
    retry_used: Set[str] = set()

    out: List[FindingOutput] = []
    for fo in findings:
        fp = fo.finding_fingerprint
        if fp not in target_fps:
            out.append(fo)
            continue
        if fp in retry_used:
            out.append(fo)
            continue
        retry_used.add(fp)

        snap = FindingSnapshot(
            category=fo.vulnerability_type.value,
            severity=fo.severity.value,
            title="",
            description=fo.description,
            file_path=fo.file_path,
            line_number=fo.line_number,
            code_snippet=fo.code_snippet,
            confidence=fo.confidence,
        )
        result = await verifier.verify_finding(snap)

        if result.status == VerificationStatus.REJECTED:
            log.info(
                "SEC-5 deep verify: rejected %s:%s — %s",
                fo.file_path,
                fo.line_number,
                result.reason,
            )
            continue
        if result.status == VerificationStatus.VERIFIED:
            new_conf = min(1.0, fo.confidence + result.confidence_adjustment)
            out.append(
                fo.model_copy(
                    update={
                        "confidence": new_conf,
                        "deterministic_tool_confirmed": True,
                        "layer3_execution": "verified",
                    }
                )
            )
            continue

        out.append(fo)

    return out
