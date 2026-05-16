"""Spine auto-triggering skills (STORY-4.1.1 / 4.1.2 / 4.1.4).

Skills are markdown prompts with YAML trigger configs that fire at the right
moment inside a role daemon's invocation. Pattern absorbed from
`obra/superpowers` (see `docs/research/COMPETITIVE_LANDSCAPE.md §3`).

Public surface:
    discover_skills, list_skills, validate_skill_registry          (registry)
    TriggerContext, compute_triggered_skills, inject_skill_prompts (engine)
"""
from shared.skills.registry import (Skill, SkillTrigger, ValidationError,
                                    discover_skills, list_skills,
                                    validate_skill_registry)
from shared.skills.trigger_engine import (TriggerContext,
                                          compute_triggered_skills,
                                          inject_skill_prompts)

__all__ = ["Skill", "SkillTrigger", "ValidationError", "discover_skills",
           "list_skills", "validate_skill_registry", "TriggerContext",
           "compute_triggered_skills", "inject_skill_prompts"]
