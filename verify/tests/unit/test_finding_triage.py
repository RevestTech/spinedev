from tron.schemas.verification import (
    CrossValidationStatus,
    FindingOutput,
    SeverityLevel,
    VulnerabilityType,
)
from tron.services.finding_triage import (
    apply_follow_up_flags_to_outputs,
    apply_path_role_to_outputs,
    filter_findings_by_suppression,
)


def _fo(fp: str, sev: SeverityLevel, l3: str | None) -> FindingOutput:
    return FindingOutput(
        vulnerability_type=VulnerabilityType.OTHER,
        severity=sev,
        file_path="a.py",
        line_number=1,
        line_end=1,
        code_snippet="x",
        description="d",
        deterministic_tool_confirmed=False,
        confidence=0.5,
        confirming_tools=[],
        cross_validation_status=CrossValidationStatus.PENDING,
        layer3_execution=l3,
        agent_id="a",
        blueprint_id="b",
        finding_fingerprint=fp,
    )


def test_filter_suppression() -> None:
    a = _fo("aa", SeverityLevel.LOW, None)
    b = _fo("bb", SeverityLevel.LOW, None)
    out = filter_findings_by_suppression([a, b], {"aa"})
    assert len(out) == 1
    assert out[0].finding_fingerprint == "bb"


def test_path_role_tag() -> None:
    a = _fo("1", SeverityLevel.HIGH, None)
    a = a.model_copy(update={"file_path": "tests/t.py"})
    out = apply_path_role_to_outputs([a], ["**/tests/**"])
    assert out[0].path_role == "test"


def test_follow_up_top_n() -> None:
    f1 = _fo("a", SeverityLevel.CRITICAL, "unverified")
    f2 = _fo("b", SeverityLevel.CRITICAL, "unverified")
    out = apply_follow_up_flags_to_outputs([f1, f2], 1)
    marked = [f for f in out if f.follow_up_recommended]
    assert len(marked) == 1
