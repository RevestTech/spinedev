"""
QAISO — Test coverage and quality analysis ISO agent.

Analyzes test suites for coverage gaps, test quality issues, dead tests,
missing assertions, flaky patterns, and isolated test problems. Runs
deterministic regex checks before LLM analysis.

Architecture ref: docs/architecture/AI_AGENT_ARCHITECTURE.md §1.3
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional
from uuid import uuid4

from tron.agents.base import (
    BaseISO,
    ISOConfig,
    ISOSpecialization,
    LLMProvider,
    ToolResult,
)
from tron.infra.llm.client import LLMClient, LLMMessage, LLMRequest
from tron.schemas.verification import (
    Blueprint,
    CrossValidationStatus,
    FindingOutput,
    SeverityLevel,
    VulnerabilityType,
)

logger = logging.getLogger(__name__)


# QA issue types mapped to VulnerabilityType
# Most QA issues map to OTHER since the enum is security-focused
QA_VULN_TYPE_MAP = {
    "dead_test": VulnerabilityType.OTHER,
    "missing_assertions": VulnerabilityType.OTHER,
    "missing_edge_cases": VulnerabilityType.OTHER,
    "test_isolation": VulnerabilityType.OTHER,
    "flaky_test_pattern": VulnerabilityType.OTHER,
    "incomplete_coverage": VulnerabilityType.OTHER,
    "slow_test": VulnerabilityType.OTHER,
    "duplicate_test": VulnerabilityType.OTHER,
    "missing_error_handling": VulnerabilityType.OTHER,
    "hardcoded_values": VulnerabilityType.OTHER,
}


class QAISO(BaseISO):
    """Quality Assurance ISO agent.

    Pipeline:
        1. Deterministic checks: test file detection, test function regex,
           pytest configuration parsing
        2. LLM analysis for test quality issues: dead tests, missing assertions,
           test isolation problems, flaky patterns, coverage gaps
        3. Findings capped at 0.7 confidence (LLM-only, no tool confirmation)

    Focus areas:
        - Missing test coverage for critical paths
        - Test quality: dead tests, untested code paths
        - Missing assertions or empty test bodies
        - Test isolation issues (shared state, fixtures)
        - Flaky test patterns (timeouts, race conditions, random data)
        - Missing edge case testing
        - Slow or resource-intensive tests
    """

    SPECIALIZATION = ISOSpecialization.QA
    DEFAULT_TOOLS = ()  # Pure LLM analysis with regex preprocessing

    SYSTEM_PROMPT = """\
You are QAISO, a test quality analysis agent in the Tron zero-drift \
verification pipeline. Your role is to identify test coverage gaps and \
test quality issues.

CRITICAL: You MUST respond with ONLY a JSON array. Do NOT include any \
explanatory text, markdown formatting, or preamble. Your response must \
start with '[' and end with ']'.

RULES:
1. Only report real test quality issues with measurable impact. Ignore \
stylistic preferences.
2. Focus on issues that reduce test reliability and coverage:
   - Dead tests: tests that never run or are always skipped
   - Missing assertions: test functions with no assert statements
   - Missing edge cases: no tests for boundary conditions, error paths, \
or edge inputs
   - Test isolation: tests that depend on shared state, fixture order, \
or environmental conditions
   - Flaky patterns: tests with timeouts, race conditions, hardcoded \
timing, or random data
   - Coverage gaps: critical business logic without tests
   - Slow tests: tests that take excessive time (>5 seconds)
3. Severity guide:
   - critical: Untested critical path, data corruption risk, no error handling
   - high: Significant coverage gap, likely to fail in production, brittle test
   - medium: Potential coverage gap, test quality issue
   - low: Minor test issue, optimization opportunity
4. Do NOT report: test organization, naming conventions, or trivial issues.

OUTPUT FORMAT (pure JSON array, NO other text):
[
  {
    "vulnerability_type": "other",
    "qa_category": "<dead_test|missing_assertions|missing_edge_cases|\
test_isolation|flaky_test_pattern|incomplete_coverage|slow_test|\
duplicate_test|missing_error_handling|hardcoded_values>",
    "severity": "<critical|high|medium|low|info>",
    "file_path": "<relative path>",
    "line_number": <int>,
    "line_end": <int or null>,
    "code_snippet": "<the test code or test definition>",
    "description": "<what the test quality issue is and why it matters>",
    "fix_suggestion": "<how to fix the test or add missing coverage>",
    "affected_source_files": "[\"file1.py\", \"file2.py\"] or null",
    "confidence": <float 0.0-1.0>
  }
]

If you find no test quality issues, return: []

Remember: ONLY JSON. No preamble, no explanation, no markdown.
"""

    def __init__(
        self,
        config: ISOConfig,
        secrets: Dict[str, str],
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        super().__init__(config, secrets)
        if llm_client:
            self._llm = llm_client
        else:
            self._llm = LLMClient(
                anthropic_key=secrets.get("llm/anthropic-key"),
                openai_key=secrets.get("llm/openai-key"),
            )

    # ── Core Analysis ──────────────────────────────────────────────

    async def _analyze(
        self,
        blueprint: Blueprint,
        file_contents: Dict[str, str],
        tool_results: Dict[str, ToolResult],
    ) -> List[FindingOutput]:
        """Run test quality analysis."""

        # Run deterministic pre-pass to gather test metadata
        test_metadata = self._run_deterministic_tools(file_contents)

        # Filter to test files + relevant source files
        test_files = {
            p: c for p, c in file_contents.items()
            if self._is_test_file(p)
        }
        if not test_files:
            # No tests found
            return []

        # Budget: reserve ~1500 for prompt + test metadata
        budget = blueprint.max_tokens - 1500
        trimmed_tests = self._truncate_to_budget(test_files, max(budget, 500))

        prompt = self._build_prompt(
            blueprint,
            trimmed_tests,
            file_contents,
            test_metadata,
            tool_results,
        )

        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=self.SYSTEM_PROMPT),
                LLMMessage(role="user", content=prompt),
            ],
            model=self.config.model_name,
            temperature=blueprint.temperature,
            max_tokens=4096,  # LLM *output* limit (Haiku max); file budget is separate
            json_mode=True,
        )

        response = await self._llm.complete(request)

        if self._metrics:
            self._metrics.llm_calls += 1
            self._metrics.llm_tokens_used += response.total_tokens
            self._metrics.llm_cost_usd += response.cost_usd

        return self._parse_llm_response(response.content, blueprint)

    # ── Deterministic Tool Pre-Pass ────────────────────────────────

    def _run_deterministic_tools(
        self,
        file_contents: Dict[str, str],
    ) -> Dict[str, Any]:
        """Run deterministic test analysis (regex, parsing).

        Args:
            file_contents: All project files.

        Returns:
            Dict with test metadata:
                - test_file_count: number of test files
                - test_function_count: total test functions
                - skipped_test_count: @skip/@pytest.mark.skip decorators
                - test_files: list of test file paths
                - pytest_config: pytest.ini or pyproject.toml settings (if found)
        """
        metadata: Dict[str, Any] = {
            "test_file_count": 0,
            "test_function_count": 0,
            "skipped_test_count": 0,
            "test_files": [],
            "pytest_config": "",
        }

        # Find all test files
        test_files = [p for p in file_contents if self._is_test_file(p)]
        metadata["test_file_count"] = len(test_files)
        metadata["test_files"] = test_files

        # Count test functions and skipped tests
        test_func_pattern = re.compile(
            r"^\s*(?:def|async\s+def)\s+test_\w+\s*\(",
            re.MULTILINE,
        )
        skip_pattern = re.compile(
            r"@(?:pytest\.mark\.skip|skip|unittest\.skip)",
            re.MULTILINE,
        )

        for test_file in test_files:
            content = file_contents.get(test_file, "")
            test_func_count = len(test_func_pattern.findall(content))
            skip_count = len(skip_pattern.findall(content))
            metadata["test_function_count"] += test_func_count
            metadata["skipped_test_count"] += skip_count

        # Look for pytest config
        for config_file in ["pytest.ini", "pyproject.toml", "setup.cfg"]:
            if config_file in file_contents:
                metadata["pytest_config"] = (
                    f"Found {config_file} (check testpaths, markers, etc.)"
                )
                break

        logger.info(
            "Test metadata: %d test files, %d test functions, %d skipped",
            metadata["test_file_count"],
            metadata["test_function_count"],
            metadata["skipped_test_count"],
        )

        return metadata

    # ── Prompt Construction ────────────────────────────────────────

    def _build_prompt(
        self,
        blueprint: Blueprint,
        test_files: Dict[str, str],
        all_files: Dict[str, str],
        test_metadata: Dict[str, Any],
        tool_results: Dict[str, ToolResult],
    ) -> str:
        """Build the LLM prompt for test quality analysis."""
        parts: List[str] = []

        parts.append(f"## Blueprint: {blueprint.name}")
        parts.append(f"Description: {blueprint.description}")
        parts.append(f"Languages: {', '.join(blueprint.scope.languages)}")
        parts.append("")

        # Test metadata summary
        parts.append("## Test Suite Summary")
        parts.append(f"Test files: {test_metadata.get('test_file_count', 0)}")
        parts.append(f"Test functions: {test_metadata.get('test_function_count', 0)}")
        parts.append(f"Skipped tests: {test_metadata.get('skipped_test_count', 0)}")
        if test_metadata.get("pytest_config"):
            parts.append(f"Config: {test_metadata['pytest_config']}")
        parts.append("")

        # Test files
        parts.append("## Test Files to Analyze")
        for path, content in test_files.items():
            parts.append(f"### {path}")
            parts.append("```")
            parts.append(content)
            parts.append("```")
            parts.append("")

        # Include some source files for context (if not too large)
        source_files = {
            p: c for p, c in all_files.items()
            if not self._is_test_file(p) and not self._is_config_file(p)
        }
        if source_files:
            parts.append("## Source Files (for coverage context)")
            # Include only first few files to stay within budget
            for path in list(source_files.keys())[:5]:
                content = source_files[path]
                parts.append(f"### {path}")
                parts.append("```")
                parts.append(content[:1000])  # First 1000 chars only
                if len(content) > 1000:
                    parts.append("... [truncated]")
                parts.append("```")
                parts.append("")

        parts.append(
            "Analyze the test suite above for quality issues and coverage gaps. "
            "Focus on: dead tests, missing assertions, test isolation, flaky patterns, "
            "and missing edge case coverage. Return a JSON array of findings."
        )

        return "\n".join(parts)

    # ── Response Parsing ───────────────────────────────────────────

    def _parse_llm_response(
        self,
        raw_response: str,
        blueprint: Blueprint,
    ) -> List[FindingOutput]:
        """Parse LLM JSON response into FindingOutput objects."""
        text = raw_response.strip()

        # Strip markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # Strip preamble text before JSON
        for i, char in enumerate(text):
            if char in ("[", "{"):
                text = text[i:]
                break

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("QAISO: failed to parse LLM response: %s", exc)
            logger.debug("Raw response: %s", raw_response[:500])
            return []

        if not isinstance(data, list):
            if isinstance(data, dict) and "findings" in data:
                data = data["findings"]
            else:
                logger.warning("QAISO: response is not a list")
                return []

        findings: List[FindingOutput] = []

        for i, item in enumerate(data):
            try:
                # Map QA categories to vulnerability types
                qa_cat = item.get("qa_category", "other")
                vuln_type = QA_VULN_TYPE_MAP.get(qa_cat, VulnerabilityType.OTHER)

                # Build description with QA category prefix
                desc = item.get("description", "")
                if qa_cat and qa_cat not in desc:
                    desc = f"[{qa_cat}] {desc}"

                finding = FindingOutput(
                    id=uuid4(),
                    vulnerability_type=vuln_type,
                    severity=SeverityLevel(item.get("severity", "medium")),
                    file_path=item.get("file_path", "unknown"),
                    line_number=max(1, int(item.get("line_number", 1))),
                    line_end=item.get("line_end"),
                    code_snippet=item.get("code_snippet", "# no snippet"),
                    description=desc,
                    fix_suggestion=item.get("fix_suggestion"),
                    confidence=min(float(item.get("confidence", 0.5)), 0.7),
                    deterministic_tool_confirmed=False,
                    agent_id=self.config.agent_id,
                    blueprint_id=blueprint.id,
                    finding_fingerprint="pending",
                    cross_validation_status=CrossValidationStatus.PENDING,
                )
                findings.append(finding)
            except Exception as exc:
                logger.warning(
                    "QAISO: skipping finding #%d: %s", i, exc
                )
                continue

        logger.info("QAISO: parsed %d findings", len(findings))
        return findings

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _is_test_file(path: str) -> bool:
        """Check if a file is a test file.

        Convention: test_*.py, *_test.py, tests.py, or in tests/ directory.
        """
        lower = path.lower()
        if not lower.endswith(".py") or "test" not in lower:
            return False

        # Normalise to forward-slash for cross-platform matching
        normalised = lower.replace("\\", "/")
        basename = normalised.rsplit("/", 1)[-1]

        return (
            basename.startswith("test_")
            or basename.endswith("_test.py")
            or "/tests/" in normalised
            or "/test/" in normalised
            or normalised.startswith("tests/")
            or normalised.startswith("test/")
        )

    @staticmethod
    def _is_config_file(path: str) -> bool:
        """Check if a file is a config file (not source code)."""
        lower = path.lower()
        config_names = {
            "pytest.ini",
            "setup.py",
            "setup.cfg",
            "pyproject.toml",
            "tox.ini",
            "conftest.py",
            "requirements.txt",
            "dockerfile",
            "makefile",
        }
        return (
            any(lower.endswith(name) for name in config_names)
            or lower.endswith(".yml")
            or lower.endswith(".yaml")
            or lower.endswith(".json")
            or lower.endswith(".toml")
        )
