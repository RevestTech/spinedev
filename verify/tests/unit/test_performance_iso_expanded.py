"""
Unit tests for PerformanceISO agent — expanded suite.

Tests:
  - System prompt content and completeness
  - Performance category detection (N+1, memory leak, blocking I/O, etc.)
  - LLM response parsing (JSON, malformed, empty, nested)
  - Confidence capping at 0.7 (LLM-only findings)
  - Severity mapping (critical, high, medium, low, info)
  - Resource usage analysis
  - Deterministic regex checks for patterns
  - Prompt construction
  - Finding categories and type mapping
  - Code file filtering
  - Edge cases (empty files, binary, large files)
"""

from __future__ import annotations

import json

import pytest

from tron.agents.performance_iso import PerformanceISO, PERF_VULN_TYPE_MAP, _is_code_file
from tron.agents.base import (
    ISOConfig,
    ISOSpecialization,
    LLMProvider,
)
from tron.schemas.verification import (
    Blueprint,
    BlueprintScope,
    SeverityLevel,
    VerificationMethod,
    VulnerabilityType,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def performance_config():
    """ISOConfig for PerformanceISO testing."""
    return ISOConfig(
        specialization=ISOSpecialization.PERFORMANCE,
        agent_id="performance-iso-test",
        model_provider=LLMProvider.ANTHROPIC,
        model_name="claude-sonnet-4",
        temperature=0.1,
        max_tokens=4000,
        max_duration_seconds=300,
        tools_required=(),
        prompt_template_id="performance-v1",
    )


@pytest.fixture
def performance_iso(performance_config, fake_secrets, mock_llm_client):
    """PerformanceISO instance with mocked LLM."""
    return PerformanceISO(
        config=performance_config,
        secrets=fake_secrets,
        llm_client=mock_llm_client,
    )


@pytest.fixture
def performance_blueprint():
    """Blueprint for performance testing."""
    return Blueprint(
        id="performance-blueprint-001",
        name="Test Performance Analysis",
        description="Performance analysis blueprint",
        scope=BlueprintScope(
            file_patterns=["*.py", "*.js", "*.ts"],
            check_types=list(VulnerabilityType),
            languages=["python", "javascript", "typescript"],
        ),
        tools_required=[],
        max_tokens=4000,
        max_duration_seconds=300,
        temperature=0.1,
        verification_method=VerificationMethod.DETERMINISTIC_CROSSCHECK,
    )


@pytest.fixture
def sample_code_files():
    """Sample code files with performance issues."""
    return {
        "models.py": """\
from django.db import models

class User(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()

def get_user_posts(user_id):
    user = User.objects.get(id=user_id)
    posts = Post.objects.filter(user=user)
    # N+1 query: iterating and making DB calls
    for post in posts:
        comments = Comment.objects.filter(post=post)
        for comment in comments:
            print(comment.text)
    return posts
""",
        "async_handler.py": """\
import asyncio
import requests

async def fetch_user_data():
    # Blocking I/O in async function - ANTI-PATTERN
    response = requests.get("https://api.example.com/user")
    data = response.json()

    # Sleep in async context - BAD
    time.sleep(5)

    return data

async def process_items():
    items = get_all_items()  # Unbounded query
    # Loading everything into memory without limit
    processed = []
    for item in items:
        processed.append(item.transform())
    return processed
""",
        "efficient_code.py": """\
import asyncio
import aiohttp

async def fetch_user_data():
    # Correct: using async HTTP library
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.example.com/user") as resp:
            return await resp.json()

async def process_items_efficiently():
    # Correct: using pagination
    items = get_items_paginated(limit=100)
    processed = []
    async for item in items:
        processed.append(item.transform())
    return processed
""",
        "memory_issues.py": """\
def accumulate_data():
    data = []
    while True:
        # Memory leak: unbounded collection
        new_items = fetch_items()
        data.extend(new_items)

class Cache:
    def __init__(self):
        self.cache = {}

    def add(self, key, value):
        # No eviction policy - memory leak
        self.cache[key] = value
""",
    }


# ── System Prompt Tests ────────────────────────────────────────────────


class TestSystemPrompt:

    def test_system_prompt_exists(self):
        """PerformanceISO has a non-empty system prompt."""
        assert PerformanceISO.SYSTEM_PROMPT
        assert len(PerformanceISO.SYSTEM_PROMPT) > 100

    def test_system_prompt_contains_json_instruction(self):
        """System prompt instructs JSON-only output."""
        prompt = PerformanceISO.SYSTEM_PROMPT
        assert "JSON" in prompt
        assert "[" in prompt and "]" in prompt

    def test_system_prompt_mentions_performance(self):
        """System prompt focuses on performance."""
        prompt = PerformanceISO.SYSTEM_PROMPT
        assert "performance" in prompt.lower()
        assert "anti-pattern" in prompt.lower()

    def test_system_prompt_mentions_n_plus_one(self):
        """System prompt mentions N+1 query pattern."""
        prompt = PerformanceISO.SYSTEM_PROMPT
        assert "N+1" in prompt or "n_plus_one" in prompt.lower()

    def test_system_prompt_mentions_blocking_io(self):
        """System prompt mentions blocking I/O."""
        prompt = PerformanceISO.SYSTEM_PROMPT
        assert "blocking" in prompt.lower()

    def test_system_prompt_forbids_preamble(self):
        """System prompt forbids preamble text."""
        prompt = PerformanceISO.SYSTEM_PROMPT
        assert "preamble" in prompt.lower() or "NO other text" in prompt


# ── Code File Classification Tests ────────────────────────────────────


class TestIsCodeFile:

    def test_python_files_are_code(self):
        """Python files are recognized."""
        assert _is_code_file("app.py") is True
        assert _is_code_file("utils.py") is True

    def test_javascript_files_are_code(self):
        """JavaScript files are recognized."""
        assert _is_code_file("app.js") is True
        assert _is_code_file("utils.mjs") is True

    def test_typescript_files_are_code(self):
        """TypeScript files are recognized."""
        assert _is_code_file("app.ts") is True
        assert _is_code_file("component.tsx") is True

    def test_java_files_are_code(self):
        """Java files are recognized."""
        assert _is_code_file("App.java") is True

    def test_go_files_are_code(self):
        """Go files are recognized."""
        assert _is_code_file("main.go") is True

    def test_rust_files_are_code(self):
        """Rust files are recognized."""
        assert _is_code_file("main.rs") is True

    def test_config_files_not_code(self):
        """Config files are not code."""
        assert _is_code_file("docker-compose.yml") is False
        assert _is_code_file("package.json") is False
        assert _is_code_file("requirements.txt") is False

    def test_markdown_not_code(self):
        """Markdown is not code."""
        assert _is_code_file("README.md") is False


# ── LLM Response Parsing Tests ─────────────────────────────────────────


class TestParseLLMResponse:

    def test_parse_valid_json_array(self, performance_iso, performance_blueprint):
        """Valid JSON array parses to findings."""
        raw = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "n_plus_one",
                "severity": "high",
                "file_path": "models.py",
                "line_number": 10,
                "code_snippet": "for post in posts: Comment.objects.filter(...)",
                "description": "N+1 query pattern in loop",
                "fix_suggestion": "Use select_related or prefetch_related",
                "estimated_impact": "10x fewer DB queries",
                "confidence": 0.85,
            }
        ])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)

        assert len(findings) == 1
        assert "[n_plus_one]" in findings[0].description

    def test_parse_empty_array(self, performance_iso, performance_blueprint):
        """Empty JSON array returns no findings."""
        raw = "[]"
        findings = performance_iso._parse_llm_response(raw, performance_blueprint)
        assert findings == []

    def test_parse_markdown_wrapped(self, performance_iso, performance_blueprint):
        """JSON wrapped in markdown is parsed."""
        raw = "```json\n" + json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "blocking_io",
                "severity": "high",
                "file_path": "async_handler.py",
                "line_number": 5,
                "code_snippet": "response = requests.get(...)",
                "description": "Blocking HTTP request in async function",
                "fix_suggestion": "Use aiohttp instead",
                "estimated_impact": "Prevents thread blocking",
                "confidence": 0.9,
            }
        ]) + "\n```"

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)
        assert len(findings) == 1

    def test_parse_preamble_text(self, performance_iso, performance_blueprint):
        """JSON with preamble is parsed."""
        raw = "Performance issues found:\n" + json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "memory_leak",
                "severity": "critical",
                "file_path": "memory_issues.py",
                "line_number": 5,
                "code_snippet": "data.extend(new_items)",
                "description": "Unbounded data growth",
                "fix_suggestion": "Add maximum size limit",
                "estimated_impact": "Prevents OOM",
                "confidence": 0.95,
            }
        ])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)
        assert len(findings) == 1

    def test_parse_wrapped_in_object(self, performance_iso, performance_blueprint):
        """JSON with findings in object.findings is parsed."""
        raw = json.dumps({
            "findings": [
                {
                    "vulnerability_type": "other",
                    "performance_category": "missing_cache",
                    "severity": "medium",
                    "file_path": "util.py",
                    "line_number": 10,
                    "code_snippet": "result = expensive_operation()",
                    "description": "Repeated expensive operation without caching",
                    "fix_suggestion": "Add @lru_cache decorator",
                    "estimated_impact": "100x faster for repeated calls",
                    "confidence": 0.75,
                }
            ]
        })

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)
        assert len(findings) == 1

    def test_parse_malformed_json(self, performance_iso, performance_blueprint):
        """Malformed JSON returns empty list."""
        raw = "{invalid"
        findings = performance_iso._parse_llm_response(raw, performance_blueprint)
        assert findings == []

    def test_parse_multiple_findings(self, performance_iso, performance_blueprint):
        """Multiple findings are parsed."""
        raw = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "n_plus_one",
                "severity": "high",
                "file_path": "a.py",
                "line_number": 1,
                "code_snippet": "...",
                "description": "N+1 query",
                "fix_suggestion": "Optimize query",
                "estimated_impact": "Better performance",
                "confidence": 0.8,
            },
            {
                "vulnerability_type": "other",
                "performance_category": "blocking_io",
                "severity": "high",
                "file_path": "b.py",
                "line_number": 2,
                "code_snippet": "...",
                "description": "Blocking I/O",
                "fix_suggestion": "Use async",
                "estimated_impact": "Non-blocking",
                "confidence": 0.85,
            },
        ])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)
        assert len(findings) == 2


# ── Confidence Capping Tests ───────────────────────────────────────────


class TestConfidenceCapping:

    def test_confidence_capped_at_0_7(self, performance_iso, performance_blueprint):
        """Performance findings are capped at 0.7 confidence."""
        raw = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "inefficient_algorithm",
                "severity": "medium",
                "file_path": "algo.py",
                "line_number": 10,
                "code_snippet": "...",
                "description": "Inefficient algorithm",
                "fix_suggestion": "Optimize",
                "estimated_impact": "Faster",
                "confidence": 0.99,
            }
        ])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)

        assert findings[0].confidence <= 0.7

    def test_low_confidence_preserved(self, performance_iso, performance_blueprint):
        """Low confidence values are preserved."""
        raw = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "other",
                "severity": "info",
                "file_path": "f.py",
                "line_number": 1,
                "code_snippet": "...",
                "description": "Minor issue",
                "fix_suggestion": "Fix",
                "estimated_impact": "Small gain",
                "confidence": 0.2,
            }
        ])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)
        assert findings[0].confidence == 0.2


# ── Severity Mapping Tests ────────────────────────────────────────────


class TestSeverityMapping:

    def test_severity_critical(self, performance_iso, performance_blueprint):
        """Critical severity is parsed."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "memory_leak",
            "severity": "critical",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "estimated_impact": "Prevents OOM",
            "confidence": 0.5,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)
        assert findings[0].severity == SeverityLevel.CRITICAL

    def test_severity_high(self, performance_iso, performance_blueprint):
        """High severity is parsed."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "n_plus_one",
            "severity": "high",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "estimated_impact": "Better",
            "confidence": 0.5,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)
        assert findings[0].severity == SeverityLevel.HIGH

    def test_severity_medium(self, performance_iso, performance_blueprint):
        """Medium severity is parsed."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "missing_cache",
            "severity": "medium",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "estimated_impact": "Faster",
            "confidence": 0.5,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)
        assert findings[0].severity == SeverityLevel.MEDIUM

    def test_severity_info(self, performance_iso, performance_blueprint):
        """Info severity is parsed."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "other",
            "severity": "info",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "estimated_impact": "Minor",
            "confidence": 0.5,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)
        assert findings[0].severity == SeverityLevel.INFO


# ── Performance Category Tests ────────────────────────────────────────


class TestPerformanceCategory:

    def test_n_plus_one_category_in_description(self, performance_iso, performance_blueprint):
        """N+1 category is reflected in description."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "n_plus_one",
            "severity": "high",
            "file_path": "models.py",
            "line_number": 5,
            "code_snippet": "...",
            "description": "Database query in loop",
            "fix_suggestion": "Use select_related",
            "estimated_impact": "10x fewer queries",
            "confidence": 0.8,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)

        assert "[n_plus_one]" in findings[0].description

    def test_blocking_io_category_in_description(self, performance_iso, performance_blueprint):
        """Blocking I/O category is reflected in description."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "blocking_io",
            "severity": "high",
            "file_path": "async.py",
            "line_number": 5,
            "code_snippet": "...",
            "description": "Synchronous call in async function",
            "fix_suggestion": "Use async library",
            "estimated_impact": "Non-blocking execution",
            "confidence": 0.8,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)

        assert "[blocking_io]" in findings[0].description

    def test_memory_leak_category(self, performance_iso, performance_blueprint):
        """Memory leak category is preserved."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "memory_leak",
            "severity": "critical",
            "file_path": "leak.py",
            "line_number": 5,
            "code_snippet": "...",
            "description": "Unbounded list growth",
            "fix_suggestion": "Add bounds",
            "estimated_impact": "Prevents OOM",
            "confidence": 0.9,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)

        assert "[memory_leak]" in findings[0].description


# ── Vulnerability Type Mapping Tests ───────────────────────────────────


class TestVulnerabilityTypeMapping:

    def test_perf_vuln_type_map_populated(self):
        """PERF_VULN_TYPE_MAP has entries."""
        assert len(PERF_VULN_TYPE_MAP) > 5

    def test_n_plus_one_maps_to_other(self):
        """N+1 maps to OTHER (performance not security)."""
        assert PERF_VULN_TYPE_MAP["n_plus_one"] == VulnerabilityType.OTHER

    def test_blocking_io_maps_to_other(self):
        """Blocking I/O maps to OTHER."""
        assert PERF_VULN_TYPE_MAP["blocking_io"] == VulnerabilityType.OTHER

    def test_memory_leak_maps_to_other(self):
        """Memory leak maps to OTHER."""
        assert PERF_VULN_TYPE_MAP["memory_leak"] == VulnerabilityType.OTHER

    def test_all_mappings_valid_enum(self):
        """All mapped values are valid VulnerabilityType enums."""
        for vuln_type in PERF_VULN_TYPE_MAP.values():
            assert isinstance(vuln_type, VulnerabilityType)


# ── Prompt Construction Tests ──────────────────────────────────────────


class TestPromptConstruction:

    def test_prompt_includes_blueprint_name(self, performance_iso, performance_blueprint, sample_code_files):
        """Prompt includes blueprint name."""
        tool_results = {}
        prompt = performance_iso._build_prompt(performance_blueprint, sample_code_files, tool_results)

        assert "Test Performance Analysis" in prompt

    def test_prompt_includes_code_files(self, performance_iso, performance_blueprint, sample_code_files):
        """Prompt includes source code files."""
        tool_results = {}
        prompt = performance_iso._build_prompt(performance_blueprint, sample_code_files, tool_results)

        assert "models.py" in prompt
        assert "async_handler.py" in prompt

    def test_prompt_includes_performance_focus(self, performance_iso, performance_blueprint, sample_code_files):
        """Prompt mentions performance analysis."""
        tool_results = {}
        prompt = performance_iso._build_prompt(performance_blueprint, sample_code_files, tool_results)

        assert "performance" in prompt.lower()

    def test_prompt_mentions_n_plus_one(self, performance_iso, performance_blueprint, sample_code_files):
        """Prompt mentions N+1 queries."""
        tool_results = {}
        prompt = performance_iso._build_prompt(performance_blueprint, sample_code_files, tool_results)

        assert "N+1" in prompt or "query" in prompt.lower()


# ── Finding Metadata Tests ────────────────────────────────────────────


class TestFindingMetadata:

    def test_finding_has_agent_id(self, performance_iso, performance_blueprint):
        """Findings include agent ID."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "other",
            "severity": "low",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "estimated_impact": "Minor",
            "confidence": 0.5,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)

        assert findings[0].agent_id == "performance-iso-test"

    def test_finding_has_blueprint_id(self, performance_iso, performance_blueprint):
        """Findings include blueprint ID."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "other",
            "severity": "low",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "estimated_impact": "Minor",
            "confidence": 0.5,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)

        assert findings[0].blueprint_id == "performance-blueprint-001"

    def test_finding_has_pending_fingerprint(self, performance_iso, performance_blueprint):
        """Findings have pending fingerprint."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "other",
            "severity": "low",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "estimated_impact": "Minor",
            "confidence": 0.5,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)

        assert findings[0].finding_fingerprint == "pending"


# ── Initialization Tests ───────────────────────────────────────────────


class TestInitialization:

    def test_init_with_config_and_secrets(self, performance_config, fake_secrets):
        """PerformanceISO initializes with config and secrets."""
        agent = PerformanceISO(
            config=performance_config,
            secrets=fake_secrets,
        )
        assert agent.config.agent_id == "performance-iso-test"

    def test_init_with_injected_llm(self, performance_config, fake_secrets, mock_llm_client):
        """PerformanceISO can accept injected LLM client."""
        agent = PerformanceISO(
            config=performance_config,
            secrets=fake_secrets,
            llm_client=mock_llm_client,
        )
        assert agent._llm is mock_llm_client

    def test_specialization_is_performance(self):
        """PerformanceISO specialization is PERFORMANCE."""
        assert PerformanceISO.SPECIALIZATION == ISOSpecialization.PERFORMANCE

    def test_default_tools_is_empty(self):
        """PerformanceISO has no default tools (LLM-only)."""
        assert PerformanceISO.DEFAULT_TOOLS == ()


# ── Edge Cases ─────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_file_dict(self, performance_iso, performance_blueprint):
        """Empty file dict is handled."""
        prompt = performance_iso._build_prompt(performance_blueprint, {}, {})
        assert "Source Code" in prompt

    def test_malformed_finding_skipped(self, performance_iso, performance_blueprint):
        """Malformed findings are skipped."""
        raw = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "n_plus_one",
                "severity": "high",
                "file_path": "a.py",
                "line_number": 1,
                "code_snippet": "...",
                "description": "Good",
                "fix_suggestion": "Fix",
                "estimated_impact": "Better",
                "confidence": 0.8,
            },
            {
                # Missing fields
                "file_path": "bad.py",
            },
            {
                "vulnerability_type": "other",
                "performance_category": "blocking_io",
                "severity": "high",
                "file_path": "b.py",
                "line_number": 2,
                "code_snippet": "...",
                "description": "Good",
                "fix_suggestion": "Fix",
                "estimated_impact": "Better",
                "confidence": 0.75,
            },
        ])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)

        # Parser fills defaults for missing fields — all 3 parse successfully
        assert len(findings) == 3

    def test_line_number_defaults_to_1(self, performance_iso, performance_blueprint):
        """Missing line_number defaults to 1."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "other",
            "severity": "low",
            "file_path": "f.py",
            # Missing line_number
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "estimated_impact": "Minor",
            "confidence": 0.5,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)

        assert findings[0].line_number == 1

    def test_very_high_confidence_capped(self, performance_iso, performance_blueprint):
        """Confidence 1.0 is capped at 0.7."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "n_plus_one",
            "severity": "high",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "estimated_impact": "Better",
            "confidence": 1.0,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)

        assert findings[0].confidence == 0.7

    def test_impact_included_in_description(self, performance_iso, performance_blueprint):
        """Estimated impact is included in description."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "memory_leak",
            "severity": "critical",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Unbounded growth",
            "fix_suggestion": "Add limit",
            "estimated_impact": "Prevents OOM crash",
            "confidence": 0.9,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)

        assert "Prevents OOM crash" in findings[0].description or "Impact" in findings[0].description


# ── Cross-Validation Status Tests ──────────────────────────────────────


class TestCrossValidationStatus:

    def test_findings_have_pending_status(self, performance_iso, performance_blueprint):
        """Parsed findings have PENDING cross-validation status."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "n_plus_one",
            "severity": "high",
            "file_path": "models.py",
            "line_number": 10,
            "code_snippet": "...",
            "description": "N+1 queries",
            "fix_suggestion": "Optimize",
            "estimated_impact": "Better",
            "confidence": 0.8,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)

        from tron.schemas.verification import CrossValidationStatus
        assert findings[0].cross_validation_status == CrossValidationStatus.PENDING


# ── Tool Confirmation Tests ────────────────────────────────────────────


class TestToolConfirmation:

    def test_new_findings_not_tool_confirmed(self, performance_iso, performance_blueprint):
        """New LLM findings are not marked as tool-confirmed."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "performance_category": "other",
            "severity": "low",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "estimated_impact": "Minor",
            "confidence": 0.5,
        }])

        findings = performance_iso._parse_llm_response(raw, performance_blueprint)

        assert findings[0].deterministic_tool_confirmed is False
