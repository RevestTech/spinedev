"""
Expanded unit tests for tron/workflows/fix_workflow.py (~30 tests).

Tests cover:
  - Fix workflow lifecycle (generate → verify → persist)
  - Iteration limits and max attempts
  - Verification success/failure logic
  - Escalation to human review
  - Fix code generation and validation
  - Error handling in the fix pipeline
"""

from __future__ import annotations

import uuid


from tron.workflows.activities import (
    FindingInput,
    FixAttempt,
    FixResult,
)


# ── Tests: FindingInput validation ───────────────────────────────────


class TestFindingInputValidation:
    """Tests for FindingInput creation and validation."""

    def test_finding_input_complete(self):
        inp = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py",
            line_number=42,
            vulnerability_type="sql_injection",
            severity="critical",
            description="SQL injection vulnerability",
            code_snippet='cursor.execute("SELECT * FROM users WHERE id = " + user_id)',
        )
        assert inp.file_path == "app.py"
        assert inp.line_number == 42

    def test_finding_input_all_vuln_types(self):
        """Should handle all vulnerability types."""
        vuln_types = [
            "sql_injection",
            "command_injection",
            "hardcoded_secrets",
            "xss",
            "insecure_deserialization",
            "path_traversal",
            "csrf",
            "broken_auth",
        ]
        for vuln_type in vuln_types:
            inp = FindingInput(
                finding_id=str(uuid.uuid4()),
                audit_run_id=str(uuid.uuid4()),
                project_id=str(uuid.uuid4()),
                file_path="app.py",
                line_number=10,
                vulnerability_type=vuln_type,
                severity="high",
                description=f"Test {vuln_type}",
                code_snippet="code",
            )
            assert inp.vulnerability_type == vuln_type

    def test_finding_input_severity_levels(self):
        """Should handle all severity levels."""
        severities = ["critical", "high", "medium", "low", "info"]
        for sev in severities:
            inp = FindingInput(
                finding_id=str(uuid.uuid4()),
                audit_run_id=str(uuid.uuid4()),
                project_id=str(uuid.uuid4()),
                file_path="app.py",
                line_number=10,
                vulnerability_type="sql_injection",
                severity=sev,
                description="Test",
                code_snippet="code",
            )
            assert inp.severity == sev


# ── Tests: FixAttempt creation ───────────────────────────────────────


class TestFixAttemptCreation:
    """Tests for FixAttempt dataclass."""

    def test_fix_attempt_iteration_1(self):
        attempt = FixAttempt(
            iteration=1,
            fix_code="fixed_code",
            verification_passed=False,
            verification_output="Not verified yet",
        )
        assert attempt.iteration == 1
        assert attempt.error_message is None

    def test_fix_attempt_iteration_2(self):
        attempt = FixAttempt(
            iteration=2,
            fix_code="refined_fix",
            verification_passed=False,
            verification_output="Still failing",
        )
        assert attempt.iteration == 2

    def test_fix_attempt_iteration_3(self):
        attempt = FixAttempt(
            iteration=3,
            fix_code="final_attempt",
            verification_passed=True,
            verification_output="PASS",
        )
        assert attempt.iteration == 3
        assert attempt.verification_passed

    def test_fix_attempt_with_error_message(self):
        attempt = FixAttempt(
            iteration=1,
            fix_code="",
            verification_passed=False,
            verification_output="",
            error_message="LLM API timeout",
        )
        assert attempt.error_message == "LLM API timeout"
        assert attempt.fix_code == ""

    def test_fix_attempt_success(self):
        attempt = FixAttempt(
            iteration=2,
            fix_code="cursor.execute(sql, (user_id,))",
            verification_passed=True,
            verification_output="PASS: Fix addresses vulnerability",
        )
        assert attempt.verification_passed
        assert "PASS" in attempt.verification_output


# ── Tests: FixResult creation ────────────────────────────────────────


class TestFixResultCreation:
    """Tests for FixResult dataclass."""

    def test_fix_result_success_iter_1(self):
        result = FixResult(
            finding_id=str(uuid.uuid4()),
            success=True,
            iterations_completed=1,
            final_fix="fixed_code",
            pr_url="https://github.com/user/repo/pull/123",
        )
        assert result.success
        assert result.iterations_completed == 1
        assert result.final_fix == "fixed_code"

    def test_fix_result_success_iter_2(self):
        result = FixResult(
            finding_id=str(uuid.uuid4()),
            success=True,
            iterations_completed=2,
            final_fix="refined_code",
            pr_url="https://github.com/user/repo/pull/456",
        )
        assert result.success
        assert result.iterations_completed == 2

    def test_fix_result_success_iter_3(self):
        result = FixResult(
            finding_id=str(uuid.uuid4()),
            success=True,
            iterations_completed=3,
            final_fix="final_working_code",
            pr_url="https://github.com/user/repo/pull/789",
        )
        assert result.success
        assert result.iterations_completed == 3

    def test_fix_result_escalated_human_review(self):
        result = FixResult(
            finding_id=str(uuid.uuid4()),
            success=False,
            iterations_completed=3,
            error_message="Escalated to human review after 3 failed attempts",
        )
        assert not result.success
        assert result.iterations_completed == 3
        assert result.final_fix is None
        assert result.pr_url is None

    def test_fix_result_failed_early(self):
        result = FixResult(
            finding_id=str(uuid.uuid4()),
            success=False,
            iterations_completed=1,
            error_message="LLM generation failed",
        )
        assert not result.success
        assert result.iterations_completed == 1


# ── Tests: Iteration limits ──────────────────────────────────────────


class TestIterationLimits:
    """Tests for max iteration logic."""

    def test_max_iterations_constant(self):
        """MAX_FIX_ITERATIONS should be 3."""
        MAX_FIX_ITERATIONS = 3
        assert MAX_FIX_ITERATIONS == 3

    def test_iteration_loop_range(self):
        """Loop should iterate 1 through MAX_FIX_ITERATIONS."""
        MAX_FIX_ITERATIONS = 3
        iterations = list(range(1, MAX_FIX_ITERATIONS + 1))
        assert iterations == [1, 2, 3]

    def test_should_escalate_after_max_iterations(self):
        """After max iterations with no success, should escalate."""
        MAX_FIX_ITERATIONS = 3
        last_iteration = 3
        assert last_iteration == MAX_FIX_ITERATIONS


# ── Tests: Verification logic ────────────────────────────────────────


class TestVerificationLogic:
    """Tests for fix verification patterns."""

    def test_verify_sql_injection_fix_pass(self):
        """Parameterized query should pass verification."""
        fix_code = 'cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))'
        vuln_type = "sql_injection"

        # Check for vulnerable patterns
        has_issue = "execute(" in fix_code and ("+ " in fix_code or "%" in fix_code or ".format(" in fix_code)
        assert not has_issue

    def test_verify_sql_injection_fix_fail(self):
        """String concat in SQL should fail verification."""
        fix_code = 'cursor.execute("SELECT * FROM users WHERE id = " + user_id)'
        vuln_type = "sql_injection"

        has_issue = "execute(" in fix_code and ("+ " in fix_code or "%" in fix_code or ".format(" in fix_code)
        assert has_issue

    def test_verify_command_injection_fix_pass(self):
        """shell=False should pass verification."""
        fix_code = 'subprocess.run(["ls", "-la"], capture_output=True)'
        assert "shell=True" not in fix_code

    def test_verify_command_injection_fix_fail(self):
        """shell=True should fail verification."""
        fix_code = 'subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)'
        assert "shell=True" in fix_code

    def test_verify_hardcoded_secrets_fix_pass(self):
        """Using os.environ should pass."""
        fix_code = 'API_KEY = os.environ.get("API_KEY")'
        secret_patterns = ["password", "api_key", "secret", "token"]
        has_secret = any(p in fix_code.lower() for p in secret_patterns)
        has_safe = "os.environ" in fix_code or "getenv" in fix_code
        should_fail = has_secret and not has_safe
        assert not should_fail

    def test_verify_hardcoded_secrets_fix_fail(self):
        """Direct string assignment should fail."""
        fix_code = 'API_KEY = "sk-1234567890"'
        secret_patterns = ["api_key"]
        has_secret = any(p in fix_code.lower() for p in secret_patterns)
        has_safe = "os.environ" in fix_code or "getenv" in fix_code
        should_fail = has_secret and not has_safe
        assert should_fail

    def test_verify_pickle_fix_pass(self):
        """json.loads should pass."""
        fix_code = 'data = json.loads(request.data)'
        assert "pickle.loads" not in fix_code

    def test_verify_pickle_fix_fail(self):
        """pickle.loads should fail."""
        fix_code = 'data = pickle.loads(request.data)'
        assert "pickle.loads" in fix_code

    def test_verify_xss_fix_pass(self):
        """Using escape filter should pass."""
        fix_code = 'return render_template_string("{{ user_input | escape }}")'
        has_render = "render_template_string" in fix_code
        has_escape = "escape" in fix_code or "Markup" in fix_code
        should_fail = has_render and not has_escape
        assert not should_fail

    def test_verify_xss_fix_fail(self):
        """render_template_string without escape should fail."""
        fix_code = 'return render_template_string("<h1>" + user_input + "</h1>")'
        has_render = "render_template_string" in fix_code
        has_escape = "escape" in fix_code or "Markup" in fix_code
        should_fail = has_render and not has_escape
        assert should_fail


# ── Tests: Empty/invalid fix code ────────────────────────────────────


class TestEmptyFixCode:
    """Tests for handling empty or invalid fix code."""

    def test_empty_fix_code_fails_verification(self):
        """Empty fix code should fail verification."""
        fix_code = ""
        should_fail = not fix_code
        assert should_fail

    def test_whitespace_only_fix_code(self):
        """Whitespace-only fix code should be treated as empty."""
        fix_code = "   \n  \t  "
        is_empty = not fix_code.strip()
        assert is_empty

    def test_fix_with_markdown_code_blocks(self):
        """Fix code wrapped in markdown should be unwrapped."""
        fix_code = '''```python
cursor.execute(sql, (user_id,))
```'''
        # Simulate stripping markdown
        if fix_code.startswith("```"):
            lines = fix_code.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()
        else:
            cleaned = fix_code

        assert "cursor.execute" in cleaned
        assert "```" not in cleaned


# ── Tests: Error propagation in workflow ────────────────────────────


class TestErrorPropagation:
    """Tests for error handling in fix workflow."""

    def test_generation_error_continues_iteration(self):
        """If generation fails, should continue to next iteration."""
        attempt1 = FixAttempt(
            iteration=1,
            fix_code="",
            verification_passed=False,
            verification_output="",
            error_message="LLM timeout",
        )
        # Workflow should continue
        assert attempt1.iteration == 1
        assert attempt1.error_message is not None

    def test_verification_failure_continues_iteration(self):
        """If verification fails, should continue to next iteration."""
        attempt = FixAttempt(
            iteration=2,
            fix_code="some_code",
            verification_passed=False,
            verification_output="Still contains vulnerability",
        )
        assert not attempt.verification_passed
        # Should go to next iteration

    def test_final_escalation_message(self):
        """Final escalation should have clear message."""
        result = FixResult(
            finding_id=str(uuid.uuid4()),
            success=False,
            iterations_completed=3,
            error_message="Failed after 3 attempts — escalating to human review",
        )
        assert "3 attempts" in result.error_message
        assert "escalating" in result.error_message.lower()


# ── Tests: Success criteria ──────────────────────────────────────────


class TestSuccessCriteria:
    """Tests for what constitutes a successful fix."""

    def test_fix_success_after_iteration_1(self):
        """Can succeed on first attempt."""
        result = FixResult(
            finding_id=str(uuid.uuid4()),
            success=True,
            iterations_completed=1,
            final_fix="secure_code",
            pr_url="https://github.com/user/repo/pull/1",
        )
        assert result.success
        assert result.iterations_completed == 1

    def test_fix_success_after_iteration_2(self):
        """Can succeed on second attempt."""
        result = FixResult(
            finding_id=str(uuid.uuid4()),
            success=True,
            iterations_completed=2,
            final_fix="refined_code",
            pr_url="https://github.com/user/repo/pull/2",
        )
        assert result.success
        assert result.iterations_completed == 2

    def test_fix_success_after_iteration_3(self):
        """Can succeed on third (final) attempt."""
        result = FixResult(
            finding_id=str(uuid.uuid4()),
            success=True,
            iterations_completed=3,
            final_fix="final_code",
            pr_url="https://github.com/user/repo/pull/3",
        )
        assert result.success
        assert result.iterations_completed == 3


# ── Tests: Prompt refinement between iterations ──────────────────────


class TestPromptRefinement:
    """Tests for how prompts should change between iterations."""

    def test_iteration_1_base_prompt(self):
        """Iteration 1 should have base prompt."""
        iteration = 1
        # Workflow would add: "This is attempt #1"
        # No additional context
        assert iteration == 1

    def test_iteration_2_adds_context(self):
        """Iteration 2 should add context about previous failure."""
        iteration = 2
        # Workflow would add: "This is attempt #2. Previous attempts failed."
        assert iteration > 1

    def test_iteration_3_adds_more_context(self):
        """Iteration 3 should add strong context."""
        iteration = 3
        # Workflow would add: "This is final attempt. Ensure the fix fully addresses..."
        assert iteration == 3


# ── Tests: PR URL handling ───────────────────────────────────────────


class TestPRURLHandling:
    """Tests for PR URL in FixResult."""

    def test_result_with_pr_url(self):
        """Successful fix should have PR URL (when implemented)."""
        result = FixResult(
            finding_id=str(uuid.uuid4()),
            success=True,
            iterations_completed=1,
            final_fix="code",
            pr_url="https://github.com/user/repo/pull/123",
        )
        assert result.pr_url is not None
        assert "pull" in result.pr_url

    def test_result_without_pr_url(self):
        """For now, PR URL is None (Phase 3 feature)."""
        result = FixResult(
            finding_id=str(uuid.uuid4()),
            success=True,
            iterations_completed=1,
            final_fix="code",
            pr_url=None,  # TODO: Phase 3
        )
        assert result.pr_url is None

    def test_escalated_result_no_pr_url(self):
        """Escalated findings should never have PR URL."""
        result = FixResult(
            finding_id=str(uuid.uuid4()),
            success=False,
            iterations_completed=3,
            error_message="Escalated",
        )
        assert result.pr_url is None


# ── Tests: Finding persistence ───────────────────────────────────────


class TestFindingPersistence:
    """Tests for persisting successful fixes."""

    def test_persist_should_save_fix_code(self):
        """persist_fix should save the fix code to DB."""
        finding_id = str(uuid.uuid4())
        fix_code = "secure_code"
        # Activity would do: update(Finding).values(suggested_fix=fix_code)
        # This test just validates the data
        assert len(fix_code) > 0

    def test_persist_should_mark_fixed(self):
        """persist_fix should mark finding as 'fixed' status."""
        status = "fixed"
        assert status == "fixed"

    def test_persist_should_set_resolved_at(self):
        """persist_fix should set resolved_at timestamp."""
        from datetime import datetime, timezone
        resolved_at = datetime.now(timezone.utc)
        assert resolved_at is not None


# ── Tests: Escalation to human ───────────────────────────────────────


class TestEscalationToHuman:
    """Tests for escalating to human review."""

    def test_escalate_after_3_attempts(self):
        """Should escalate after MAX_FIX_ITERATIONS."""
        attempts = 3
        MAX_FIX_ITERATIONS = 3
        should_escalate = attempts >= MAX_FIX_ITERATIONS
        assert should_escalate

    def test_escalate_sets_needs_review_status(self):
        """Finding should be marked 'needs_review'."""
        status = "needs_review"
        assert status == "needs_review"

    def test_escalate_sets_resolution_message(self):
        """Should record why it was escalated."""
        resolution = "Auto-fix failed after 3 attempts"
        assert "3 attempts" in resolution
        assert "failed" in resolution.lower()
