"""3-tier contribution gates — Wave 4 Squad D / V3 #27.

Translates a lesson + scope context into one or more writes against
``spine_learning.lesson`` (V29). Pure logic + a thin DB writer that the
tests stub. No secrets / no networking — Tier 2 *export* is in
:mod:`learning.anonymizer`; this module only *records* the in-DB lesson
with the correct ``scope``.

Public entry points
-------------------

    gate(ctx) -> ContributionDecision
        Apply the 3 tiers and return the resolved scope + reason.

    contribute_lesson(payload, ctx, *, writer=None) -> ContributionOutcome
        Run :func:`gate`, then call ``writer`` (or the default psql writer)
        for each tier permitted, then return the rows written + ids.

Contribution policy:

    Tier 1a (project)   — every audit event auto-promotes here. ALWAYS on.
    Tier 1b (within_hub)— writes a second lesson row scoped within_hub IF
                          policy.within_hub_enabled. Default ON.
    Tier 2  (cross_org) — writes a third lesson row scoped cross_org ONLY
                          if explicit per-category consent is granted.
                          Default OFF. Auditor row is mandatory because
                          this crosses an org boundary.
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .scope import (
    LearningScope,
    PolicyLoader,
    ResolvedScope,
    ScopeContext,
    ScopePolicy,
    resolve_scope,
)

logger = logging.getLogger(__name__)

DEFAULT_DB_URL = "postgresql://spine:spine@localhost:33000/spine"


@dataclass(frozen=True)
class LessonPayload:
    """Minimal lesson shape this gate emits. Mirrors V29 columns."""
    lesson_text: str
    source_audit_record_id: Optional[str] = None
    embedding: Optional[list[float]] = None

    def text_hash(self) -> str:
        return hashlib.sha256(self.lesson_text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ContributionDecision:
    """Result of :func:`gate` — which tiers are permitted for one event."""
    resolved: ResolvedScope
    tiers_to_write: tuple[LearningScope, ...]
    skipped_reasons: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ContributionOutcome:
    """Result of :func:`contribute_lesson` — rows written + ids per tier."""
    decision: ContributionDecision
    written: dict[str, str]  # tier_value -> lesson_id (uuid str)
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def total_written(self) -> int:
        return len(self.written)


Writer = Callable[[LessonPayload, LearningScope, dict[str, Any]], str]
"""(payload, tier, extras) -> lesson_id; tests inject a stub."""


# ─── Gate ────────────────────────────────────────────────────────────


def gate(
    ctx: ScopeContext,
    *,
    loader: Optional[PolicyLoader] = None,
    explicit_policy: Optional[ScopePolicy] = None,
) -> ContributionDecision:
    """Decide which tiers a single audit event may promote into.

    The rule (per V3 #27):
      Tier 1a is unconditional.
      Tier 1b stacks on top of Tier 1a if within_hub_enabled.
      Tier 2 stacks on top of 1a+1b if per-category consent granted.

    We always *include* lower tiers when a higher tier is requested —
    the project copy is the canonical local source of truth and never
    skipped.
    """
    resolved = resolve_scope(ctx, loader=loader, explicit_policy=explicit_policy)
    policy = resolved.policy_snapshot
    tiers: list[LearningScope] = [LearningScope.PROJECT]  # Tier 1a always
    skipped: dict[str, str] = {}

    # Tier 1b
    if ctx.requested_scope in (LearningScope.WITHIN_HUB, LearningScope.CROSS_ORG):
        if policy.within_hub_enabled:
            tiers.append(LearningScope.WITHIN_HUB)
        else:
            skipped[LearningScope.WITHIN_HUB.value] = "within_hub_disabled_by_policy"

    # Tier 2 — strict; only on explicit per-category consent.
    if ctx.requested_scope == LearningScope.CROSS_ORG:
        if policy.cross_org_for(ctx.data_category):
            tiers.append(LearningScope.CROSS_ORG)
        else:
            skipped[LearningScope.CROSS_ORG.value] = (
                "cross_org_consent_missing"
                if ctx.data_category is None
                else f"cross_org_consent_missing_for:{ctx.data_category}"
            )

    return ContributionDecision(
        resolved=resolved,
        tiers_to_write=tuple(tiers),
        skipped_reasons=skipped,
    )


# ─── Writer ──────────────────────────────────────────────────────────


def _q(v: object) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def _psql(sql: str, db_url: str) -> str:
    r = subprocess.run(
        ["psql", db_url, "-At", "-F", "\x1f", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    return r.stdout


def _default_writer(
    payload: LessonPayload,
    tier: LearningScope,
    extras: dict[str, Any],
) -> str:
    """Insert one row into ``spine_learning.lesson`` and return its id."""
    db_url = (
        extras.get("db_url")
        or os.environ.get("SPINE_DB_URL")
        or os.environ.get("DATABASE_URL")
        or DEFAULT_DB_URL
    )
    source_id = payload.source_audit_record_id
    source_sql = "NULL" if source_id is None else f"{_q(source_id)}::uuid"
    sql = (
        "INSERT INTO spine_learning.lesson (scope, source_audit_record_id, "
        "lesson_text) VALUES ("
        f"{_q(tier.value)}, {source_sql}, {_q(payload.lesson_text)}) "
        "RETURNING id;"
    )
    out = _psql(sql, db_url).strip()
    return out.splitlines()[0] if out else ""


def contribute_lesson(
    payload: LessonPayload,
    ctx: ScopeContext,
    *,
    loader: Optional[PolicyLoader] = None,
    explicit_policy: Optional[ScopePolicy] = None,
    writer: Optional[Writer] = None,
    writer_extras: Optional[dict[str, Any]] = None,
) -> ContributionOutcome:
    """Run the gate, then write one row per permitted tier.

    Failures are isolated per tier — a Tier 1b write failure must not
    block the canonical Tier 1a write (and vice-versa). Caller inspects
    ``outcome.failed`` for partial-write conditions.
    """
    decision = gate(ctx, loader=loader, explicit_policy=explicit_policy)
    written: dict[str, str] = {}
    failed: dict[str, str] = {}
    extras = dict(writer_extras or {})
    w = writer or _default_writer

    for tier in decision.tiers_to_write:
        try:
            row_id = w(payload, tier, extras)
            if row_id:
                written[tier.value] = row_id
            else:
                failed[tier.value] = "no_row_id_returned"
        except Exception as exc:  # noqa: BLE001 — isolate per tier
            logger.warning(
                "contribute_lesson tier=%s failed: %s",
                tier.value, exc,
            )
            failed[tier.value] = type(exc).__name__

    return ContributionOutcome(decision=decision, written=written, failed=failed)


__all__ = [
    "ContributionDecision",
    "ContributionOutcome",
    "LessonPayload",
    "Writer",
    "contribute_lesson",
    "gate",
]
