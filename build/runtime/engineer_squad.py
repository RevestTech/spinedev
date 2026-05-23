"""Engineer squad-lead — coordinates specialty subagents (#13 hybrid + institutional roles).

The **engineer** role acts as squad lead. Specialty workers (frontend,
backend, database) produce FILE/RUN blocks in parallel; the lead merges,
dedupes paths, and seals one commit under a single directive.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from shared.llm import LLMRequest, Message, call_async

logger = logging.getLogger("spine.build.engineer_squad")
_DEFAULT_MODEL = os.environ.get("SPINE_INTAKE_MODEL", "claude-sonnet-4-6")

_SPECIALTIES: tuple[tuple[str, str], ...] = (
    (
        "frontend",
        "You are the **frontend subagent** under the Spine engineer squad. "
        "Produce UI/client code only (components, pages, styles, client API calls). "
        "Use FILE/RUN blocks. Do not implement server/database layers.",
    ),
    (
        "backend",
        "You are the **backend subagent** under the Spine engineer squad. "
        "Produce API/server code only (routes, services, auth, business logic). "
        "Use FILE/RUN blocks. Coordinate with frontend via clear API contracts.",
    ),
    (
        "database",
        "You are the **database subagent** under the Spine engineer squad. "
        "Produce schema/migrations/seed data and data-access layers. "
        "Use FILE/RUN blocks. Keep migrations idempotent where possible.",
    ),
)


@dataclass
class SquadMergeResult:
    intro_md: str
    raw_combined: str
    specialties_run: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def squad_enabled() -> bool:
    return os.environ.get("SPINE_ENGINEER_SQUAD", "1").strip().lower() not in ("0", "false", "no")


async def _run_specialty(
    *,
    specialty: str,
    specialty_prompt: str,
    system_base: str,
    user_msg: str,
) -> tuple[str, str]:
    system = (
        specialty_prompt
        + "\n\n---\n\n"
        + system_base
        + f"\n\n---\n\n## Squad scope\n\nYou own the **{specialty}** slice only."
    )
    resp = await call_async(LLMRequest(
        model=_DEFAULT_MODEL,
        messages=[Message(role="user", content=user_msg)],
        system=system,
        max_tokens=24000,
        temperature=0.2,
    ))
    return specialty, resp.content.strip()


async def run_engineer_squad(
    *,
    system_base: str,
    user_msg: str,
    project_name: str,
) -> SquadMergeResult:
    """Run FE/BE/DB subagents in parallel and merge outputs."""
    _ = project_name
    tasks = [
        _run_specialty(
            specialty=spec,
            specialty_prompt=prompt,
            system_base=system_base,
            user_msg=user_msg,
        )
        for spec, prompt in _SPECIALTIES
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    intros: list[str] = []
    bodies: list[str] = []
    specialties_run: list[str] = []
    errors: list[str] = []

    for item in results:
        if isinstance(item, Exception):
            errors.append(f"{type(item).__name__}: {item}")
            continue
        spec, content = item
        specialties_run.append(spec)
        if not content:
            errors.append(f"{spec}: empty output")
            continue
        intros.append(f"### {spec}\n\n{content[:1200]}")
        bodies.append(content)

    if not bodies:
        return SquadMergeResult(
            intro_md="Squad produced no output.",
            raw_combined="",
            specialties_run=specialties_run,
            errors=errors or ["all specialties failed"],
        )

    intro_md = "# Engineer squad summary\n\n" + "\n\n".join(intros)
    raw_combined = "\n\n---\n\n".join(bodies)
    logger.info("engineer_squad_merged", extra={"specialties": specialties_run})
    return SquadMergeResult(
        intro_md=intro_md,
        raw_combined=raw_combined,
        specialties_run=specialties_run,
        errors=errors,
    )


__all__ = ["SquadMergeResult", "run_engineer_squad", "squad_enabled"]
