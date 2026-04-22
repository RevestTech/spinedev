"""
Manager Agent — orchestrates ISO agents for an audit run.

The Manager:
1. Receives an audit request (project + scope)
2. Creates Blueprints for each analysis dimension
3. Dispatches Blueprints to specialized ISO agents
4. Collects FindingBatches from all agents
5. Runs cross-validation between agents (different LLM providers)
6. Produces the final consolidated audit result

Architecture ref: docs/architecture/AI_AGENT_ARCHITECTURE.md §5
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from tron.agents.base import (
    BaseISO,
    ISOConfig,
    ISOSpecialization,
    LLMProvider,
    AgentMetrics,
)
from tron.infra.llm.client import DEFAULT_ANTHROPIC_FAST_MODEL, LLMClient
from tron.schemas.verification import (
    Blueprint,
    BlueprintScope,
    CrossValidationResult,
    CrossValidationStatus,
    ConsensusLevel,
    FindingBatch,
    FindingOutput,
    SeverityLevel,
    VerificationMethod,
    VulnerabilityType,
)

logger = logging.getLogger(__name__)


# ── Audit Request / Result ─────────────────────────────────────────────


@dataclass
class AuditRequest:
    """Input to the Manager for a full audit run."""

    project_id: UUID
    audit_run_id: UUID
    file_contents: Dict[str, str]   # {path: source_code}
    languages: List[str]            # e.g. ["python", "javascript"]
    workspace_root: str = "/workspace"
    check_types: Optional[List[VulnerabilityType]] = None

    def __post_init__(self):
        if self.check_types is None:
            # Default: check all vulnerability types
            self.check_types = list(VulnerabilityType)


@dataclass
class AuditResult:
    """Output from a complete audit run."""

    audit_run_id: UUID
    project_id: UUID
    findings: List[FindingOutput]
    cross_validations: List[CrossValidationResult]
    agent_metrics: List[Dict[str, Any]]
    total_files_scanned: int = 0
    duration_seconds: float = 0.0
    status: str = "completed"  # completed | failed | partial
    errors: List[str] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SeverityLevel.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SeverityLevel.HIGH)

    @property
    def confirmed_count(self) -> int:
        return sum(1 for f in self.findings if f.deterministic_tool_confirmed)


# ── Manager ────────────────────────────────────────────────────────────


class AuditManager:
    """Orchestrates ISO agents for a complete audit run.

    The Manager does NOT do analysis itself — it coordinates agents
    that each handle a specific dimension (security, performance, etc.).

    Usage:
        manager = AuditManager(secrets=secrets)
        manager.register_agent(security_iso)
        result = await manager.run_audit(request)
    """

    def __init__(
        self,
        secrets: Dict[str, str],
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        self._secrets = secrets
        self._agents: Dict[ISOSpecialization, BaseISO] = {}
        self._llm = llm_client or LLMClient(
            anthropic_key=secrets.get("llm/anthropic-key"),
            openai_key=secrets.get("llm/openai-key"),
        )

    def register_agent(self, agent: BaseISO) -> None:
        """Register an ISO agent for use in audits."""
        spec = agent.config.specialization
        self._agents[spec] = agent
        logger.info(
            "Registered agent: %s (%s)",
            agent.config.agent_id,
            spec.value,
        )

    # ── Run Audit ──────────────────────────────────────────────────

    async def run_audit(self, request: AuditRequest) -> AuditResult:
        """Execute a full audit: dispatch agents → collect → cross-validate."""
        start = time.time()

        logger.info(
            "Audit %s starting: project=%s, files=%d, agents=%d",
            request.audit_run_id,
            request.project_id,
            len(request.file_contents),
            len(self._agents),
        )

        if not self._agents:
            return AuditResult(
                audit_run_id=request.audit_run_id,
                project_id=request.project_id,
                findings=[],
                cross_validations=[],
                agent_metrics=[],
                status="failed",
                errors=["No agents registered"],
            )

        # Step 1: Create blueprints for each agent
        blueprints = self._create_blueprints(request)

        # Step 2: Dispatch agents concurrently
        batches = await self._dispatch_agents(request, blueprints)

        # Step 3: Merge and deduplicate findings
        all_findings = self._merge_findings(batches)

        # Step 4: Cross-validate critical/high findings
        cross_validations = await self._cross_validate(
            all_findings, request
        )

        # Step 5: Apply cross-validation results to findings
        final_findings = self._apply_cross_validation(
            all_findings, cross_validations
        )

        # Collect metrics
        agent_metrics = []
        for agent in self._agents.values():
            if agent.metrics:
                agent_metrics.append(agent.metrics.to_dict())

        duration = time.time() - start

        result = AuditResult(
            audit_run_id=request.audit_run_id,
            project_id=request.project_id,
            findings=final_findings,
            cross_validations=cross_validations,
            agent_metrics=agent_metrics,
            total_files_scanned=len(request.file_contents),
            duration_seconds=duration,
        )

        logger.info(
            "Audit %s completed in %.1fs: %d findings (%d critical, %d high, %d confirmed)",
            request.audit_run_id,
            duration,
            len(final_findings),
            result.critical_count,
            result.high_count,
            result.confirmed_count,
        )

        return result

    # ── Blueprint Creation ─────────────────────────────────────────

    def _create_blueprints(
        self, request: AuditRequest
    ) -> Dict[ISOSpecialization, Blueprint]:
        """Create a Blueprint for each registered agent."""
        blueprints: Dict[ISOSpecialization, Blueprint] = {}

        # File patterns from actual file extensions in the request
        extensions = set()
        for path in request.file_contents:
            if "." in path:
                ext = path.rsplit(".", 1)[1]
                extensions.add(f"*.{ext}")

        file_patterns = list(extensions) if extensions else ["*.*"]

        for spec, agent in self._agents.items():
            bp = Blueprint(
                id=f"{request.audit_run_id}-{spec.value}",
                name=f"{spec.value.title()} Analysis",
                description=f"{spec.value.title()} analysis for project {request.project_id}",
                scope=BlueprintScope(
                    file_patterns=file_patterns,
                    check_types=request.check_types,
                    languages=request.languages,
                ),
                tools_required=list(agent.config.tools_required),
                max_tokens=agent.config.max_tokens,
                max_duration_seconds=agent.config.max_duration_seconds,
                temperature=agent.config.temperature,
                verification_method=VerificationMethod.DETERMINISTIC_CROSSCHECK,
            )
            blueprints[spec] = bp

        return blueprints

    # ── Agent Dispatch ─────────────────────────────────────────────

    async def _dispatch_agents(
        self,
        request: AuditRequest,
        blueprints: Dict[ISOSpecialization, Blueprint],
    ) -> List[FindingBatch]:
        """Dispatch all agents concurrently and collect results."""

        async def _run_agent(
            spec: ISOSpecialization,
        ) -> Optional[FindingBatch]:
            agent = self._agents[spec]
            blueprint = blueprints[spec]
            try:
                return await agent.execute(
                    blueprint=blueprint,
                    file_contents=request.file_contents,
                    workspace_root=request.workspace_root,
                )
            except Exception as exc:
                logger.exception(
                    "Agent %s failed: %s", agent.config.agent_id, exc
                )
                return None

        tasks = [_run_agent(spec) for spec in self._agents]
        results = await asyncio.gather(*tasks)

        return [r for r in results if r is not None]

    # ── Merge & Dedup ──────────────────────────────────────────────

    def _merge_findings(
        self, batches: List[FindingBatch]
    ) -> List[FindingOutput]:
        """Merge findings from all agents, deduplicating by fingerprint."""
        seen: Dict[str, FindingOutput] = {}

        for batch in batches:
            for finding in batch.findings:
                fp = finding.finding_fingerprint
                if fp in seen:
                    # Keep the one with higher confidence or tool confirmation
                    existing = seen[fp]
                    if (
                        finding.deterministic_tool_confirmed
                        and not existing.deterministic_tool_confirmed
                    ) or finding.confidence > existing.confidence:
                        seen[fp] = finding
                else:
                    seen[fp] = finding

        merged = list(seen.values())
        logger.info(
            "Merged %d total findings from %d batches → %d unique",
            sum(len(b.findings) for b in batches),
            len(batches),
            len(merged),
        )
        return merged

    # ── Cross-Validation ───────────────────────────────────────────

    async def _cross_validate(
        self,
        findings: List[FindingOutput],
        request: AuditRequest,
    ) -> List[CrossValidationResult]:
        """Cross-validate critical and high findings.

        Only findings with severity >= HIGH get cross-validated.
        Cross-validation uses a DIFFERENT LLM provider than the
        primary agent to prevent correlated failures.
        """
        to_validate = [
            f for f in findings
            if f.severity in (SeverityLevel.CRITICAL, SeverityLevel.HIGH)
            and not f.deterministic_tool_confirmed
        ]

        if not to_validate:
            return []

        logger.info(
            "Cross-validating %d critical/high findings", len(to_validate)
        )

        results: List[CrossValidationResult] = []

        for finding in to_validate:
            try:
                result = await self._validate_single_finding(finding, request)
                if result:
                    results.append(result)
            except Exception as exc:
                logger.warning(
                    "Cross-validation failed for finding %s: %s",
                    finding.id, exc,
                )

        return results

    async def _validate_single_finding(
        self,
        finding: FindingOutput,
        request: AuditRequest,
    ) -> Optional[CrossValidationResult]:
        """Validate a single finding using a different LLM provider."""
        # Determine primary provider from the agent that found it
        primary_agent = self._agents.get(ISOSpecialization.SECURITY)
        if not primary_agent:
            return None

        primary_provider = primary_agent.config.model_provider

        # Pick the opposite provider for validation
        if primary_provider == LLMProvider.ANTHROPIC:
            validator_provider = LLMProvider.OPENAI
            validator_model = "gpt-4o"
        else:
            validator_provider = LLMProvider.ANTHROPIC
            validator_model = DEFAULT_ANTHROPIC_FAST_MODEL

        # Get the source code for this finding
        source_code = request.file_contents.get(finding.file_path, "")
        if not source_code:
            return None

        # Ask the validator model to independently assess
        from tron.infra.llm.client import LLMMessage, LLMRequest

        prompt = (
            f"Review this code and determine if there is a "
            f"{finding.vulnerability_type.value} vulnerability "
            f"at line {finding.line_number}.\n\n"
            f"File: {finding.file_path}\n"
            f"```\n{source_code[:4000]}\n```\n\n"
            f"Respond with JSON: "
            f'{{"found": true/false, "confidence": 0.0-1.0, "reasoning": "..."}}'
        )

        response = await self._llm.complete(
            LLMRequest(
                messages=[
                    LLMMessage(
                        role="system",
                        content="You are a security validation agent. "
                        "Independently assess whether the described "
                        "vulnerability exists. Be precise and skeptical.",
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                model=validator_model,
                temperature=0.1,
                max_tokens=500,
                json_mode=True,
            )
        )

        # Parse validator response
        try:
            import json
            data = json.loads(response.content)
            validator_found = bool(data.get("found", False))
        except (json.JSONDecodeError, KeyError):
            validator_found = False

        # Determine consensus
        if validator_found:
            consensus = ConsensusLevel.CONFIRMED
            adjustment = 0.15
        else:
            consensus = ConsensusLevel.DISPUTED
            adjustment = -0.2

        return CrossValidationResult(
            finding_id=finding.id,
            primary_agent=finding.agent_id,
            primary_model_provider=primary_provider.value,
            validation_agent=f"validator-{validator_provider.value}",
            validator_model_provider=validator_provider.value,
            primary_found=True,
            validator_found=validator_found,
            consensus=consensus,
            confidence_adjustment=adjustment,
        )

    # ── Apply Validation ───────────────────────────────────────────

    def _apply_cross_validation(
        self,
        findings: List[FindingOutput],
        validations: List[CrossValidationResult],
    ) -> List[FindingOutput]:
        """Apply cross-validation results to findings."""
        validation_map: Dict[UUID, CrossValidationResult] = {
            v.finding_id: v for v in validations
        }

        updated: List[FindingOutput] = []
        for finding in findings:
            cv = validation_map.get(finding.id)
            if cv:
                new_status = (
                    CrossValidationStatus.CONFIRMED
                    if cv.consensus == ConsensusLevel.CONFIRMED
                    else CrossValidationStatus.DISPUTED
                )
                new_confidence = max(
                    0.0,
                    min(1.0, finding.confidence + cv.confidence_adjustment),
                )
                finding = finding.model_copy(
                    update={
                        "cross_validation_status": new_status,
                        "calibrated_confidence": new_confidence,
                    }
                )
            updated.append(finding)

        confirmed = sum(
            1 for f in updated
            if f.cross_validation_status == CrossValidationStatus.CONFIRMED
        )
        disputed = sum(
            1 for f in updated
            if f.cross_validation_status == CrossValidationStatus.DISPUTED
        )
        logger.info(
            "Cross-validation applied: %d confirmed, %d disputed",
            confirmed,
            disputed,
        )

        return updated
