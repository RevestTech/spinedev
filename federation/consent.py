"""
federation.consent
==================

Per #10 — fractal Hub federation operates on a **consent-leaning** trust
model:

* **Peer-consent default.** Children must explicitly opt in to each
  consent class (telemetry, update_push, learning_cross_org,
  audit_export, …). Without a row in `spine_federation.consent_record`
  the answer is *no*.

* **Bounded mandatory upward flows.** A parent Hub's bundle may declare
  specific consent classes as *mandatory* upward (e.g. "all subsidiary
  Hubs MUST report security incidents up the tree"). The mandatory set
  is bounded — every entry needs a declared rationale + an audit-log
  trace at policy install. Mandatory flows override the peer-consent
  default, but only for the explicitly listed classes.

This module is the single source of truth for "may I send X from child
A to parent B?" — the downstream router, update cascade, and any MCP
tool that crosses the federation boundary funnels through
`ConsentEngine.is_allowed`.

Bundle policy shape (consumed by `ConsentEngine.from_bundle_policy`)::

    federation:
      consent:
        mandatory_upward:
          - class: security_incident
            rationale: "Org-wide regulatory reporting (SOC2 CC7.4)"
          - class: critical_compliance_evidence
            rationale: "Evidence chain integrity (SOC2 CC4.2)"

Anything not in `mandatory_upward` is governed by the per-child
consent_record table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Optional, Protocol
from uuid import UUID

logger = logging.getLogger("spine.federation.consent")

ConsentClass = Literal[
    "telemetry",
    "update_push",
    "learning_cross_org",
    "audit_export",
    "security_incident",
    "critical_compliance_evidence",
]
"""Recognised consent classes. Extending this Literal requires updating
both the V23 migration's `consent_record.consent_class` text column
(no DB schema change needed — it's text-not-enum) and any bundle
validators."""

ConsentDecision = Literal["accepted", "rejected", "pending"]
"""Decisions recorded against a peer Hub for one consent class."""


class MandatoryFlowDenied(RuntimeError):
    """Raised when a caller attempts to deny a consent class that the
    bundle has declared mandatory upward. Surfaces as an audit event in
    the calling code path."""


@dataclass(frozen=True)
class _MandatoryClass:
    """One declared mandatory-upward consent class."""

    consent_class: str
    rationale: str


class _PoolProto(Protocol):
    """Tiny duck-typed surface for asyncpg pool used by consent reads."""

    def acquire(self) -> Any:  # pragma: no cover - protocol stub
        ...


@dataclass
class ConsentEngine:
    """Policy + lookup engine for federation consent decisions.

    Construct with the asyncpg pool and a (possibly empty) list of
    mandatory-upward consent classes from the bundle. The engine is
    cheap to rebuild — bundle reloads create a fresh engine and atomic-
    swap it into the router/cascade.
    """

    pool: _PoolProto
    mandatory_upward: tuple[_MandatoryClass, ...] = ()

    # ---------------------------------------------------------------
    # Constructors
    # ---------------------------------------------------------------

    @classmethod
    def from_bundle_policy(
        cls,
        pool: _PoolProto,
        bundle_policy: Optional[dict[str, Any]],
    ) -> "ConsentEngine":
        """Build an engine from a parsed bundle's `federation` section.

        Tolerates missing sections: an empty bundle policy = no mandatory
        upward flows, peer-consent everywhere.
        """
        entries: list[_MandatoryClass] = []
        if bundle_policy:
            consent_block = bundle_policy.get("consent") or {}
            for raw in consent_block.get("mandatory_upward") or []:
                consent_class = raw.get("class")
                rationale = raw.get("rationale") or ""
                if not consent_class:
                    continue
                if not rationale:
                    # Per #10 every mandatory flow must declare rationale.
                    raise ValueError(
                        f"mandatory_upward[{consent_class}] missing rationale; "
                        "bundle policy declares it but provides no justification"
                    )
                entries.append(
                    _MandatoryClass(
                        consent_class=consent_class, rationale=rationale
                    )
                )
        return cls(pool=pool, mandatory_upward=tuple(entries))

    # ---------------------------------------------------------------
    # Decisions
    # ---------------------------------------------------------------

    def is_mandatory(self, consent_class: str) -> bool:
        """True if the bundle declared this consent class mandatory upward."""
        return any(m.consent_class == consent_class for m in self.mandatory_upward)

    def mandatory_rationale(self, consent_class: str) -> Optional[str]:
        """Return the operator-facing rationale for a mandatory flow."""
        for m in self.mandatory_upward:
            if m.consent_class == consent_class:
                return m.rationale
        return None

    async def is_allowed(
        self, peer_hub_id: UUID, consent_class: str
    ) -> bool:
        """Resolve: may we send ``consent_class`` to/from ``peer_hub_id``?

        Order:
            1. Mandatory upward flow → allowed regardless of peer choice.
            2. Active consent_record with matching child/parent + class.
            3. Default: deny.
        """
        if self.is_mandatory(consent_class):
            return True
        sql = (
            "SELECT 1 FROM spine_federation.consent_record "
            "WHERE consent_class = $1 "
            "  AND (child_hub_id = $2 OR parent_hub_id = $2) "
            "LIMIT 1"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchval(sql, consent_class, peer_hub_id)
        return row is not None

    async def grant(
        self,
        *,
        child_hub_id: UUID,
        parent_hub_id: UUID,
        consent_class: str,
        granted_by: str,
        scope: Optional[dict[str, Any]] = None,
    ) -> None:
        """INSERT a consent_record granting ``consent_class`` child→parent.

        Caller is responsible for emitting the matching audit event
        (subsystem='federation', action='consent_grant').
        """
        if not granted_by:
            raise ValueError("granted_by is required for consent grants")
        sql = (
            "INSERT INTO spine_federation.consent_record "
            "  (child_hub_id, parent_hub_id, consent_class, granted_by, scope_jsonb) "
            "VALUES ($1, $2, $3, $4, $5)"
        )
        import json as _json

        async with self.pool.acquire() as conn:
            await conn.execute(
                sql,
                child_hub_id,
                parent_hub_id,
                consent_class,
                granted_by,
                _json.dumps(scope or {}),
            )
        logger.info(
            "consent_granted",
            extra={
                "child_hub_id": str(child_hub_id),
                "parent_hub_id": str(parent_hub_id),
                "consent_class": consent_class,
            },
        )

    async def revoke(
        self,
        *,
        child_hub_id: UUID,
        parent_hub_id: UUID,
        consent_class: str,
    ) -> None:
        """DELETE consent_record rows for the triple.

        Mandatory upward flows cannot be revoked at the consent layer —
        the caller must remove the entry from the bundle policy (#10).
        Attempting to revoke a mandatory class raises
        ``MandatoryFlowDenied``.
        """
        if self.is_mandatory(consent_class):
            raise MandatoryFlowDenied(
                f"consent_class={consent_class!r} is mandatory_upward in this "
                f"Hub's bundle (rationale: {self.mandatory_rationale(consent_class)}). "
                "Edit the bundle to remove it before revoking."
            )
        sql = (
            "DELETE FROM spine_federation.consent_record "
            "WHERE child_hub_id = $1 AND parent_hub_id = $2 AND consent_class = $3"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(sql, child_hub_id, parent_hub_id, consent_class)
        logger.info(
            "consent_revoked",
            extra={
                "child_hub_id": str(child_hub_id),
                "parent_hub_id": str(parent_hub_id),
                "consent_class": consent_class,
            },
        )


__all__: list[str] = [
    "ConsentClass",
    "ConsentDecision",
    "ConsentEngine",
    "MandatoryFlowDenied",
]
