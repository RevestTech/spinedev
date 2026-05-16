"""Trigger engine — decide which skills fire for a given directive context.

Implements STORY-4.1.1 (auto-trigger evaluation runtime). Role daemons call:

    ctx = TriggerContext(role="engineer", phase="build_in_progress",
                         directive_text="...", artifact_type="BuildArtifact",
                         project_id="proj-123")
    fired = compute_triggered_skills(ctx, registry)
    prompt = inject_skill_prompts(base_role_prompt, fired)
    # ...invoke LLM with `prompt`

Evaluation is AND-across `applies_when`, OR-across `applies_when_or`, then
filtered by role/phase/keyword pre-checks, then sorted by priority desc,
then truncated to fit `max_token_overhead` (sum across all fired skills,
default cap 2000 chars). Skills listed in `incompatible_with` of any
already-fired skill are dropped in order.
"""
from __future__ import annotations
import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.skills.registry import (DEFAULT_TOKEN_BUDGET, Skill,
                                    discover_skills)

DIRECTIVE_SHORT_THRESHOLD = 100  # chars; "vague" directive heuristic
SKILL_BLOCK_HEADER = "## SKILLS ACTIVE FOR THIS DIRECTIVE"
_BEGIN = "<!-- SPINE-SKILL: {slug} -->"
_END = "<!-- /SPINE-SKILL: {slug} -->"


class TriggerContext(BaseModel):
    """Runtime context the role daemon hands to the trigger engine."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    role: str
    phase: str
    directive_text: str = ""
    artifact_type: Optional[str] = None
    project_id: str = ""
    prior_skills_fired: list[str] = Field(default_factory=list)


def _matches_clause(clause: dict[str, Any], ctx: TriggerContext) -> bool:
    """Evaluate a single AND-clause from applies_when / applies_when_or.

    Multiple keys inside one clause dict are all-must-match. Unknown keys
    cause the clause to evaluate False — be explicit, not surprising.
    """
    if not clause:
        return False
    directive = (ctx.directive_text or "")
    directive_l = directive.lower()
    for key, expected in clause.items():
        if key == "directive_contains":
            if not isinstance(expected, str) \
                    or expected.lower() not in directive_l:
                return False
        elif key == "directive_short":
            if bool(expected) is not (len(directive) < DIRECTIVE_SHORT_THRESHOLD):
                return False
        elif key == "role":
            if expected != ctx.role:
                return False
        elif key == "phase":
            if expected != ctx.phase:
                return False
        elif key == "artifact_about_to_be_emitted":
            if expected != ctx.artifact_type:
                return False
        else:
            return False
    return True


def _keyword_match(skill: Skill, directive_text: str) -> bool:
    """`applies_to_directive_keywords` is OR-semantics; empty list = match-all."""
    kws = skill.trigger.applies_to_directive_keywords
    if not kws:
        return True
    text = directive_text or ""
    for kw in kws:
        # Treat each entry as a regex if it parses; fall back to substring.
        try:
            if re.search(kw, text, flags=re.IGNORECASE):
                return True
        except re.error:
            if kw.lower() in text.lower():
                return True
    return False


def _passes_filters(skill: Skill, ctx: TriggerContext) -> bool:
    """Hard pre-filters: role + phase + keyword. Empty list = no constraint."""
    if skill.trigger.applies_to_roles \
            and ctx.role not in skill.trigger.applies_to_roles:
        return False
    if skill.trigger.applies_to_phases \
            and ctx.phase not in skill.trigger.applies_to_phases:
        return False
    if not _keyword_match(skill, ctx.directive_text):
        return False
    return True


def _passes_rules(skill: Skill, ctx: TriggerContext) -> bool:
    """`applies_when` (AND-across-list) and `applies_when_or` (OR-across-list)
    are independent paths. Either passing fires the skill; both empty also
    fires (assuming pre-filters passed) — the role/phase/keyword filters are
    the only constraint in that case.
    """
    and_rules = skill.trigger.applies_when
    or_rules = skill.trigger.applies_when_or
    if not and_rules and not or_rules:
        return True
    and_ok = bool(and_rules) and all(_matches_clause(c, ctx) for c in and_rules)
    or_ok = bool(or_rules) and any(_matches_clause(c, ctx) for c in or_rules)
    return and_ok or or_ok


def compute_triggered_skills(context: TriggerContext,
                             registry: Optional[dict[str, Skill]] = None,
                             token_budget: int = DEFAULT_TOKEN_BUDGET
                             ) -> list[Skill]:
    """Return the firing order — priority desc, capped by token budget."""
    reg = registry if registry is not None else discover_skills()
    candidates: list[Skill] = []
    for skill in reg.values():
        if not _passes_filters(skill, context):
            continue
        if not _passes_rules(skill, context):
            continue
        candidates.append(skill)
    candidates.sort(key=lambda s: (-s.priority, s.slug))

    fired: list[Skill] = []
    fired_slugs: set[str] = set(context.prior_skills_fired)
    incompatible_blocked: set[str] = set()
    for slug in context.prior_skills_fired:
        prior = reg.get(slug)
        if prior:
            incompatible_blocked.update(prior.incompatible_with)
    spent = 0
    for skill in candidates:
        if skill.slug in fired_slugs or skill.slug in incompatible_blocked:
            continue
        # Estimate overhead by the lesser of declared budget and actual length.
        overhead = min(skill.max_token_overhead, len(skill.prompt_text))
        if spent + overhead > token_budget:
            continue
        fired.append(skill)
        fired_slugs.add(skill.slug)
        incompatible_blocked.update(skill.incompatible_with)
        spent += overhead
    return fired


def inject_skill_prompts(role_prompt_text: str,
                         skills: list[Skill]) -> str:
    """Append fired skill prompts after the base role prompt, with markers."""
    if not skills:
        return role_prompt_text
    parts: list[str] = [role_prompt_text.rstrip(), "", "", SKILL_BLOCK_HEADER, ""]
    for skill in skills:
        body = skill.prompt_text.strip()
        parts.append(_BEGIN.format(slug=skill.slug))
        parts.append(body)
        parts.append(_END.format(slug=skill.slug))
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"
