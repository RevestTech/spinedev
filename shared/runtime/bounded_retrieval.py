"""Bounded iterative retrieval for role dispatch (V3 B4).

Borrowed contract source: ECC ``iterative-retrieval`` skill
(`affaan-m/ecc`, MIT). See ``docs/ECC_BORROWS.md`` B4.

Spine's existing dispatchers (build, plan, verify) ship full project
metadata to every role on every dispatch. That's the "send everything"
failure mode — it bloats context, breaks the role's observation budget
(per V3 #30a), and is the proximate cause of the SPA-hang class of bugs
seen on dogfood projects.

This module implements the 4-phase bounded retrieval protocol:

  DISPATCH  → minimal seed (project id, work item, prior winner, top-N
              engineering goals)
  EVALUATE  → role replies with either a final result or a list of
              ``Need`` items declaring what extra context it requires
  REFINE    → resolver fetches the needs (KG / file / audit / metadata)
  LOOP      → re-dispatch with augmented seed; bounded to ``max_cycles``
              (default 3), then proceed with best-available

Channel
-------

Roles signal needs through the V3 #30a observation envelope. A
``ToolResponse`` with ``status='warning'`` and ``next_actions`` items
prefixed with ``"need:"`` is interpreted as a NeedsRequest. The
prefix lets the same envelope serve both retrieval and ordinary
next-action lists (e.g. ``"approve_decision 42"``).

Failure modes
-------------

* If the role exhausts ``max_cycles`` still requesting needs, the
  dispatcher proceeds with whatever was resolved and records a
  ``cycle_exhausted`` warning. The role's last partial result is the
  output; never silently retry forever.
* If a resolver raises, the corresponding ``ResolvedNeed`` records the
  failure (``success=False``, ``error=str(exc)``) and the loop continues.
  Roles can detect partial resolution and decide whether to refuse
  (per #12 Cite-or-Refuse) or carry on.

This module is provider-agnostic — it does not call an LLM. The
``role_callable`` is supplied by the caller and is the contract surface
where Claude Code / Cursor / a charter daemon plug in.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import Artifact, ArtifactType, ToolResponse

logger = logging.getLogger(__name__)


NeedType = Literal[
    "kg_node",
    "file_path",
    "audit_hash",
    "project_metadata",
    "ledger_entry",
]
"""Categories of context a role may request via the needs channel.

Mirrors :class:`shared.mcp.schemas.envelopes.ArtifactType` so resolved
needs round-trip into V3 #30a ``Artifact`` rows without translation.
"""


NEED_PREFIX = "need:"
"""Prefix that marks a ``next_actions`` entry as a needs request."""


CYCLE_EXHAUSTED_REASON = "cycle_exhausted"
"""Recorded in ``RetrievalOutcome.warnings`` when the role keeps asking
for needs past ``max_cycles``."""


class Need(BaseModel):
    """One context request from a role.

    Encoded over the wire as ``next_actions`` entry
    ``"need:<type>:<ref>"`` (or ``"need:<type>:<ref>|<reason>"``).
    Reason is optional but encouraged so the dispatcher can log
    *why* the role asked.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: NeedType = Field(
        ..., description="What category of context is required.",
    )
    ref: str = Field(
        ..., min_length=1,
        description=(
            "Lookup key. Shape depends on type — kg_node id / "
            "file:line / audit content_hash / metadata.key.path / "
            "ledger entry uuid."
        ),
    )
    reason: str | None = Field(
        default=None,
        description="Role-side explanation. Optional.",
    )

    def to_next_action(self) -> str:
        """Encode this need as a ``next_actions`` entry."""
        base = f"{NEED_PREFIX}{self.type}:{self.ref}"
        if self.reason:
            return f"{base}|{self.reason}"
        return base


class ResolvedNeed(BaseModel):
    """A resolved (or failed-to-resolve) need."""

    model_config = ConfigDict(extra="forbid")

    need: Need
    content: str | None = Field(
        default=None,
        description="Resolved content (markdown / source / json). None on failure.",
    )
    artifact: Artifact | None = Field(
        default=None,
        description="V3 #30a artifact reference produced by the resolver.",
    )
    success: bool = Field(..., description="True iff content was fetched.")
    error: str | None = Field(default=None)


NeedsResolver = Callable[[Sequence[Need]], Sequence[ResolvedNeed]]
"""Resolves a list of ``Need`` into a list of ``ResolvedNeed``.

Implementations should resolve every input (return a ``ResolvedNeed``
with ``success=False`` for ones that failed) rather than raising — the
loop catches exceptions but a partial resolution is more useful than a
total failure.
"""


RoleCallable = Callable[["Seed"], ToolResponse]
"""Invokes a role with the current ``Seed`` and returns its envelope."""


class Seed(BaseModel):
    """Minimal initial dispatch payload, augmented across cycles."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1)
    work_item: str = Field(..., min_length=1, description="What to work on.")
    role: str = Field(..., min_length=1)
    prior_winner: str | None = Field(
        default=None,
        description=(
            "Identifier of the prior accepted candidate (if any) so the "
            "role can ground continuations."
        ),
    )
    base_context: list[str] = Field(
        default_factory=list,
        description=(
            "Seed context items the dispatcher decided are always cheap "
            "enough to ship (top-N engineering goals, scope summary)."
        ),
    )
    resolved: list[ResolvedNeed] = Field(
        default_factory=list,
        description=(
            "Accumulated context from prior REFINE phases. Grows across "
            "cycles. Empty on cycle 0."
        ),
    )

    def augment(self, new_resolved: Sequence[ResolvedNeed]) -> "Seed":
        """Return a new ``Seed`` with ``new_resolved`` appended."""
        return self.model_copy(
            update={"resolved": [*self.resolved, *new_resolved]},
        )


@dataclass(frozen=True)
class RetrievalOutcome:
    """Final result of one bounded-retrieval run."""

    final_response: ToolResponse
    cycles_used: int
    resolved_needs: list[ResolvedNeed]
    warnings: list[str] = field(default_factory=list)


# ─── parsing ───────────────────────────────────────────────────────────


def parse_needs(response: ToolResponse) -> list[Need]:
    """Extract ``Need`` items from a role response's ``next_actions``.

    Lines NOT prefixed with ``need:`` are ignored (they remain plain
    next-actions). Malformed need lines are skipped with a debug log
    and surfaced as warnings on the outcome.
    """
    needs: list[Need] = []
    for action in response.next_actions:
        if not action.startswith(NEED_PREFIX):
            continue
        body = action[len(NEED_PREFIX):]
        # Split optional reason after `|`.
        if "|" in body:
            ref_part, _, reason_part = body.partition("|")
            reason = reason_part.strip() or None
        else:
            ref_part = body
            reason = None
        if ":" not in ref_part:
            logger.debug("malformed need (missing type:ref): %r", action)
            continue
        type_, _, ref = ref_part.partition(":")
        type_clean = type_.strip()
        ref_clean = ref.strip()
        if type_clean not in {
            "kg_node", "file_path", "audit_hash",
            "project_metadata", "ledger_entry",
        }:
            logger.debug("unknown need type %r in %r", type_clean, action)
            continue
        if not ref_clean:
            continue
        needs.append(
            Need(type=type_clean, ref=ref_clean, reason=reason)  # type: ignore[arg-type]
        )
    return needs


# ─── runner ────────────────────────────────────────────────────────────


def run_bounded_retrieval(
    *,
    seed: Seed,
    role: RoleCallable,
    resolver: NeedsResolver,
    max_cycles: int = 3,
) -> RetrievalOutcome:
    """Execute the bounded retrieval loop.

    Stops on the first non-needs response or after ``max_cycles``
    iterations, whichever comes first. ``max_cycles`` of 0 is treated
    as 1 (the role always gets at least one shot).
    """
    if max_cycles < 1:
        max_cycles = 1

    current = seed
    cycles_used = 0
    last_response: ToolResponse | None = None
    warnings: list[str] = []
    all_resolved: list[ResolvedNeed] = list(seed.resolved)

    for cycle_idx in range(max_cycles):
        cycles_used = cycle_idx + 1
        last_response = role(current)
        needs = parse_needs(last_response)
        if not needs:
            # Role produced its final answer (or a plain warning/error/refusal).
            return RetrievalOutcome(
                final_response=last_response,
                cycles_used=cycles_used,
                resolved_needs=all_resolved,
                warnings=warnings,
            )
        # REFINE phase.
        try:
            new_resolved = list(resolver(needs))
        except Exception as exc:
            logger.exception("bounded_retrieval: resolver raised")
            new_resolved = [
                ResolvedNeed(
                    need=n,
                    content=None,
                    success=False,
                    error=f"resolver_exception: {exc}",
                )
                for n in needs
            ]
        all_resolved.extend(new_resolved)
        current = current.augment(new_resolved)

    # Cycle exhausted with the role still asking for needs.
    warnings.append(CYCLE_EXHAUSTED_REASON)
    assert last_response is not None, "max_cycles >= 1 guarantees at least one role call"
    return RetrievalOutcome(
        final_response=last_response,
        cycles_used=cycles_used,
        resolved_needs=all_resolved,
        warnings=warnings,
    )


__all__ = [
    "CYCLE_EXHAUSTED_REASON",
    "NEED_PREFIX",
    "Need",
    "NeedType",
    "NeedsResolver",
    "ResolvedNeed",
    "RetrievalOutcome",
    "RoleCallable",
    "Seed",
    "parse_needs",
    "run_bounded_retrieval",
]
