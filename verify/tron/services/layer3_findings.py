"""Layer 3 execution verification for in-process audit runs (AuditExecutor path)."""

from __future__ import annotations

import logging
from typing import List

from tron.schemas.verification import FindingOutput, SeverityLevel
from tron.services.sandbox_client import SandboxClient
from tron.verification.execution_verifier import (
    ExecutionVerifier,
    FindingSnapshot,
    VerificationStatus,
)


async def apply_layer3_to_findings(
    findings: List[FindingOutput],
    *,
    logger: logging.Logger | None = None,
) -> List[FindingOutput]:
    """Verify critical/high findings in sandbox; drop rejected; boost verified."""
    log = logger or logging.getLogger(__name__)
    client = SandboxClient(logger=log)
    if not client.is_available():
        log.warning("Layer 3: sandbox unavailable — skipping execution verification")
        return findings

    verifier = ExecutionVerifier(sandbox_client=client, logger=log)
    kept: List[FindingOutput] = []

    for fo in findings:
        sev = fo.severity
        if sev not in (SeverityLevel.CRITICAL, SeverityLevel.HIGH):
            kept.append(fo)
            continue

        snap = FindingSnapshot(
            category=fo.vulnerability_type.value,
            severity=sev.value,
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
                    }
                )
            )
            continue
        kept.append(fo)

    return kept
