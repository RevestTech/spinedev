"""Interactive PLAN questionnaire — compile answers for the LLM and `.tron` bundle."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

# Keys expected from the UI wizard (all optional strings except compliance_frameworks).
QUESTIONNAIRE_KEYS = (
    "product_summary",
    "primary_users",
    "success_metrics",
    "tech_stack",
    "deployment_model",
    "scale_expectations",
    "compliance_frameworks",
    "data_classes",
    "integrations",
    "non_functional",
    "timeline",
    "risks_assumptions",
    "open_questions",
)


def questionnaire_has_substance(q: Optional[Dict[str, Any]]) -> bool:
    if not q or not isinstance(q, dict):
        return False
    for key in QUESTIONNAIRE_KEYS:
        val = q.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            if any(str(x).strip() for x in val):
                return True
        elif str(val).strip():
            return True
    return False


def compile_plan_inputs(
    goals: str,
    constraints: str,
    questionnaire: Optional[Dict[str, Any]],
) -> Tuple[str, str]:
    """
    Merge free-text goals/constraints with structured questionnaire answers.

    Returns (effective_goals, effective_constraints) for the planner LLM.
    """
    g = (goals or "").strip()
    c = (constraints or "").strip()
    q = questionnaire or {}

    goal_parts: list[str] = []
    if q.get("product_summary"):
        goal_parts.append(f"**Product / outcome**\n{q['product_summary'].strip()}")
    if q.get("primary_users"):
        goal_parts.append(f"**Primary users / personas**\n{q['primary_users'].strip()}")
    if q.get("success_metrics"):
        goal_parts.append(f"**Success metrics**\n{q['success_metrics'].strip()}")

    cons_parts: list[str] = []
    if q.get("tech_stack"):
        cons_parts.append(f"**Tech stack & preferences**\n{q['tech_stack'].strip()}")
    if q.get("deployment_model"):
        cons_parts.append(f"**Deployment model**\n{q['deployment_model'].strip()}")
    if q.get("scale_expectations"):
        cons_parts.append(f"**Scale & SLO expectations**\n{q['scale_expectations'].strip()}")

    cf = q.get("compliance_frameworks")
    if isinstance(cf, list) and cf:
        cons_parts.append(
            "**Compliance frameworks**\n" + ", ".join(str(x) for x in cf if str(x).strip())
        )
    elif isinstance(cf, str) and cf.strip():
        cons_parts.append(f"**Compliance frameworks**\n{cf.strip()}")

    if q.get("data_classes"):
        cons_parts.append(f"**Sensitive data classes**\n{q['data_classes'].strip()}")
    if q.get("integrations"):
        cons_parts.append(f"**Integrations & external systems**\n{q['integrations'].strip()}")
    if q.get("non_functional"):
        cons_parts.append(f"**Non-functional requirements**\n{q['non_functional'].strip()}")
    if q.get("timeline"):
        cons_parts.append(f"**Timeline / milestones**\n{q['timeline'].strip()}")
    if q.get("risks_assumptions"):
        cons_parts.append(f"**Known risks & assumptions**\n{q['risks_assumptions'].strip()}")
    if q.get("open_questions"):
        cons_parts.append(f"**Open questions**\n{q['open_questions'].strip()}")

    q_goals_block = "\n\n".join(goal_parts)
    q_cons_block = "\n\n".join(cons_parts)

    if len(g) < 3:
        g = q_goals_block or "Define goals using the questionnaire or free-text goals field."
    elif q_goals_block:
        g = f"{g}\n\n---\n**From structured questionnaire:**\n\n{q_goals_block}"

    if not c.strip():
        c = q_cons_block or ""
    elif q_cons_block:
        c = f"{c}\n\n---\n**From structured questionnaire:**\n\n{q_cons_block}"

    return g, c
