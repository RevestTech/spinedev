"""
PerformanceISO — Performance-focused ISO agent.

Analyzes code for performance anti-patterns: N+1 queries, missing async,
unclosed resources, inefficient algorithms, missing caching, and database
query issues. Uses purely LLM-based analysis (no deterministic pre-pass
tools yet — profilers are too invasive for static analysis).

Architecture ref: docs/architecture/AI_AGENT_ARCHITECTURE.md §1.5
"""

from __future__ import annotations

import json
import logging
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


# Performance issue types mapped to closest VulnerabilityType
# Most performance issues map to OTHER since the enum is security-focused
PERF_VULN_TYPE_MAP = {
    "n_plus_one": VulnerabilityType.OTHER,
    "missing_async": VulnerabilityType.OTHER,
    "resource_leak": VulnerabilityType.OTHER,
    "inefficient_algorithm": VulnerabilityType.OTHER,
    "missing_index": VulnerabilityType.OTHER,
    "missing_cache": VulnerabilityType.OTHER,
    "blocking_io": VulnerabilityType.OTHER,
    "memory_leak": VulnerabilityType.OTHER,
    "excessive_logging": VulnerabilityType.OTHER,
    "unbounded_query": VulnerabilityType.OTHER,
    "security_misconfiguration": VulnerabilityType.SECURITY_MISCONFIGURATION,
}


class PerformanceISO(BaseISO):
    """Performance-specialized ISO agent.

    Pipeline:
        1. LLM analysis for performance anti-patterns
        2. No deterministic tools (static profiling isn't practical)
        3. Findings are capped at 0.7 confidence since LLM-only

    Focus areas:
        - N+1 query patterns (ORM usage in loops)
        - Missing async/await (blocking calls in async context)
        - Resource leaks (unclosed files, DB connections, HTTP sessions)
        - Inefficient algorithms (nested loops, unbounded collections)
        - Missing pagination/limits on database queries
        - Missing caching for repeated expensive operations
        - Blocking I/O in event loops
    """

    SPECIALIZATION = ISOSpecialization.PERFORMANCE
    DEFAULT_TOOLS = ()  # Pure LLM analysis

    SYSTEM_PROMPT = """\
You are PerformanceISO, a performance analysis agent in the Tron \
zero-drift verification pipeline. You identify performance anti-patterns \
and bottlenecks in source code.

CRITICAL: You MUST respond with ONLY a JSON array. Do NOT include any \
explanatory text, markdown formatting, or preamble. Your response must \
start with '[' and end with ']'.

RULES:
1. Only report real performance issues with measurable impact. No premature \
optimization complaints.
2. Focus on issues that cause real production problems:
   - N+1 queries: ORM/DB calls inside loops (e.g., for item in items: db.query(...))
   - Blocking I/O in async context: sync HTTP calls, file I/O, or sleep() in async functions
   - Resource leaks: unclosed database connections, file handles, HTTP sessions
   - Unbounded queries: SELECT * without LIMIT, loading entire tables into memory
   - Missing pagination: API endpoints that return all records
   - Inefficient algorithms: O(n²) loops where O(n) or O(n log n) is possible
   - Memory issues: growing collections without bounds, large object retention
   - Missing caching: repeated identical expensive operations (DB/API calls)
3. Do NOT report: micro-optimizations, stylistic preferences, or issues \
only relevant at extreme scale.
4. Severity guide:
   - critical: Will cause outages (unbounded memory growth, connection exhaustion)
   - high: Significant degradation at normal load (N+1 queries, blocking I/O)
   - medium: Noticeable under load (missing cache, inefficient algorithm)
   - low: Minor optimization opportunity

OUTPUT FORMAT (pure JSON array, NO other text):
[
  {
    "vulnerability_type": "other",
    "performance_category": "<n_plus_one|missing_async|resource_leak|\
inefficient_algorithm|missing_index|missing_cache|blocking_io|memory_leak|\
excessive_logging|unbounded_query>",
    "severity": "<critical|high|medium|low|info>",
    "file_path": "<relative path>",
    "line_number": <int>,
    "line_end": <int or null>,
    "code_snippet": "<the problematic code>",
    "description": "<what the performance issue is and its impact>",
    "fix_suggestion": "<how to fix it with a concrete before/after example>",
    "estimated_impact": "<brief: e.g., '10x fewer DB queries' or 'prevents OOM'>",
    "confidence": <float 0.0-1.0>
  }
]

If you find no performance issues, return: []

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
        """Run LLM performance analysis."""

        # Filter to code files (skip configs, YAMLs — those are BuilderISO's domain)
        code_files = {
            p: c for p, c in file_contents.items()
            if _is_code_file(p)
        }
        if not code_files:
            code_files = file_contents

        budget = blueprint.max_tokens - 1500
        trimmed = self._truncate_to_budget(code_files, max(budget, 500))

        prompt = self._build_prompt(blueprint, trimmed, tool_results)

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

    # ── Prompt Construction ────────────────────────────────────────

    def _build_prompt(
        self,
        blueprint: Blueprint,
        file_contents: Dict[str, str],
        tool_results: Dict[str, ToolResult],
    ) -> str:
        """Build prompt for performance analysis."""
        parts: List[str] = []

        parts.append(f"## Blueprint: {blueprint.name}")
        parts.append(f"Description: {blueprint.description}")
        parts.append(f"Languages: {', '.join(blueprint.scope.languages)}")
        parts.append("")

        # Source code
        parts.append("## Source Code to Analyze for Performance Issues")
        for path, content in file_contents.items():
            parts.append(f"### {path}")
            parts.append("```")
            parts.append(content)
            parts.append("```")
            parts.append("")

        parts.append(
            "Analyze the code above for performance anti-patterns and bottlenecks. "
            "Focus on N+1 queries, blocking I/O, resource leaks, unbounded queries, "
            "and inefficient algorithms. Return a JSON array of findings."
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
            logger.warning("PerformanceISO: failed to parse response: %s", exc)
            return []

        if not isinstance(data, list):
            if isinstance(data, dict) and "findings" in data:
                data = data["findings"]
            else:
                logger.warning("PerformanceISO: response is not a list")
                return []

        findings: List[FindingOutput] = []

        for i, item in enumerate(data):
            try:
                # Map performance categories to vulnerability types
                perf_cat = item.get("performance_category", "other")
                vuln_type = PERF_VULN_TYPE_MAP.get(
                    perf_cat, VulnerabilityType.OTHER
                )

                # Build description with performance category prefix
                desc = item.get("description", "")
                impact = item.get("estimated_impact", "")
                if impact and impact not in desc:
                    desc = f"[{perf_cat}] {desc} (Impact: {impact})"
                elif perf_cat:
                    desc = f"[{perf_cat}] {desc}"

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
                    "PerformanceISO: skipping finding #%d: %s", i, exc
                )
                continue

        logger.info("PerformanceISO: parsed %d findings", len(findings))
        return findings


def _is_code_file(path: str) -> bool:
    """Check if a file is source code (not config/manifest)."""
    code_extensions = {
        ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs",
        ".java", ".kt", ".scala",
        ".go", ".rs",
        ".c", ".cpp", ".cc", ".h", ".hpp",
        ".cs", ".rb", ".php", ".swift",
    }
    lower = path.lower()
    return any(lower.endswith(ext) for ext in code_extensions)
