"""Atomic instinct schema for Smart Spine (V3 #27, B3 borrow).

Borrowed contract source: ECC ``continuous-learning-v2`` skill v2.1
(`affaan-m/ecc`, MIT). See ``docs/ECC_BORROWS.md`` B3.

Where this fits
---------------

Smart Spine (#27) already has a 3-tier loop for **lessons** — fully
formed "we learned X" statements that flow through
``learning.contribute_lesson`` into ``spine_learning.lesson``. Lessons
are the consolidated artifact.

**Instincts** are the layer beneath: atomic observations of a useful
behaviour, recorded with a confidence score (0.3 – 0.9). The same
instinct seen across multiple projects within a Hub graduates into a
lesson via :func:`check_promotion` + :func:`promote_to_lesson`.

This keeps Smart Spine's #27 contract intact:

  * Tier 1a (per-project): every recorded instinct is persistent in
    its project's JSONL.
  * Tier 1b (within-Hub): cross-project promotion happens only when
    threshold (default 2 distinct projects) is hit AND policy permits.
  * Tier 2 (cross-org): an instinct never crosses an org boundary
    directly — the only path out of a Hub is via lesson promotion,
    which routes through :mod:`learning.contribute` and
    :mod:`learning.anonymizer` exactly as before.

Storage
-------

JSONL per ``(project_id, run_id)`` under::

    <root>/<project_id>/<run_id>.jsonl

``<root>`` is :func:`default_instinct_root`, honouring
``SPINE_INSTINCT_ROOT`` (default ``~/.spine/instincts``). Mirrors the
B1 decision-ledger storage shape for operational consistency.

Fingerprinting
--------------

The hash key that identifies an instinct as "the same" across
observations is::

    fingerprint = sha256(normalised(pattern) + "\\x1f" + normalised(trigger))

Different rationales / confidences / actors are still the SAME
instinct; the fingerprint deliberately ignores them so a noisy first
observation can be corroborated by a quieter later one.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


CONFIDENCE_FLOOR = 0.3
"""Default confidence for a newly observed instinct."""

CONFIDENCE_CEILING = 0.9
"""Maximum confidence — corroboration cannot make Spine *certain*."""

PROMOTION_THRESHOLD_PROJECTS = 2
"""Distinct projects required before an instinct is eligible for
promotion to a lesson (within-Hub tier per #27 1b)."""

PROMOTION_MIN_CONFIDENCE = 0.5
"""Average confidence across observations must be at least this for
promotion eligibility."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalise(text: str) -> str:
    """Collapse whitespace and lowercase — for fingerprint stability."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def default_instinct_root() -> Path:
    """Resolve the on-disk root for instinct JSONL files."""
    env_value = os.environ.get("SPINE_INSTINCT_ROOT", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    return Path.home() / ".spine" / "instincts"


class Instinct(BaseModel):
    """An atomic learned behaviour.

    Confidence is bounded to [``CONFIDENCE_FLOOR``, ``CONFIDENCE_CEILING``].
    Bare construction defaults to ``CONFIDENCE_FLOOR`` — the model is
    intentionally cautious; observers raise confidence by corroboration.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern: str = Field(
        ..., min_length=1,
        description=(
            "The behaviour itself, in imperative form "
            "(e.g. 'run flyway migrate before pytest in KG-touching tests')."
        ),
    )
    trigger: str = Field(
        ..., min_length=1,
        description=(
            "When this applies (e.g. 'editing shared/runtime/kg_*.py')."
        ),
    )
    rationale: str = Field(
        ..., min_length=1,
        description="Why this is the right behaviour.",
    )
    confidence: float = Field(
        default=CONFIDENCE_FLOOR,
        ge=CONFIDENCE_FLOOR, le=CONFIDENCE_CEILING,
        description=(
            f"Confidence in [{CONFIDENCE_FLOOR}, {CONFIDENCE_CEILING}]. "
            "Defaults to floor."
        ),
    )

    @property
    def fingerprint(self) -> str:
        """SHA-256 of normalised pattern + trigger.

        Identifies "the same instinct" across observations. Different
        rationales, confidences, actors do NOT change the fingerprint.
        """
        joined = f"{_normalise(self.pattern)}\x1f{_normalise(self.trigger)}"
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class InstinctRecord(BaseModel):
    """One observation of an :class:`Instinct` in a specific project run.

    Records reference the audit chain via ``audit_hash`` so corroboration
    is cite-able (mirrors the decision-ledger B1 chain-of-trust posture).
    """

    model_config = ConfigDict(extra="forbid")

    record_id: UUID = Field(default_factory=uuid4)
    instinct: Instinct
    project_id: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    actor: str = Field(
        ..., min_length=1,
        description="Role / role daemon / human that observed this.",
    )
    observed_at: datetime = Field(default_factory=_utcnow)
    audit_hash: str | None = Field(
        default=None,
        description=(
            "Optional ``spine_audit.event.content_hash`` linking this "
            "observation to its originating event. None when recorded "
            "outside an audited path (rare)."
        ),
    )
    notes: str | None = Field(default=None)

    @property
    def fingerprint(self) -> str:
        return self.instinct.fingerprint


class PromotionDecision(BaseModel):
    """Verdict on whether an instinct fingerprint may graduate to a lesson.

    ``eligible_for_promotion`` is the final boolean. ``reasons`` carries
    failure codes when ``False`` (``threshold_not_met`` /
    ``confidence_below_floor``) so callers can decide whether to retry
    later (more corroboration) or downgrade.
    """

    model_config = ConfigDict(extra="forbid")

    fingerprint: str = Field(..., min_length=64, max_length=64)
    projects_seen: tuple[str, ...] = Field(default_factory=tuple)
    observations: int = Field(default=0, ge=0)
    avg_confidence: float = Field(
        default=0.0, ge=0.0, le=CONFIDENCE_CEILING,
    )
    threshold_projects: int = Field(default=PROMOTION_THRESHOLD_PROJECTS, ge=1)
    threshold_confidence: float = Field(
        default=PROMOTION_MIN_CONFIDENCE,
        ge=CONFIDENCE_FLOOR, le=CONFIDENCE_CEILING,
    )
    eligible_for_promotion: bool = Field(default=False)
    reasons: tuple[str, ...] = Field(default_factory=tuple)


class InstinctStore:
    """Append-only per-(project_id, run_id) JSONL store for instincts.

    Thread-safe append. Reader methods do not lock; concurrent reads
    while a single writer appends are safe on POSIX (line-atomic writes).
    """

    def __init__(
        self,
        *,
        project_id: str,
        run_id: str,
        root: Path | str | None = None,
    ) -> None:
        if not project_id:
            raise ValueError("project_id required")
        if not run_id:
            raise ValueError("run_id required")
        self.project_id = project_id
        self.run_id = run_id
        if root is None:
            self.root = default_instinct_root()
        else:
            self.root = Path(root).expanduser().resolve()
        self._path = self.root / project_id / f"{run_id}.jsonl"
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def record(self, observation: InstinctRecord) -> InstinctRecord:
        """Append ``observation`` to this run's JSONL.

        Raises:
            ValueError: if ``observation.project_id`` / ``run_id`` do not
                match the store.
        """
        if observation.project_id != self.project_id:
            raise ValueError(
                f"observation.project_id={observation.project_id!r} "
                f"does not match store project_id={self.project_id!r}"
            )
        if observation.run_id != self.run_id:
            raise ValueError(
                f"observation.run_id={observation.run_id!r} "
                f"does not match store run_id={self.run_id!r}"
            )
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = observation.model_dump_json() + "\n"
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line)
            return observation

    def iter_records(self) -> Iterator[InstinctRecord]:
        """Yield every observation in this run's file in append order."""
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                yield InstinctRecord.model_validate_json(line)


def iter_root(root: Path | None = None) -> Iterator[InstinctRecord]:
    """Walk every project / run JSONL under ``root`` and yield records.

    Used by :func:`check_promotion` to aggregate cross-run observations
    cheaply without holding a per-store handle.
    """
    root = root or default_instinct_root()
    if not root.exists():
        return
    for project_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for run_file in sorted(project_dir.glob("*.jsonl")):
            with run_file.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield InstinctRecord.model_validate_json(line)
                    except Exception:  # pragma: no cover - skip junk
                        logger.warning(
                            "iter_root: skipping malformed record in %s",
                            run_file,
                        )


def check_promotion(
    fingerprint: str,
    *,
    root: Path | None = None,
    threshold_projects: int = PROMOTION_THRESHOLD_PROJECTS,
    threshold_confidence: float = PROMOTION_MIN_CONFIDENCE,
) -> PromotionDecision:
    """Aggregate every observation of ``fingerprint`` and decide promotion.

    Eligible iff:

      * observations span at least ``threshold_projects`` distinct
        project_ids, AND
      * average confidence across all matching observations is
        ≥ ``threshold_confidence``.
    """
    matches = [
        r for r in iter_root(root)
        if r.instinct.fingerprint == fingerprint
    ]
    if not matches:
        return PromotionDecision(
            fingerprint=fingerprint,
            threshold_projects=threshold_projects,
            threshold_confidence=threshold_confidence,
            eligible_for_promotion=False,
            reasons=("no_observations",),
        )
    projects = tuple(sorted({m.project_id for m in matches}))
    avg = sum(m.instinct.confidence for m in matches) / len(matches)

    reasons: list[str] = []
    if len(projects) < threshold_projects:
        reasons.append("threshold_not_met")
    if avg < threshold_confidence:
        reasons.append("confidence_below_floor")
    eligible = not reasons
    return PromotionDecision(
        fingerprint=fingerprint,
        projects_seen=projects,
        observations=len(matches),
        avg_confidence=avg,
        threshold_projects=threshold_projects,
        threshold_confidence=threshold_confidence,
        eligible_for_promotion=eligible,
        reasons=tuple(reasons),
    )


def promote_to_lesson_payload(
    fingerprint: str,
    decision: PromotionDecision,
    *,
    root: Path | None = None,
) -> dict[str, str] | None:
    """Return a ``LessonPayload``-compatible dict for ``contribute_lesson``.

    Returns ``None`` when ``decision.eligible_for_promotion`` is False.
    The caller (typically a Conductor or the Hub scheduler) invokes
    :func:`learning.contribute.contribute_lesson` with this payload to
    route the lesson into ``spine_learning.lesson`` at the tier permitted
    by the existing ``learning.scope`` resolver.

    This keeps the existing Smart Spine consent + anonymizer wiring
    on the lesson path — instincts never bypass it.
    """
    if not decision.eligible_for_promotion:
        return None
    matches = [
        r for r in iter_root(root)
        if r.instinct.fingerprint == fingerprint
    ]
    if not matches:
        return None
    sample = matches[0].instinct
    lesson_text = (
        f"Promoted instinct (fingerprint={fingerprint[:12]}…):\n"
        f"- Pattern: {sample.pattern}\n"
        f"- Trigger: {sample.trigger}\n"
        f"- Rationale: {sample.rationale}\n"
        f"- Corroboration: {decision.observations} observation(s) "
        f"across {len(decision.projects_seen)} project(s) "
        f"(avg confidence {decision.avg_confidence:.2f})."
    )
    return {"lesson_text": lesson_text}


__all__ = [
    "CONFIDENCE_CEILING",
    "CONFIDENCE_FLOOR",
    "Instinct",
    "InstinctRecord",
    "InstinctStore",
    "PROMOTION_MIN_CONFIDENCE",
    "PROMOTION_THRESHOLD_PROJECTS",
    "PromotionDecision",
    "check_promotion",
    "default_instinct_root",
    "iter_root",
    "promote_to_lesson_payload",
]
