"""Architect Technical Review Swarm — LangGraph wiring for Hub ``architect`` role."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from plan.artifacts.trd_v1 import TRDv1
from plan.runtime.prd_from_metadata import prd_from_project, swarm_project_type
from plan.swarm.scout_contribution import (
    DEFAULT_LENS_FOR_ROLE,
    Finding,
    FindingKind,
    ScoutContribution,
    ScoutRole,
    Severity,
)
from plan.swarm.swarm_engine import run_swarm
from shared.llm import LLMRequest, Message, call

logger = logging.getLogger("spine.plan.architect_swarm")
_DEFAULT_MODEL = os.environ.get("SPINE_INTAKE_MODEL", "claude-sonnet-4-6")
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


@dataclass
class ArchitectSwarmResult:
    ok: bool
    trd_md: str = ""
    swarm_run_id: str = ""
    scouts_run: list[str] = field(default_factory=list)
    scouts_unrun: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    error_class: str | None = None
    error_message: str | None = None


def swarm_enabled() -> bool:
    return os.environ.get("SPINE_ARCHITECT_SWARM", "1").strip().lower() not in ("0", "false", "no")


class LlmScoutDispatcher:
    """One LLM call per scout role; returns structured ``ScoutContribution``."""

    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or _DEFAULT_MODEL

    def __call__(
        self,
        role: ScoutRole,
        scope: str,
        prd: dict[str, Any],
    ) -> ScoutContribution:
        lens = DEFAULT_LENS_FOR_ROLE[role]
        system = (
            f"You are the Spine **{role.value}** scout in the architect TRD swarm. "
            f"Lens: {lens.value}. Assess the PRD from your specialty and return "
            "ONLY valid JSON with keys: findings (list of "
            "{severity, kind, file_or_section, description, recommendation}), "
            "risks (list), open_questions (list). "
            "severity: info|low|medium|high|critical. "
            "kind: constraint|recommendation|dependency|gap|opportunity."
        )
        user = (
            f"## Scope\n{scope}\n\n## PRD\n```json\n"
            f"{json.dumps(prd, default=str)[:12000]}\n```"
        )
        resp = call(LLMRequest(
            model=self.model,
            system=system,
            messages=[Message(role="user", content=user)],
            max_tokens=4000,
            temperature=0.2,
        ))
        raw = resp.content.strip()
        findings: list[Finding] = []
        try:
            match = _JSON_BLOCK_RE.search(raw)
            payload = json.loads(match.group(0) if match else raw)
            for item in payload.get("findings") or []:
                if not isinstance(item, dict):
                    continue
                findings.append(Finding(
                    severity=Severity(str(item.get("severity", "low")).lower()),
                    kind=FindingKind(str(item.get("kind", "recommendation")).lower()),
                    file_or_section=str(item.get("file_or_section") or "global")[:120],
                    description=str(item.get("description") or "Scout finding")[:500],
                    recommendation=(str(item["recommendation"])[:300] if item.get("recommendation") else None),
                ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("scout_json_parse_failed", extra={"role": role.value, "err": str(exc)})
            findings = [Finding(
                severity=Severity.MEDIUM,
                kind=FindingKind.RECOMMENDATION,
                file_or_section="global",
                description=raw[:500] or f"{role.value} scout summary unavailable.",
                recommendation="Review manually during TRD approval.",
            )]

        if not findings:
            findings = [Finding(
                severity=Severity.LOW,
                kind=FindingKind.GAP,
                file_or_section="global",
                description=f"{role.value} scout returned no structured findings.",
                recommendation="Proceed with architect synthesis defaults.",
            )]

        return ScoutContribution(
            scout_role=role,
            lens=lens,
            scope_received=scope[:500],
            findings=findings,
            model_used=self.model,
            confidence=0.6,
        )


def run_architect_swarm(project: dict[str, Any], *, pipeline_version: str = "1") -> ArchitectSwarmResult:
    """Run LangGraph swarm (linear fallback when LangGraph absent)."""
    if not swarm_enabled():
        return ArchitectSwarmResult(
            ok=False,
            error_class="swarm_disabled",
            error_message="SPINE_ARCHITECT_SWARM=0",
        )

    prd = prd_from_project(project)
    try:
        state = run_swarm(
            prd,
            swarm_project_type(project),
            pipeline_version=pipeline_version,
            dispatcher=LlmScoutDispatcher(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("architect_swarm_failed")
        return ArchitectSwarmResult(
            ok=False,
            error_class=type(exc).__name__,
            error_message=str(exc)[:500],
        )

    trd_payload = state.get("trd_payload")
    if not trd_payload:
        return ArchitectSwarmResult(
            ok=False,
            swarm_run_id=str(state.get("run_id") or ""),
            scouts_run=[c.get("scout_role", "?") for c in (state.get("contributions") or []) if isinstance(c, dict)],
            scouts_unrun=list(state.get("unrun") or []),
            validation_errors=list(state.get("validation_errors") or []),
            error_class="synthesis_failed",
            error_message="; ".join(state.get("validation_errors") or ["no TRD produced"]),
        )

    trd = TRDv1.model_validate(trd_payload)
    md = trd.to_markdown()
    unrun = list(state.get("unrun") or [])
    if unrun:
        md += "\n\n---\n\n## Swarm degraded\n\nScouts that did not run: " + ", ".join(unrun) + "\n"

    return ArchitectSwarmResult(
        ok=True,
        trd_md=md,
        swarm_run_id=str(state.get("run_id") or ""),
        scouts_run=[
            str(c.get("scout_role")) for c in (state.get("contributions") or [])
            if isinstance(c, dict) and c.get("scout_role")
        ],
        scouts_unrun=unrun,
        validation_errors=list(state.get("validation_errors") or []),
    )


__all__ = ["ArchitectSwarmResult", "LlmScoutDispatcher", "run_architect_swarm", "swarm_enabled"]
