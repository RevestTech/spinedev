"""Unit tests for Layer 3 finding tagging (layer3_execution)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tron.schemas.verification import (
    CrossValidationStatus,
    FindingOutput,
    SeverityLevel,
    VulnerabilityType,
)
from tron.services import layer3_findings as l3mod
from tron.verification.execution_verifier import (
    VerificationResult,
    VerificationStatus,
)


def _fo(
    *,
    severity: SeverityLevel = SeverityLevel.MEDIUM,
    line: int = 1,
    vuln: VulnerabilityType = VulnerabilityType.OTHER,
) -> FindingOutput:
    return FindingOutput(
        vulnerability_type=vuln,
        severity=severity,
        file_path="a.py",
        line_number=line,
        code_snippet="x = 1",
        description="test",
        confidence=0.5,
        deterministic_tool_confirmed=False,
        cross_validation_status=CrossValidationStatus.PENDING,
        agent_id="test",
        blueprint_id="bp",
        finding_fingerprint=f"fp-{line}",
    )


@pytest.mark.asyncio
async def test_layer3_sandbox_unavailable_marks_severities():
    with patch.object(l3mod.SandboxClient, "is_available", return_value=False):
        low = _fo(severity=SeverityLevel.LOW)
        crit = _fo(severity=SeverityLevel.CRITICAL, line=2)
        out = await l3mod.apply_layer3_to_findings([low, crit], logger=None)
    assert len(out) == 2
    assert out[0].layer3_execution == "not_applicable"
    assert out[1].layer3_execution == "skipped"


@pytest.mark.asyncio
async def test_layer3_rejected_finding_dropped():
    crit = _fo(severity=SeverityLevel.CRITICAL)
    rej = VerificationResult(
        status=VerificationStatus.REJECTED,
        method="test",
        confidence_adjustment=0.0,
        reason="fp",
    )
    with patch.object(l3mod.SandboxClient, "is_available", return_value=True):
        with patch.object(
            l3mod.ExecutionVerifier, "verify_finding", new=AsyncMock(return_value=rej)
        ):
            out = await l3mod.apply_layer3_to_findings([crit], logger=None)
    assert out == []


@pytest.mark.asyncio
async def test_layer3_verified_marks_and_boosts_confidence():
    crit = _fo(severity=SeverityLevel.CRITICAL, line=3)
    ok = VerificationResult(
        status=VerificationStatus.VERIFIED,
        method="t",
        confidence_adjustment=0.1,
        reason="ok",
    )
    with patch.object(l3mod.SandboxClient, "is_available", return_value=True):
        with patch.object(
            l3mod.ExecutionVerifier, "verify_finding", new=AsyncMock(return_value=ok)
        ):
            out = await l3mod.apply_layer3_to_findings([crit], logger=None)
    assert len(out) == 1
    assert out[0].layer3_execution == "verified"
    assert out[0].deterministic_tool_confirmed is True
    assert out[0].confidence == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_deep_verify_skips_when_top_n_zero():
    crit = _fo(severity=SeverityLevel.CRITICAL)
    crit = crit.model_copy(update={"layer3_execution": "unverified"})
    out = await l3mod.apply_deep_verify_retry_pass_to_outputs(
        [crit], logger=None, top_n=0
    )
    assert out[0].layer3_execution == "unverified"


@pytest.mark.asyncio
async def test_deep_verify_upgrades_unverified_to_verified():
    crit = _fo(severity=SeverityLevel.CRITICAL, line=9)
    crit = crit.model_copy(update={"layer3_execution": "unverified"})
    ok = VerificationResult(
        status=VerificationStatus.VERIFIED,
        method="retry",
        confidence_adjustment=0.05,
        reason="ok",
    )
    with patch.object(l3mod.SandboxClient, "is_available", return_value=True):
        with patch.object(
            l3mod.ExecutionVerifier, "verify_finding", new=AsyncMock(return_value=ok)
        ):
            out = await l3mod.apply_deep_verify_retry_pass_to_outputs(
                [crit], logger=None, top_n=5
            )
    assert len(out) == 1
    assert out[0].layer3_execution == "verified"
    assert out[0].deterministic_tool_confirmed is True
