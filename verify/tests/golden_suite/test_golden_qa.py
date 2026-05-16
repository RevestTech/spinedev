"""
Golden Test Suite for QAISO Agent

This module contains regression tests that verify QAISO correctly detects
test quality issues and coverage gaps. Tests use mock LLM responses to
ensure determinism — no real LLM calls.

Test quality issues tested:
- Dead tests (skipped, never run)
- Missing assertions or empty test bodies
- Test isolation issues (shared state)
- Flaky test patterns (timeouts, hardcoded timing)
- Missing edge case coverage
- Slow/resource-intensive tests
- Coverage gaps in critical code

Each test:
1. Constructs a mock LLM response representing test quality analysis
2. Calls QAISO._parse_llm_response()
3. Asserts the correct finding type, severity, and description
"""

import pytest
import json
from unittest.mock import Mock

from tron.agents.qa_iso import QAISO, QA_VULN_TYPE_MAP
from tron.schemas.verification import (
    Blueprint,
    BlueprintScope,
    VulnerabilityType,
    SeverityLevel,
)


# Fixtures

@pytest.fixture
def mock_llm_client():
    """Mock LLM client that doesn't make real API calls"""
    return Mock()


@pytest.fixture
def qa_iso(mock_llm_client):
    """Create QAISO agent with mocked LLM"""
    from tron.agents.base import ISOConfig, ISOSpecialization, LLMProvider

    config = ISOConfig(
        specialization=ISOSpecialization.QA,
        agent_id="test-qa-iso",
        model_provider=LLMProvider.ANTHROPIC,
        model_name="claude-haiku-4-5-20251001",
    )

    iso = QAISO(
        config=config,
        secrets={"llm/anthropic-key": "test-key"},
        llm_client=mock_llm_client,
    )
    return iso


@pytest.fixture
def test_blueprint():
    """Create a test blueprint for QA analysis"""
    return Blueprint(
        id="golden-test-qa-blueprint",
        name="Golden Suite QA Test",
        description="Test blueprint for golden suite QA issues",
        scope=BlueprintScope(
            file_patterns=["test_*.py", "*_test.py"],
            check_types=[VulnerabilityType.OTHER],
            languages=["python"],
        ),
    )


# ============================================================================
# Dead Test Tests
# ============================================================================

class TestGoldenDeadTests:
    """Golden tests for dead test detection"""

    def test_skipped_test_never_runs(self, qa_iso, test_blueprint):
        """MUST detect permanently skipped tests"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "dead_test",
                "severity": "high",
                "file_path": "tests/test_auth.py",
                "line_number": 42,
                "code_snippet": "@pytest.mark.skip(reason='TODO: implement')\ndef test_login_with_ldap():\n    pass",
                "description": "Test permanently skipped — dead code, never runs, coverage gap",
                "fix_suggestion": "Either implement the test or remove it; if blocked, create a GitHub issue and link it",
                "confidence": 0.98,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.HIGH
        assert "dead_test" in findings[0].description.lower()

    def test_conditional_skip_based_on_flag(self, qa_iso, test_blueprint):
        """MUST detect tests skipped based on environment flags"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "dead_test",
                "severity": "high",
                "file_path": "tests/test_integration.py",
                "line_number": 58,
                "code_snippet": "@pytest.mark.skipif(SKIP_SLOW_TESTS, reason='Performance check')\ndef test_large_dataset_processing():\n    pass",
                "description": "Test conditionally skipped — if SKIP_SLOW_TESTS=True, test never runs and coverage gap remains",
                "fix_suggestion": "Split into separate test suite; use markers instead of skipif",
                "confidence": 0.85,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1


# ============================================================================
# Missing Assertions Tests
# ============================================================================

class TestGoldenMissingAssertions:
    """Golden tests for missing assertion detection"""

    def test_test_with_no_assertions(self, qa_iso, test_blueprint):
        """MUST detect test with no assertions"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "missing_assertions",
                "severity": "critical",
                "file_path": "tests/test_models.py",
                "line_number": 74,
                "code_snippet": "def test_user_creation():\n    user = User(name='Alice')\n    user.save()\n    # No assertion!",
                "description": "Test function with no assertions — doesn't actually verify anything",
                "fix_suggestion": "Add assertions: assert user.id is not None; assert user.name == 'Alice'",
                "confidence": 0.99,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.CRITICAL

    def test_test_only_checks_no_exception(self, qa_iso, test_blueprint):
        """MUST detect tests that only verify code doesn't crash"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "missing_assertions",
                "severity": "high",
                "file_path": "tests/test_api.py",
                "line_number": 89,
                "code_snippet": "def test_api_call():\n    response = api.get_user(123)  # Only checking it doesn't raise\n    # No assertion on response content!",
                "description": "Test only verifies no exception — doesn't check if result is correct",
                "fix_suggestion": "Add assertions: assert response.status_code == 200; assert response.json()['id'] == 123",
                "confidence": 0.96,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1


# ============================================================================
# Test Isolation Tests
# ============================================================================

class TestGoldenTestIsolation:
    """Golden tests for test isolation issue detection"""

    def test_shared_mutable_state(self, qa_iso, test_blueprint):
        """MUST detect shared mutable state between tests"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "test_isolation",
                "severity": "high",
                "file_path": "tests/test_cache.py",
                "line_number": 103,
                "code_snippet": "SHARED_CACHE = {}  # Module-level, shared across tests\n\ndef test_cache_set():\n    SHARED_CACHE['key'] = 'value'\n\ndef test_cache_get():\n    # Depends on test_cache_set running first!",
                "description": "Tests share mutable module-level state — test order dependency, non-hermetic",
                "fix_suggestion": "Use fixtures to initialize state: @pytest.fixture def cache(): return {}",
                "confidence": 0.93,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.HIGH

    def test_database_state_not_reset(self, qa_iso, test_blueprint):
        """MUST detect database state not reset between tests"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "test_isolation",
                "severity": "critical",
                "file_path": "tests/test_database.py",
                "line_number": 118,
                "code_snippet": "def test_user_creation():\n    User.objects.create(name='Alice')\n\ndef test_user_list():\n    # Expects only new user, but previous test's Alice is still there",
                "description": "Database not cleaned between tests — tests depend on execution order",
                "fix_suggestion": "Add @pytest.fixture(autouse=True) to clear DB or use transactions: def db_reset(db): db.rollback()",
                "confidence": 0.97,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1


# ============================================================================
# Flaky Test Pattern Tests
# ============================================================================

class TestGoldenFlakyPatterns:
    """Golden tests for flaky test pattern detection"""

    def test_hardcoded_sleep_time(self, qa_iso, test_blueprint):
        """MUST detect hardcoded sleep times that can be flaky"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "flaky_test_pattern",
                "severity": "high",
                "file_path": "tests/test_async.py",
                "line_number": 133,
                "code_snippet": "def test_async_operation():\n    asyncio.run(operation())\n    time.sleep(0.5)  # Hardcoded timeout\n    assert result_ready",
                "description": "Hardcoded sleep time can be flaky — too short on slow machines, too long on fast",
                "fix_suggestion": "Use wait_for with exponential backoff or pytest-timeout plugin",
                "confidence": 0.89,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.HIGH

    def test_random_data_without_seed(self, qa_iso, test_blueprint):
        """MUST detect tests using random data without seed"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "flaky_test_pattern",
                "severity": "medium",
                "file_path": "tests/test_shuffle.py",
                "line_number": 148,
                "code_snippet": "def test_shuffle():\n    data = list(range(100))\n    random.shuffle(data)  # No seed!\n    assert data[0] == 50  # Randomly fails",
                "description": "Test uses random data without setting seed — test becomes flaky",
                "fix_suggestion": "Set seed: random.seed(42) or use @pytest.mark.seed(42)",
                "confidence": 0.94,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1

    def test_race_condition_in_test(self, qa_iso, test_blueprint):
        """MUST detect potential race conditions in tests"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "flaky_test_pattern",
                "severity": "high",
                "file_path": "tests/test_threading.py",
                "line_number": 163,
                "code_snippet": "def test_concurrent_writes():\n    threads = [Thread(target=write_data) for _ in range(10)]\n    for t in threads: t.start()\n    assert data == expected  # Race condition: might run before writes complete",
                "description": "Test has race condition — doesn't wait for threads before asserting",
                "fix_suggestion": "Wait for all threads: for t in threads: t.join()",
                "confidence": 0.96,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1


# ============================================================================
# Missing Edge Cases Tests
# ============================================================================

class TestGoldenMissingEdgeCases:
    """Golden tests for missing edge case coverage"""

    def test_no_boundary_value_testing(self, qa_iso, test_blueprint):
        """MUST detect missing boundary value tests"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "missing_edge_cases",
                "severity": "medium",
                "file_path": "tests/test_validation.py",
                "line_number": 178,
                "code_snippet": "def test_valid_age():\n    assert validate_age(25) == True  # Only tests happy path",
                "description": "No tests for edge cases: min (0), max (150), negative, null",
                "fix_suggestion": "Add: test_age_zero(), test_age_negative(), test_age_over_max(), test_age_none()",
                "affected_source_files": "[\"validators.py\"]",
                "confidence": 0.82,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.MEDIUM

    def test_no_error_path_coverage(self, qa_iso, test_blueprint):
        """MUST detect missing error path tests"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "missing_edge_cases",
                "severity": "high",
                "file_path": "tests/test_errors.py",
                "line_number": 193,
                "code_snippet": "def test_parse_json():\n    result = parse_json('{\"key\": \"value\"}')\n    assert result['key'] == 'value'  # Only success path",
                "description": "No tests for error cases: malformed JSON, empty string, null",
                "fix_suggestion": "Add: test_parse_json_malformed(), test_parse_json_empty(), test_parse_json_null()",
                "affected_source_files": "[\"parsers.py\"]",
                "confidence": 0.88,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)
        assert len(findings) == 1


# ============================================================================
# Coverage Gap Tests
# ============================================================================

class TestGoldenCoverageGaps:
    """Golden tests for untested critical code paths"""

    def test_critical_business_logic_uncovered(self, qa_iso, test_blueprint):
        """MUST detect critical code paths with no tests"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "incomplete_coverage",
                "severity": "critical",
                "file_path": "tests/test_billing.py",
                "line_number": 208,
                "code_snippet": "def test_subscription_renewal():\n    sub = create_subscription()\n    # Code path for 'insufficient funds' exception never tested",
                "description": "Critical billing code for insufficient funds has 0% test coverage",
                "fix_suggestion": "Add test_subscription_renewal_insufficient_funds() with mocked payment failure",
                "affected_source_files": "[\"billing.py\"]",
                "confidence": 0.92,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.CRITICAL


# ============================================================================
# Slow Test Tests
# ============================================================================

class TestGoldenSlowTests:
    """Golden tests for slow/resource-intensive tests"""

    def test_slow_integration_test(self, qa_iso, test_blueprint):
        """MUST detect unnecessarily slow tests"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "slow_test",
                "severity": "medium",
                "file_path": "tests/test_integration.py",
                "line_number": 223,
                "code_snippet": "def test_api_integration():\n    # Makes 50 real HTTP requests, takes 30 seconds\n    for i in range(50):\n        requests.get(f'https://api.example.com/resource/{i}')",
                "description": "Test makes real HTTP calls, takes 30+ seconds — should use mocks",
                "fix_suggestion": "Mock HTTP responses: @patch('requests.get') or use responses library",
                "confidence": 0.90,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.MEDIUM


# ============================================================================
# Duplicate Test Tests
# ============================================================================

class TestGoldenDuplicateTests:
    """Golden tests for duplicate/redundant tests"""

    def test_identical_test_bodies(self, qa_iso, test_blueprint):
        """MUST detect near-identical tests"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "duplicate_test",
                "severity": "low",
                "file_path": "tests/test_users.py",
                "line_number": 238,
                "code_snippet": "def test_user_name():\n    user = User(name='Alice')\n    assert user.name == 'Alice'\n\ndef test_user_full_name():\n    user = User(name='Alice')  # Identical except variable name\n    assert user.name == 'Alice'",
                "description": "Tests are nearly identical — one is redundant",
                "fix_suggestion": "Consolidate into parameterized test: @pytest.mark.parametrize('name', ['Alice', 'Bob'])",
                "confidence": 0.87,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 1


# ============================================================================
# Clean Test Suite Tests
# ============================================================================

class TestGoldenCleanTestSuite:
    """Golden tests for clean test suites with no issues"""

    def test_clean_test_suite_no_issues(self, qa_iso, test_blueprint):
        """Clean test suite returns no findings"""
        mock_response = json.dumps([])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 0

    def test_well_covered_module_no_gaps(self, qa_iso, test_blueprint):
        """Well-covered module returns no findings"""
        mock_response = json.dumps([])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 0


# ============================================================================
# Integration Tests
# ============================================================================

class TestGoldenQAIntegration:
    """Integration tests with multiple QA issues"""

    def test_multiple_qa_issues(self, qa_iso, test_blueprint):
        """MUST handle multiple QA issues in same response"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "dead_test",
                "severity": "high",
                "file_path": "tests/test_auth.py",
                "line_number": 10,
                "code_snippet": "@pytest.mark.skip\ndef test_ldap_auth(): pass",
                "confidence": 0.98,
            },
            {
                "vulnerability_type": "other",
                "qa_category": "missing_assertions",
                "severity": "critical",
                "file_path": "tests/test_auth.py",
                "line_number": 20,
                "code_snippet": "def test_login(): auth.login('user')",
                "confidence": 0.99,
            },
            {
                "vulnerability_type": "other",
                "qa_category": "test_isolation",
                "severity": "high",
                "file_path": "tests/test_auth.py",
                "line_number": 30,
                "code_snippet": "SHARED_DB = {}",
                "confidence": 0.93,
            },
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 3
        severities = [f.severity for f in findings]
        assert SeverityLevel.CRITICAL in severities

    def test_qa_findings_capped_at_0_7(self, qa_iso, test_blueprint):
        """QA findings must be capped at 0.7 confidence (LLM-only)"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "dead_test",
                "severity": "high",
                "file_path": "tests/test.py",
                "line_number": 10,
                "code_snippet": "@skip\ndef test(): pass",
                "confidence": 0.99,  # Try to exceed cap
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 1
        assert findings[0].confidence <= 0.7

    def test_qa_findings_all_marked_unconfirmed(self, qa_iso, test_blueprint):
        """All QA findings should be marked as not tool-confirmed"""
        mock_response = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "missing_assertions",
                "severity": "critical",
                "file_path": "tests/test.py",
                "line_number": 10,
                "code_snippet": "def test(): pass",
                "confidence": 0.7,
            }
        ])

        findings = qa_iso._parse_llm_response(mock_response, test_blueprint)

        assert len(findings) == 1
        assert findings[0].deterministic_tool_confirmed is False
