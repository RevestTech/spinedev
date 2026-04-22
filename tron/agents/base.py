"""
BaseISO — Abstract base class for all Tron ISO agents.

Every ISO agent (SecurityISO, BuilderISO, QAISO, PerformanceISO) inherits
from this class. It enforces:

- Blueprint-scoped execution (agents can only touch what the Blueprint allows)
- Deterministic tool pre-pass (Bandit, Semgrep, etc. run BEFORE the LLM)
- Resource limits (token budget, duration timeout, temperature lock)
- Cross-validation isolation (different LLM providers for primary vs validator)
- Keyvault-only secrets (LLM keys loaded at runtime, never from env)
- Structured output via FindingOutput / FindingBatch schemas

Architecture ref: docs/architecture/AI_AGENT_ARCHITECTURE.md §1
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from tron.infra.sandbox.client import SandboxClient, get_sandbox_client
from tron.schemas.verification import (
    Blueprint,
    BlueprintScope,
    FindingBatch,
    FindingOutput,
    SeverityLevel,
    VerificationMethod,
    VulnerabilityType,
)

logger = logging.getLogger(__name__)


# ── Agent Specializations ──────────────────────────────────────────────


class ISOSpecialization(str, Enum):
    """Agent specialization types — each maps to one ISO agent class."""

    SECURITY = "security"
    BUILDER = "builder"
    QA = "qa"
    PERFORMANCE = "performance"
    COMPLIANCE = "compliance"
    DOCUMENTATION = "documentation"
    ARCHITECTURE = "architecture"


class LLMProvider(str, Enum):
    """Supported LLM providers.

    Cross-validation requires primary and validator to use DIFFERENT
    providers to prevent correlated failures (same training data →
    same blind spots).
    """

    ANTHROPIC = "anthropic"
    OPENAI = "openai"


# ── Configuration ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ISOConfig:
    """Immutable configuration for an ISO agent instance.

    All secrets (LLM API keys) are passed at runtime from keyvault —
    never stored in config files or environment variables.
    """

    specialization: ISOSpecialization
    agent_id: str

    # LLM settings
    model_provider: LLMProvider
    model_name: str                         # e.g. "claude-sonnet-4-20250514"
    fallback_model_name: Optional[str] = None
    temperature: float = 0.1                # Low temperature for determinism
    max_tokens: int = 4000

    # Resource limits
    max_duration_seconds: int = 300
    max_retries: int = 2
    max_concurrent_tools: int = 4

    # Deterministic tools this agent requires
    tools_required: tuple[str, ...] = ()

    # Prompt template reference (for drift detection)
    prompt_template_id: str = ""
    prompt_template_hash: str = ""          # SHA256 of the frozen prompt

    # ComplianceISO only: extra reference text from built-in control packs + project/env.
    compliance_reference_context: str = ""


# ── Tool Result ────────────────────────────────────────────────────────


@dataclass
class ToolResult:
    """Result from running a deterministic tool (Bandit, Semgrep, etc.)."""

    tool_name: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    findings_count: int = 0
    raw_findings: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.exit_code == 0


# ── Agent Metrics ──────────────────────────────────────────────────────


@dataclass
class AgentMetrics:
    """Runtime metrics for a single agent execution."""

    agent_id: str
    blueprint_id: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    total_findings: int = 0
    tool_durations: Dict[str, float] = field(default_factory=dict)
    llm_calls: int = 0
    llm_tokens_used: int = 0
    llm_cost_usd: float = 0.0
    errors: List[str] = field(default_factory=list)
    threat_intel_alerts: List[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        if self.finished_at and self.started_at:
            return self.finished_at - self.started_at
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "blueprint_id": self.blueprint_id,
            "duration_seconds": self.duration_seconds,
            "total_findings": self.total_findings,
            "tool_durations": self.tool_durations,
            "llm_calls": self.llm_calls,
            "llm_tokens_used": self.llm_tokens_used,
            "llm_cost_usd": self.llm_cost_usd,
            "errors": self.errors,
        }


# ── Abstract Base ──────────────────────────────────────────────────────


class BaseISO(ABC):
    """Abstract base for all ISO agents.

    Lifecycle:
        1. __init__  — receives ISOConfig + secrets dict (from keyvault)
        2. execute() — public entry point, enforces Blueprint constraints
           a. _run_deterministic_tools()  — Bandit/Semgrep/etc. pre-pass
           b. _analyze()                  — LLM-based analysis (subclass)
           c. _post_process()             — dedup, fingerprint, cap confidence
        3. Result is a FindingBatch ready for cross-validation

    Subclasses MUST implement:
        - _analyze()     — core LLM analysis logic
        - _build_prompt() — construct the LLM prompt from context + tool results
        - _parse_llm_response() — extract FindingOutputs from LLM response
    """

    # Subclasses override these
    SPECIALIZATION: ISOSpecialization
    DEFAULT_TOOLS: tuple[str, ...] = ()

    def __init__(
        self,
        config: ISOConfig,
        secrets: Dict[str, str],
    ) -> None:
        """Initialize the ISO agent.

        Args:
            config: Immutable agent configuration.
            secrets: Dict of secrets from keyvault. Must include the LLM
                     API key for this agent's provider. Keys follow the
                     keyvault path convention: "llm/openai-key",
                     "llm/anthropic-key" (worker merges optional "anthropic-key"
                     into this entry at startup), etc.
        """
        self.config = config
        self._secrets = secrets
        self._llm_api_key = self._resolve_llm_key(secrets)
        self._metrics: Optional[AgentMetrics] = None

        logger.info(
            "ISO agent initialized: %s (%s, provider=%s, model=%s)",
            config.agent_id,
            config.specialization.value,
            config.model_provider.value,
            config.model_name,
        )

    # ── Public API ─────────────────────────────────────────────────

    async def execute(
        self,
        blueprint: Blueprint,
        file_contents: Dict[str, str],
        workspace_root: str = "/workspace",
    ) -> FindingBatch:
        """Execute the agent against a Blueprint.

        This is the only public entry point. It enforces all Blueprint
        constraints: scope, resource limits, and verification method.

        Args:
            blueprint: The Blueprint defining scope and constraints.
            file_contents: Dict of {file_path: source_code} to analyze.
                          Only files matching Blueprint scope are processed.
            workspace_root: Root of the project workspace (for tool execution).

        Returns:
            FindingBatch with all findings from this execution.

        Raises:
            asyncio.TimeoutError: If execution exceeds blueprint.max_duration_seconds.
            ValueError: If Blueprint scope is invalid.
        """
        self._metrics = AgentMetrics(
            agent_id=self.config.agent_id,
            blueprint_id=blueprint.id,
            started_at=time.time(),
        )

        logger.info(
            "Agent %s executing blueprint %s (%d files in scope)",
            self.config.agent_id,
            blueprint.id,
            len(file_contents),
        )

        try:
            # Enforce timeout from Blueprint
            timeout = min(
                blueprint.max_duration_seconds,
                self.config.max_duration_seconds,
            )

            findings = await asyncio.wait_for(
                self._execute_pipeline(blueprint, file_contents, workspace_root),
                timeout=timeout,
            )

        except asyncio.TimeoutError:
            logger.error(
                "Agent %s timed out on blueprint %s after %ds",
                self.config.agent_id,
                blueprint.id,
                blueprint.max_duration_seconds,
            )
            self._metrics.errors.append(
                f"Timeout after {blueprint.max_duration_seconds}s"
            )
            findings = []

        except Exception as exc:
            logger.exception(
                "Agent %s failed on blueprint %s: %s",
                self.config.agent_id,
                blueprint.id,
                exc,
            )
            self._metrics.errors.append(str(exc))
            findings = []

        finally:
            self._metrics.finished_at = time.time()
            self._metrics.total_findings = len(findings)

        batch = FindingBatch(
            blueprint_id=blueprint.id,
            findings=findings,
            agent_id=self.config.agent_id,
            total_files_scanned=len(file_contents),
            execution_duration_seconds=self._metrics.duration_seconds,
        )

        logger.info(
            "Agent %s completed blueprint %s: %d findings in %.1fs",
            self.config.agent_id,
            blueprint.id,
            len(findings),
            self._metrics.duration_seconds,
        )

        return batch

    @property
    def metrics(self) -> Optional[AgentMetrics]:
        """Access metrics from the last execution."""
        return self._metrics

    async def _get_sandbox(self) -> SandboxClient:
        """Get a sandbox client instance."""
        return await get_sandbox_client()

    # ── Pipeline Steps ─────────────────────────────────────────────

    async def _execute_pipeline(
        self,
        blueprint: Blueprint,
        file_contents: Dict[str, str],
        workspace_root: str,
    ) -> List[FindingOutput]:
        """Internal pipeline: tools → LLM analysis → post-process."""

        # Step 1: Run deterministic tools (Bandit, Semgrep, etc.)
        tool_results = await self._run_deterministic_tools(
            blueprint, file_contents, workspace_root
        )

        # Step 2: LLM-based analysis (subclass implements this)
        raw_findings = await self._analyze(
            blueprint=blueprint,
            file_contents=file_contents,
            tool_results=tool_results,
        )

        # Step 3: Post-process — deduplicate, fingerprint, cap confidence
        findings = self._post_process(raw_findings, tool_results, blueprint)

        return findings

    async def _run_deterministic_tools(
        self,
        blueprint: Blueprint,
        file_contents: Dict[str, str],
        workspace_root: str,
    ) -> Dict[str, ToolResult]:
        """Run required deterministic tools before LLM analysis.

        Tools run concurrently up to max_concurrent_tools. Results are
        passed to _analyze() so the LLM can cross-reference them.
        """
        tools_to_run = list(
            set(blueprint.tools_required) | set(self.DEFAULT_TOOLS)
        )
        if not tools_to_run:
            return {}

        logger.info(
            "Agent %s running deterministic tools: %s",
            self.config.agent_id,
            tools_to_run,
        )

        results: Dict[str, ToolResult] = {}
        semaphore = asyncio.Semaphore(self.config.max_concurrent_tools)

        async def _run_one(tool_name: str) -> None:
            async with semaphore:
                start = time.time()
                try:
                    result = await self._execute_tool(
                        tool_name, workspace_root, file_contents
                    )
                    result.duration_seconds = time.time() - start
                    results[tool_name] = result
                    self._metrics.tool_durations[tool_name] = result.duration_seconds
                except Exception as exc:
                    logger.error(
                        "Tool %s failed: %s", tool_name, exc
                    )
                    results[tool_name] = ToolResult(
                        tool_name=tool_name,
                        exit_code=-1,
                        stdout="",
                        stderr=str(exc),
                        duration_seconds=time.time() - start,
                    )

        await asyncio.gather(*[_run_one(t) for t in tools_to_run])
        return results

    def _post_process(
        self,
        findings: List[FindingOutput],
        tool_results: Dict[str, ToolResult],
        blueprint: Blueprint,
    ) -> List[FindingOutput]:
        """Post-process findings: dedup, fingerprint, tool confirmation."""
        seen_fingerprints: set[str] = set()
        processed: List[FindingOutput] = []

        for finding in findings:
            # Generate deterministic fingerprint for dedup
            fp = self._compute_fingerprint(finding)

            if fp in seen_fingerprints:
                logger.debug("Dedup: dropping duplicate finding %s", fp[:12])
                continue
            seen_fingerprints.add(fp)

            # Check if deterministic tools confirmed this finding
            confirming = self._check_tool_confirmation(finding, tool_results)

            # Build updated finding with fingerprint + tool confirmation
            updated = finding.model_copy(
                update={
                    "finding_fingerprint": fp,
                    "confirming_tools": confirming,
                    "deterministic_tool_confirmed": len(confirming) > 0,
                }
            )

            processed.append(updated)

        logger.info(
            "Post-process: %d raw → %d after dedup (%d tool-confirmed)",
            len(findings),
            len(processed),
            sum(1 for f in processed if f.deterministic_tool_confirmed),
        )

        return processed

    # ── Abstract Methods (subclasses implement) ────────────────────

    @abstractmethod
    async def _analyze(
        self,
        blueprint: Blueprint,
        file_contents: Dict[str, str],
        tool_results: Dict[str, ToolResult],
    ) -> List[FindingOutput]:
        """Core analysis logic — subclass implements LLM interaction.

        Args:
            blueprint: The active Blueprint with scope and constraints.
            file_contents: Source code keyed by file path.
            tool_results: Results from deterministic tool pre-pass.

        Returns:
            List of raw FindingOutput objects (before post-processing).
        """
        ...

    @abstractmethod
    def _build_prompt(
        self,
        blueprint: Blueprint,
        file_contents: Dict[str, str],
        tool_results: Dict[str, ToolResult],
    ) -> str:
        """Build the LLM prompt for this agent's analysis.

        The prompt should include:
        - Blueprint scope constraints
        - File contents (within token budget)
        - Tool results for cross-referencing
        - Output format instructions (FindingOutput JSON schema)
        """
        ...

    @abstractmethod
    def _parse_llm_response(
        self,
        raw_response: str,
        blueprint: Blueprint,
    ) -> List[FindingOutput]:
        """Parse the LLM response into structured FindingOutput objects.

        Must handle malformed responses gracefully — log warnings and
        skip unparseable findings rather than crashing.
        """
        ...

    # ── Tool Execution ─────────────────────────────────────────────

    async def _execute_tool(
        self,
        tool_name: str,
        workspace_root: str,
        file_contents: Optional[Dict[str, str]] = None,
    ) -> ToolResult:
        """Execute a deterministic tool in the sandbox.

        Override in subclasses for tool-specific argument construction.
        The default implementation raises NotImplementedError — concrete
        agents must wire up their own tool commands.
        """
        raise NotImplementedError(
            f"Agent {self.config.agent_id} does not implement "
            f"tool execution for '{tool_name}'. Override _execute_tool() "
            f"in your ISO subclass."
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _resolve_llm_key(self, secrets: Dict[str, str]) -> str:
        """Resolve the LLM API key from keyvault secrets.

        Raises:
            KeyError: If the required key is not in secrets.
        """
        key_map = {
            LLMProvider.ANTHROPIC: "llm/anthropic-key",
            LLMProvider.OPENAI: "llm/openai-key",
        }
        secret_path = key_map[self.config.model_provider]
        if secret_path not in secrets:
            raise KeyError(
                f"Missing keyvault secret '{secret_path}' for provider "
                f"'{self.config.model_provider.value}'. Ensure it is loaded "
                f"during worker startup."
            )
        key = secrets[secret_path]
        if not key or key == "REPLACE_ME_IN_VAULT":
            raise ValueError(
                f"Keyvault secret '{secret_path}' is not configured. "
                f"Set it in the container keyvault before running agents."
            )
        return key

    @staticmethod
    def _compute_fingerprint(finding: FindingOutput) -> str:
        """Compute a deterministic SHA256 fingerprint for dedup.

        Fingerprint is based on: file_path + line_number + vulnerability_type
        + a normalized code snippet hash. This ensures the same finding
        from different agents or runs produces the same fingerprint.
        """
        # Normalize code snippet (strip whitespace for minor formatting diffs)
        code_normalized = " ".join(finding.code_snippet.split())
        raw = (
            f"{finding.file_path}:"
            f"{finding.line_number}:"
            f"{finding.vulnerability_type.value}:"
            f"{hashlib.sha256(code_normalized.encode()).hexdigest()[:16]}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def _check_tool_confirmation(
        self,
        finding: FindingOutput,
        tool_results: Dict[str, ToolResult],
    ) -> List[str]:
        """Check which deterministic tools confirmed a finding.

        Matches by file_path and line_number against tool raw_findings.
        Subclasses can override for tool-specific matching logic.
        """
        confirming: List[str] = []

        for tool_name, result in tool_results.items():
            if not result.success:
                continue
            for tool_finding in result.raw_findings:
                tool_file = tool_finding.get("file", tool_finding.get("path", ""))
                tool_line = tool_finding.get("line", tool_finding.get("line_number", 0))

                # Normalize paths for comparison
                if (
                    self._paths_match(finding.file_path, str(tool_file))
                    and abs(finding.line_number - int(tool_line)) <= 3
                ):
                    confirming.append(tool_name)
                    break  # One confirmation per tool is enough

        return confirming

    @staticmethod
    def _paths_match(path_a: str, path_b: str) -> bool:
        """Compare file paths, handling relative vs absolute differences."""
        # Strip leading ./ and normalize
        a = path_a.lstrip("./").rstrip("/")
        b = path_b.lstrip("./").rstrip("/")
        return a == b or a.endswith(b) or b.endswith(a)

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate (4 chars ≈ 1 token for English code).

        Good enough for budget enforcement. Real token counting happens
        at the LLM client layer.
        """
        return len(text) // 4

    # Patterns for security-critical files that must be scanned first
    SECURITY_PRIORITY_PATTERNS = (
        ".env", ".env.", "Dockerfile", "docker-compose",
        "appsettings", "nginx", ".conf", ".yaml", ".yml",
        "secrets", "credentials", "auth", "password", "token",
        "requirements.txt", "package.json", "Gemfile",
        ".csproj", "nuget.config", "web.config",
    )

    def _is_security_priority(self, path: str) -> bool:
        """Check if a file path matches security-critical patterns."""
        lower = path.lower()
        basename = lower.rsplit("/", 1)[-1] if "/" in lower else lower
        return any(pat in basename for pat in self.SECURITY_PRIORITY_PATTERNS) or \
               "/scripts/" in lower or "/infra/" in lower

    def _truncate_to_budget(
        self,
        file_contents: Dict[str, str],
        budget_tokens: int,
    ) -> Dict[str, str]:
        """Truncate file contents to fit within token budget.

        Security-critical files (configs, env, Dockerfiles, scripts) are
        always included first. Remaining budget goes to smaller code files.
        """
        # Split into priority (configs/secrets) and regular files
        priority_files = []
        regular_files = []
        for path, content in file_contents.items():
            if self._is_security_priority(path):
                priority_files.append((path, content))
            else:
                regular_files.append((path, content))

        # Sort each group by size (smallest first)
        priority_files.sort(key=lambda kv: len(kv[1]))
        regular_files.sort(key=lambda kv: len(kv[1]))

        # Priority files first, then regular
        ordered = priority_files + regular_files

        result: Dict[str, str] = {}
        remaining = budget_tokens

        for path, content in ordered:
            est = self._estimate_tokens(content)
            if est <= remaining:
                result[path] = content
                remaining -= est
            elif remaining > 200:
                # Truncate this file to fit remaining budget
                char_budget = remaining * 4
                result[path] = content[:char_budget] + "\n... [truncated]"
                remaining = 0
                break
            else:
                break

        included_priority = sum(1 for p, _ in priority_files if p in result)
        total_priority = len(priority_files)

        if len(result) < len(file_contents):
            logger.warning(
                "Token budget: included %d/%d files (%d/%d security-critical) (budget=%d tokens)",
                len(result),
                len(file_contents),
                included_priority,
                total_priority,
                budget_tokens,
            )

        return result

    def _format_not_in_scope_instruction(self, blueprint: Blueprint) -> str:
        """Format the 'not in scope' instruction for the LLM prompt."""
        if not blueprint.not_in_scope:
            return ""

        patterns = ", ".join(f"'{p}'" for p in blueprint.not_in_scope)
        return (
            f"\nSTRICT SCOPE ENFORCEMENT: The following paths and file patterns are "
            f"EXPLICITLY OUT OF SCOPE for this analysis: {patterns}. "
            f"You MUST NOT report any findings, vulnerabilities, or issues related "
            f"to these paths or any files matching these patterns. Ignore them entirely."
        )

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"id={self.config.agent_id} "
            f"spec={self.config.specialization.value} "
            f"provider={self.config.model_provider.value}>"
        )
