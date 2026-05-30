"""Append-only decision ledger for Spine (V3 #12a).

> Annotation ratified 2026-05-29 in ``docs/V3_DESIGN_DECISIONS.md``.
> Borrowed contract source: ECC ``recursive-decision-ledger`` skill
> (``affaan-m/ecc``, MIT). See ``docs/ECC_BORROWS.md`` B1.

This module turns recursive / ensemble / rollout reasoning into auditable
evidence. Cite-or-Refuse (#12) governs whether a role *may act*; the
decision ledger governs whether the result of those acts *may be promoted
to live*.

Storage
-------

Each ``LedgerEntry`` is one JSON record appended to a JSONL file at::

    <root>/<project_id>/<run_id>.jsonl

``<root>`` defaults to the value of the ``SPINE_DECISION_LEDGER_ROOT``
environment variable, falling back to ``~/.spine/decision_ledger``. Spine
projects own their JSONL — there is no cross-project ledger file. This
matches the per-run workspace contract (#34) and keeps the ledger sweepable.

Hash chain
----------

Each ``LedgerEntry`` records ``prev_hash`` (the previous entry's
``content_hash``, or ``None`` for the first entry in a run) and its own
``content_hash``. The chain is content-addressed and forms a Merkle-style
proof: any tamper to a prior entry breaks every following entry's hash.

In addition, the canonical JSON form of every appended entry is shadowed
into the existing ``spine_audit.audit_event`` table via :class:`AuditRecord`
with ``action='decision_ledger.append'`` so the durable audit chain
references the ledger entry by hash. The ledger file is the source of
truth for ledger semantics; the audit table is the source of truth for
"this entry was observed at time T by actor X."

Promotion gate
--------------

The class :class:`PromotionGate` packages the answer to the question
"may this candidate be promoted to live?" into an explicit value:

* ``allowed`` — both freshness and replay gates passed, bundle policy
  permits live promotion at this work-item tier (#19).
* ``denied`` — at least one gate failed; ``reasons`` lists the failures.
  Default state for production deploys, capital-class migrations, and
  destructive ops.

Recursive confidence alone is **never** sufficient for ``allowed``. The
caller (typically the Conductor or Auditor charter) provides both the
freshness check and the replay check; the ledger merely records them.

Module shape
------------

* :class:`DecisionMark` — Literal alias listing the five marks.
* :class:`Candidate` — one ranked option inside a rollout.
* :class:`CoherenceMark` — comparison against the prior accepted winner.
* :class:`PromotionGate` — explicit gate verdict + reason list.
* :class:`LedgerEntry` — one JSONL row.
* :class:`DecisionLedger` — append / tail / coherence-check / gate API.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


DecisionMark = Literal["accept", "watch", "reject", "decay", "replay"]
"""Five recognised marks per the ECC recursive-decision-ledger contract."""


PromotionVerdict = Literal["allowed", "denied"]
"""Outcome of the promotion gate. Defaults to ``denied`` per V3 #12a."""


WorkItemTier = Literal["paper", "preview", "internal", "production", "destructive"]
"""Tiering used by the gate to decide which checks are mandatory.

* ``paper``       — pure simulation / dry-run; gate is informational.
* ``preview``     — staged on an isolated environment, no customer data.
* ``internal``    — internal infra change, no external blast radius.
* ``production``  — customer-facing deploy. Freshness + replay required.
* ``destructive`` — irreversible op (e.g. delete data, drop tables).
                    Freshness + replay + explicit operator confirmation
                    required; gate denial is sticky.
"""


def _utcnow() -> datetime:
    """Return a timezone-aware UTC ``datetime``."""
    return datetime.now(timezone.utc)


def _canon_json(payload: dict[str, Any]) -> str:
    """Deterministic JSON encoding used for hashing."""

    def _default(value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        raise TypeError(f"unserialisable for ledger hash: {type(value)!r}")

    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=_default,
    )


def _sha256(text: str) -> str:
    """Hex SHA-256 of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def default_ledger_root() -> Path:
    """Resolve the on-disk root for ledger JSONL files.

    Honours ``SPINE_DECISION_LEDGER_ROOT`` if set, otherwise
    ``~/.spine/decision_ledger``.
    """
    env_value = os.environ.get("SPINE_DECISION_LEDGER_ROOT", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    return Path.home() / ".spine" / "decision_ledger"


class Candidate(BaseModel):
    """One ranked option produced by a rollout."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str = Field(
        ..., min_length=1,
        description="Stable identifier — opaque to the ledger.",
    )
    mark: DecisionMark = Field(
        ..., description="Decision mark assigned by the role.",
    )
    score: float | None = Field(
        default=None,
        description="Optional model-side score. Ledger does not interpret.",
    )
    rationale: str | None = Field(
        default=None,
        description="Short human / role rationale for the mark.",
    )


class CoherenceMark(BaseModel):
    """Comparison of this rollout's winner against prior accepted state.

    Captures the five questions every rollout should answer before
    promotion. Booleans are intentionally explicit — ``None`` is reserved
    for "not applicable to this entry" rather than "unknown".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ensemble_matches_prior_winner: bool | None = Field(
        default=None,
        description="Ensemble vote agreed with the previously accepted winner.",
    )
    recursive_matches_prior_winner: bool | None = Field(
        default=None,
        description="Self-consistency / recursive vote agreed with prior winner.",
    )
    latest_rollout_match: bool | None = Field(
        default=None,
        description="This rollout's top candidate matches the previous rollout.",
    )
    drift_detected: bool = Field(
        default=False,
        description="Drift between fresh evidence and prior ledger context.",
    )
    notes: str | None = Field(
        default=None,
        description="Free-text supplementary notes.",
    )


class PromotionGate(BaseModel):
    """Explicit verdict on whether the rollout result may be promoted.

    V3 #12a: ``denied`` is the default state. Recursive confidence is not
    a reason to set ``allowed``. The caller is responsible for setting
    ``freshness_passed`` and ``replay_passed`` truthfully.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: PromotionVerdict = Field(
        default="denied",
        description="Final gate outcome. Default-deny.",
    )
    tier: WorkItemTier = Field(
        ...,
        description="Work-item tier; controls which checks are mandatory.",
    )
    freshness_passed: bool = Field(
        default=False,
        description="Fresh evidence ingested within bundle-policy window.",
    )
    replay_passed: bool = Field(
        default=False,
        description="Prior winner reproducible on current state.",
    )
    operator_confirmed: bool = Field(
        default=False,
        description="Explicit human operator confirmation. Required for 'destructive'.",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description=(
            "Reason codes for the verdict. Empty when 'allowed'. "
            "Example codes: 'freshness_stale', 'replay_failed', "
            "'operator_not_confirmed', 'tier_denies_live'."
        ),
    )

    @classmethod
    def evaluate(
        cls,
        *,
        tier: WorkItemTier,
        freshness_passed: bool,
        replay_passed: bool,
        operator_confirmed: bool = False,
    ) -> "PromotionGate":
        """Compute the gate verdict from the input checks.

        Logic (the ledger never approves on recursive confidence alone):

        * ``paper`` / ``preview`` — always ``allowed``; gate is informational.
        * ``internal`` — ``allowed`` when freshness passes; replay optional.
        * ``production`` — requires freshness AND replay.
        * ``destructive`` — requires freshness AND replay AND operator.
        """
        reasons: list[str] = []
        if tier in ("paper", "preview"):
            return cls(
                verdict="allowed", tier=tier,
                freshness_passed=freshness_passed,
                replay_passed=replay_passed,
                operator_confirmed=operator_confirmed,
                reasons=[],
            )

        if tier == "internal":
            if not freshness_passed:
                reasons.append("freshness_stale")
        elif tier == "production":
            if not freshness_passed:
                reasons.append("freshness_stale")
            if not replay_passed:
                reasons.append("replay_failed")
        elif tier == "destructive":
            if not freshness_passed:
                reasons.append("freshness_stale")
            if not replay_passed:
                reasons.append("replay_failed")
            if not operator_confirmed:
                reasons.append("operator_not_confirmed")

        verdict: PromotionVerdict = "allowed" if not reasons else "denied"
        return cls(
            verdict=verdict, tier=tier,
            freshness_passed=freshness_passed,
            replay_passed=replay_passed,
            operator_confirmed=operator_confirmed,
            reasons=reasons,
        )


class LedgerEntry(BaseModel):
    """One JSONL row in the decision ledger.

    Hash chain
    ----------

    ``prev_hash`` carries the previous entry's ``content_hash`` for this
    run, or ``None`` for the first entry. ``content_hash`` is the SHA-256
    of the canonical JSON encoding of every field except ``content_hash``
    itself (matches the audit_record exclusion pattern).
    """

    model_config = ConfigDict(extra="forbid")

    entry_id: UUID = Field(default_factory=uuid4)
    project_id: str = Field(
        ..., min_length=1,
        description="Spine project this entry belongs to.",
    )
    run_id: str = Field(
        ..., min_length=1,
        description="Identifier of the rollout / dispatch this entry describes.",
    )
    actor: str = Field(
        ..., min_length=1,
        description="Role / subsystem that generated this entry.",
    )
    rollout_index: int = Field(
        ..., ge=0,
        description="Zero-based index of this rollout within the run.",
    )
    ts: datetime = Field(default_factory=_utcnow)

    fresh_evidence: list[str] = Field(
        default_factory=list,
        description=(
            "Stable references (KG node ids, file:line, audit hashes) for "
            "the evidence ingested at this rollout."
        ),
    )
    search_space_size: int | None = Field(
        default=None,
        description="Cardinality of the search space (if bounded).",
    )
    trial_count: int = Field(
        default=1, ge=1,
        description="Number of trials in this rollout.",
    )
    effective_trial_count: int | None = Field(
        default=None,
        description="Trials retained after dedup / filtering. Defaults to trial_count.",
    )

    candidates: list[Candidate] = Field(
        ...,
        description="Top candidates with explicit marks. Empty list rejected.",
    )
    prior_accepted_winner: str | None = Field(
        default=None,
        description="``candidate_id`` of the prior accepted winner, if any.",
    )
    prior_watchlist: list[str] = Field(
        default_factory=list,
        description="``candidate_id``s on the watchlist from the prior entry.",
    )
    coherence: CoherenceMark = Field(
        default_factory=CoherenceMark,
        description="Comparison against prior ledger state.",
    )
    promotion_gate: PromotionGate = Field(
        ...,
        description="Explicit gate verdict. Default-deny per V3 #12a.",
    )

    prev_hash: str | None = Field(
        default=None,
        description="content_hash of the prior entry in this run. None for first.",
    )
    content_hash: str | None = Field(
        default=None,
        description="SHA-256 of the canonical JSON of this entry (computed on write).",
    )

    def compute_content_hash(self) -> str:
        """Return the SHA-256 of the canonical encoding of this entry.

        Excludes the ``content_hash`` field itself so the hash is stable
        when set into the model afterwards.
        """
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        return _sha256(_canon_json(payload))


class DecisionLedger:
    """Append-only JSONL ledger for one ``(project_id, run_id)`` pair.

    Thread-safe append. Not multi-process safe — use a single writer per
    run. Reader methods (:meth:`tail`, :meth:`iter_entries`) are safe to
    run concurrently with a writer because writes are line-atomic on
    POSIX filesystems for sub-PAGE writes.

    Usage::

        ledger = DecisionLedger(project_id="abc", run_id="run-001")
        entry = LedgerEntry(
            project_id="abc", run_id="run-001",
            actor="conductor", rollout_index=0,
            candidates=[Candidate(candidate_id="plan-A", mark="accept")],
            promotion_gate=PromotionGate.evaluate(
                tier="production",
                freshness_passed=True,
                replay_passed=True,
            ),
        )
        appended = ledger.append(entry)
        # appended.content_hash and prev_hash are populated.
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
            self.root = default_ledger_root()
        else:
            self.root = Path(root).expanduser().resolve()
        self._path = self.root / project_id / f"{run_id}.jsonl"
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        """Absolute path to the JSONL file for this run."""
        return self._path

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        """Append ``entry`` to the ledger.

        Returns a copy of ``entry`` with ``prev_hash`` and ``content_hash``
        populated from the chain. Constructs an :class:`AuditRecord`
        shadow event so the existing audit chain references the ledger
        entry by hash. Persistence of the audit record itself is the
        caller's responsibility (the existing pattern from
        ``shared/mcp/cite_or_refuse.py``).

        Raises:
            ValueError: if ``entry.project_id`` / ``entry.run_id`` do not
                match this ledger, or ``entry.candidates`` is empty.
        """
        if entry.project_id != self.project_id:
            raise ValueError(
                f"entry.project_id={entry.project_id!r} does not match "
                f"ledger project_id={self.project_id!r}"
            )
        if entry.run_id != self.run_id:
            raise ValueError(
                f"entry.run_id={entry.run_id!r} does not match "
                f"ledger run_id={self.run_id!r}"
            )
        if not entry.candidates:
            raise ValueError("entry.candidates must be non-empty")

        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            prev_hash = self._last_hash_locked()
            chained = entry.model_copy(update={"prev_hash": prev_hash})
            content_hash = chained.compute_content_hash()
            final = chained.model_copy(update={"content_hash": content_hash})
            line = _canon_json(final.model_dump(mode="json")) + "\n"
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line)
            self._shadow_audit(final)
            return final

    def tail(self, n: int = 1) -> list[LedgerEntry]:
        """Return up to the last ``n`` entries (oldest first)."""
        if n <= 0:
            return []
        entries = list(self.iter_entries())
        return entries[-n:]

    def iter_entries(self) -> Iterator[LedgerEntry]:
        """Yield every entry in append order."""
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                yield LedgerEntry.model_validate_json(line)

    def verify_chain(self) -> tuple[bool, str | None]:
        """Walk the ledger and verify the hash chain.

        Returns ``(ok, reason)``. ``reason`` is ``None`` on success or a
        short description of the first failure encountered.
        """
        prev_hash: str | None = None
        for idx, entry in enumerate(self.iter_entries()):
            if entry.prev_hash != prev_hash:
                return False, f"entry {idx}: prev_hash mismatch"
            expected = entry.compute_content_hash()
            if entry.content_hash != expected:
                return False, f"entry {idx}: content_hash mismatch"
            prev_hash = entry.content_hash
        return True, None

    # ─── internal helpers ───

    def _last_hash_locked(self) -> str | None:
        """Return the ``content_hash`` of the last appended entry, or None."""
        if not self._path.exists():
            return None
        last: str | None = None
        with self._path.open("rb") as handle:
            try:
                handle.seek(-4096, os.SEEK_END)
            except OSError:
                handle.seek(0)
            for line in handle.read().splitlines()[::-1]:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                last = obj.get("content_hash")
                if last:
                    break
        return last

    def _shadow_audit(self, entry: LedgerEntry) -> None:
        """Build an ``AuditRecord`` shadow event for ``entry``.

        Constructs but does not persist — persistence is the caller's
        responsibility (existing pattern from cite_or_refuse). Failures
        are swallowed and logged; the ledger write itself has already
        succeeded.
        """
        try:
            from shared.audit.audit_record import AuditRecord
        except Exception:
            logger.warning(
                "decision_ledger: audit_record import failed; skipping shadow audit",
            )
            return
        try:
            AuditRecord(
                role=entry.actor,
                subsystem="shared",
                action="decision_ledger.append",
                actor=entry.actor,
                subject_type="decision_ledger_entry",
                subject_id=str(entry.entry_id),
                rationale=(
                    f"ledger append run={entry.run_id} "
                    f"rollout={entry.rollout_index} "
                    f"verdict={entry.promotion_gate.verdict}"
                ),
                metadata={
                    "project_id": entry.project_id,
                    "run_id": entry.run_id,
                    "rollout_index": entry.rollout_index,
                    "content_hash": entry.content_hash,
                    "prev_hash": entry.prev_hash,
                    "promotion_verdict": entry.promotion_gate.verdict,
                    "promotion_tier": entry.promotion_gate.tier,
                    "promotion_reasons": list(entry.promotion_gate.reasons),
                },
            )
        except Exception:
            logger.exception("decision_ledger: shadow audit record build failed")


__all__ = [
    "Candidate",
    "CoherenceMark",
    "DecisionLedger",
    "DecisionMark",
    "LedgerEntry",
    "PromotionGate",
    "PromotionVerdict",
    "WorkItemTier",
    "default_ledger_root",
]
