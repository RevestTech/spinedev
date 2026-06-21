"""Layer 5 NOT_IN_SCOPE enforcement tests.

The Blueprint's ``scope.file_patterns`` and ``scope.check_types`` shape
prompts up-front, but LLMs occasionally return findings outside that
declared scope. ``AuditManager._apply_blueprint_scope_filter`` is the
post-process gate that drops them.

These tests exercise the filter in isolation — no agents, no LLM calls.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tron.agents.manager import AuditManager
from tron.schemas.verification import (
    Blueprint,
    BlueprintScope,
    FindingBatch,
    FindingOutput,
    SeverityLevel,
    VerificationMethod,
    VulnerabilityType,
)


def _make_blueprint(
    *,
    bp_id: str,
    file_patterns: list[str],
    check_types: list[VulnerabilityType],
) -> Blueprint:
    return Blueprint(
        id=bp_id,
        name=f"bp-{bp_id}",
        description="test blueprint",
        scope=BlueprintScope(
            file_patterns=file_patterns,
            check_types=check_types,
            languages=["python"],
        ),
        verification_method=VerificationMethod.DETERMINISTIC_CROSSCHECK,
    )


def _make_finding(
    *,
    file_path: str,
    vuln_type: VulnerabilityType = VulnerabilityType.SQL_INJECTION,
    blueprint_id: str = "test-bp",
) -> FindingOutput:
    return FindingOutput(
        id=str(uuid4()),
        title="test finding",
        agent_id="test-agent",
        blueprint_id=blueprint_id,
        finding_fingerprint=f"fp-{uuid4().hex[:8]}",
        file_path=file_path,
        line_number=1,
        vulnerability_type=vuln_type,
        severity=SeverityLevel.HIGH,
        confidence=0.5,
        description="test",
        code_snippet="x = 1",
        fix_suggestion="fix",
        deterministic_tool_confirmed=False,
    )


def _make_batch(blueprint_id: str, findings: list[FindingOutput]) -> FindingBatch:
    return FindingBatch(
        blueprint_id=blueprint_id,
        agent_id="test-agent",
        findings=findings,
        total_files_scanned=1,
        execution_duration_seconds=0.1,
    )


@pytest.fixture
def manager():
    # _apply_blueprint_scope_filter is a pure method on AuditManager;
    # constructing the manager doesn't touch agents/LLMs/DB but the
    # constructor does require a secrets dict for plumbing reasons.
    return AuditManager(secrets={})


# ── File-pattern enforcement ─────────────────────────────────────────────


class TestFilePatternScope:
    def test_matching_pattern_is_kept(self, manager):
        bp = _make_blueprint(bp_id="bp1", file_patterns=["*.py"], check_types=[])
        batch = _make_batch("bp1", [_make_finding(file_path="src/app.py")])

        dropped = manager._apply_blueprint_scope_filter([batch], {"bp1": bp})
        assert dropped == 0
        assert len(batch.findings) == 1

    def test_off_pattern_is_dropped(self, manager):
        bp = _make_blueprint(bp_id="bp1", file_patterns=["*.py"], check_types=[])
        batch = _make_batch(
            "bp1",
            [
                _make_finding(file_path="src/app.py"),    # in scope
                _make_finding(file_path="src/app.js"),    # NOT in scope
                _make_finding(file_path="dist/build.css"),  # NOT in scope
            ],
        )

        dropped = manager._apply_blueprint_scope_filter([batch], {"bp1": bp})
        assert dropped == 2
        assert len(batch.findings) == 1
        assert batch.findings[0].file_path == "src/app.py"

    def test_nested_path_matches_via_double_glob(self, manager):
        # ``**/`` is the universal "any depth prefix" glob — fnmatch
        # treats single ``*`` as not crossing path separators.
        bp = _make_blueprint(bp_id="bp1", file_patterns=["*.py"], check_types=[])
        batch = _make_batch("bp1", [_make_finding(file_path="src/deep/nested/file.py")])

        dropped = manager._apply_blueprint_scope_filter([batch], {"bp1": bp})
        assert dropped == 0
        assert len(batch.findings) == 1

    def test_empty_pattern_list_means_unconstrained(self, manager):
        # No patterns → no file-path constraint. Every file passes.
        bp = _make_blueprint(bp_id="bp1", file_patterns=[], check_types=[])
        batch = _make_batch(
            "bp1",
            [
                _make_finding(file_path="x.py"),
                _make_finding(file_path="y.go"),
                _make_finding(file_path="z.rs"),
            ],
        )

        dropped = manager._apply_blueprint_scope_filter([batch], {"bp1": bp})
        assert dropped == 0
        assert len(batch.findings) == 3


# ── Vulnerability-type enforcement ───────────────────────────────────────


class TestVulnTypeScope:
    def test_in_scope_type_is_kept(self, manager):
        bp = _make_blueprint(
            bp_id="bp1",
            file_patterns=["*.py"],
            check_types=[VulnerabilityType.SQL_INJECTION],
        )
        batch = _make_batch(
            "bp1",
            [_make_finding(file_path="x.py", vuln_type=VulnerabilityType.SQL_INJECTION)],
        )

        dropped = manager._apply_blueprint_scope_filter([batch], {"bp1": bp})
        assert dropped == 0
        assert len(batch.findings) == 1

    def test_off_topic_type_is_dropped(self, manager):
        # Blueprint asks for SQLi only; agent returns XSS too. Drop it.
        bp = _make_blueprint(
            bp_id="bp1",
            file_patterns=["*.py"],
            check_types=[VulnerabilityType.SQL_INJECTION],
        )
        batch = _make_batch(
            "bp1",
            [
                _make_finding(file_path="x.py", vuln_type=VulnerabilityType.SQL_INJECTION),
                _make_finding(file_path="x.py", vuln_type=VulnerabilityType.XSS),
            ],
        )

        dropped = manager._apply_blueprint_scope_filter([batch], {"bp1": bp})
        assert dropped == 1
        assert len(batch.findings) == 1
        assert batch.findings[0].vulnerability_type == VulnerabilityType.SQL_INJECTION

    def test_empty_check_types_means_unconstrained(self, manager):
        bp = _make_blueprint(bp_id="bp1", file_patterns=["*.py"], check_types=[])
        batch = _make_batch(
            "bp1",
            [
                _make_finding(file_path="x.py", vuln_type=VulnerabilityType.SQL_INJECTION),
                _make_finding(file_path="x.py", vuln_type=VulnerabilityType.XSS),
                _make_finding(file_path="x.py", vuln_type=VulnerabilityType.OTHER),
            ],
        )

        dropped = manager._apply_blueprint_scope_filter([batch], {"bp1": bp})
        assert dropped == 0
        assert len(batch.findings) == 3


# ── Multi-batch + missing-blueprint behaviour ────────────────────────────


class TestMultiBatch:
    def test_each_batch_uses_its_own_scope(self, manager):
        bp_py = _make_blueprint(bp_id="py", file_patterns=["*.py"], check_types=[])
        bp_js = _make_blueprint(bp_id="js", file_patterns=["*.js"], check_types=[])

        py_batch = _make_batch(
            "py",
            [
                _make_finding(file_path="x.py"),    # ok
                _make_finding(file_path="x.js"),    # NOT in py scope
            ],
        )
        js_batch = _make_batch(
            "js",
            [
                _make_finding(file_path="y.js"),    # ok
                _make_finding(file_path="y.py"),    # NOT in js scope
            ],
        )

        dropped = manager._apply_blueprint_scope_filter(
            [py_batch, js_batch], {"py": bp_py, "js": bp_js}
        )
        assert dropped == 2
        assert [f.file_path for f in py_batch.findings] == ["x.py"]
        assert [f.file_path for f in js_batch.findings] == ["y.js"]

    def test_unknown_blueprint_skips_filter_for_that_batch(self, manager, caplog):
        # Orchestration drift: a batch references a Blueprint that wasn't
        # passed in. We log loudly and keep the findings — better noisy
        # than silently dropping data.
        batch = _make_batch(
            "ghost-bp",
            [_make_finding(file_path="anywhere.go"), _make_finding(file_path="other.rs")],
        )

        dropped = manager._apply_blueprint_scope_filter([batch], {})
        assert dropped == 0
        assert len(batch.findings) == 2  # nothing dropped
        # Warning logged about the missing Blueprint id
        assert any(
            "ghost-bp" in r.message for r in caplog.records if r.levelname == "WARNING"
        )
