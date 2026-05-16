"""
Architect synthesis: merge per-scout contributions into a `trd-v1`.

Implements `STORY-1.2.4` (synthesis pattern) from `docs/BACKLOG.md`. The
swarm engine (`swarm_engine.py`) calls `synthesize_trd()` once every
dispatched scout has returned a `ScoutContribution`.

Two-pass:
  1. **Deterministic merge** — group by lens; map lens → TRD section; union
     + dedupe risks/open-questions across scouts.
  2. **LLM prose pass** (optional `ProsePass`) — fills narrative fields via
     `shared/cost/router.py` at `medium` tier. Pass 1 alone yields a valid
     TRD, so the swarm survives LLM outages.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional

from plan.artifacts._base import (
    ArtifactMetadata, ArtifactStatus, OpenQuestion as TRDOpenQuestion, Size,
)
from plan.artifacts.prd_v1 import PRDv1
from plan.artifacts.trd_v1 import (
    ArchitectureSection, Component, CostProjection,
    Impact as TRDImpact, Likelihood as TRDLikelihood,
    NonFunctionalRequirements, Risk, ScopeEstimate, TechChoice, TRDv1,
)

from .scout_contribution import Finding, FindingKind, ScoutContribution, ScoutLens


class SynthesisError(Exception):
    """Raised when synthesis cannot build a valid TRD even after retry."""


# prose_fn(section_name, raw_inputs) -> str
ProsePass = Callable[[str, list[str]], str]


def _by_lens(cs: Iterable[ScoutContribution]) -> dict[ScoutLens, list[ScoutContribution]]:
    out: dict[ScoutLens, list[ScoutContribution]] = {}
    for c in cs:
        out.setdefault(c.lens, []).append(c)
    return out


def _components_from(findings: Iterable[Finding]) -> list[Component]:
    """Promote RECOMMENDATION findings to first-cut Components."""
    seen: set[str] = set()
    comps: list[Component] = []
    for f in findings:
        if f.kind != FindingKind.RECOMMENDATION:
            continue
        name = (f.file_or_section or "component").strip()[:60] or "component"
        if name in seen:
            continue
        seen.add(name)
        comps.append(Component(name=name, responsibility=f.description[:140]))
    return comps


def _dedupe_risks(cs: Iterable[ScoutContribution]) -> list[Risk]:
    seen: dict[str, Risk] = {}
    for c in cs:
        for r in c.risks:
            key = r.description.strip().lower()
            if key in seen:
                continue
            seen[key] = Risk(
                description=r.description,
                likelihood=TRDLikelihood(r.likelihood.value),
                impact=TRDImpact(r.impact.value),
                mitigation=r.mitigation or "Defer to architect during build.",
            )
    return list(seen.values())


def _dedupe_oqs(cs: Iterable[ScoutContribution]) -> list[TRDOpenQuestion]:
    seen: dict[str, TRDOpenQuestion] = {}
    for c in cs:
        for oq in c.open_questions:
            key = oq.question.strip().lower()
            if key in seen:
                continue
            seen[key] = TRDOpenQuestion(
                id=oq.id, question=oq.question, recommendation=oq.recommendation
            )
    return list(seen.values())


def _nfrs_from(by_lens: dict[ScoutLens, list[ScoutContribution]]) -> NonFunctionalRequirements:
    """operator → perf/scalability/observability; engineer → security/cost."""
    def _join(rcs: list[ScoutContribution]) -> str:
        bits = [f.description for c in rcs for f in c.findings
                if f.severity.value in ("medium", "high", "critical")]
        return " ".join(bits)[:400]
    ops = by_lens.get(ScoutLens.INFRA, [])
    eng = by_lens.get(ScoutLens.FEASIBILITY, [])
    return NonFunctionalRequirements(
        performance=_join(ops) or "Defer until load profile measured.",
        security=_join(eng) or "Default deny; review during build.",
        scalability=_join(ops) or "Scale-out path TBD by operator.",
        observability=_join(ops) or "Structured logs; metrics per phase.",
        cost=_join(eng) or "Budget caps enforced by router.",
    )


def _tech_choices_from(eng: list[ScoutContribution]) -> list[TechChoice]:
    return [
        TechChoice(
            concern=(f.file_or_section or "tech-choice")[:60],
            decision=f.recommendation[:80],
            rationale=f.description[:200] or "See scout finding.",
            alternatives_considered=[],
        )
        for c in eng for f in c.findings
        if f.kind == FindingKind.RECOMMENDATION and f.recommendation
    ]


def _arch_prose(
    researcher: list[ScoutContribution], engineer: list[ScoutContribution],
    prose: Optional[ProsePass],
) -> tuple[str, str]:
    def _bullet(cs: list[ScoutContribution]) -> list[str]:
        return [f"{c.scout_role.value}: {' '.join(f.description for f in c.findings[:3])}"
                for c in cs]
    ov_raw, fl_raw = _bullet(researcher + engineer), _bullet(engineer)
    if prose is not None:
        return (prose("system_overview", ov_raw) or "TBD",
                prose("data_flow", fl_raw) or "TBD")
    return (" ".join(ov_raw)[:1000] or "Deterministic synthesis: see component list below.",
            " ".join(fl_raw)[:1000] or "Deterministic synthesis: see component responsibilities.")


def synthesize_trd(
    prd: PRDv1,
    contributions: list[ScoutContribution],
    *,
    prose_pass: Optional[ProsePass] = None,
    created_by: str = "architect",
) -> TRDv1:
    """Merge scout contributions into a validated `trd-v1`. Raises
    `SynthesisError` on Pydantic failure — caller retries with simpler prompt."""
    by_lens = _by_lens(contributions)
    engineer = by_lens.get(ScoutLens.FEASIBILITY, [])
    researcher = by_lens.get(ScoutLens.CURRENT_STATE, [])
    arch_findings = [f for c in (engineer + researcher) for f in c.findings]
    overview, flow = _arch_prose(researcher, engineer, prose_pass)
    architecture = ArchitectureSection(
        system_overview=overview,
        components=_components_from(arch_findings),
        data_flow=flow,
    )
    try:
        return TRDv1(
            project_id=prd.project_id,
            prd_ref=f"PRD::{prd.project_id}#{prd.version}",
            architecture=architecture,
            data_model=None,  # datawright lens — EPIC-1.2 follow-up
            integrations=[],
            nfrs=_nfrs_from(by_lens),
            tech_choices=_tech_choices_from(engineer),
            risks=_dedupe_risks(contributions),
            open_questions=_dedupe_oqs(contributions),
            scope_estimate=ScopeEstimate(
                epics_count=max(1, len(prd.goals.must)),
                stories_count=max(1, len(prd.acceptance_criteria)),
                estimated_size=Size.M),
            cost_projection=CostProjection(
                build_phase_estimate=0.0, verify_phase_estimate=0.0, total_estimate=0.0),
            metadata=ArtifactMetadata(created_by=created_by, status=ArtifactStatus.DRAFT),
        )
    except Exception as e:  # pragma: no cover — defensive
        raise SynthesisError(f"TRD validation failed: {e}") from e


__all__ = ["ProsePass", "SynthesisError", "synthesize_trd"]
