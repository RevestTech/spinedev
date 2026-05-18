"""Tier 3 vendor self-improvement loop — Wave 4 Squad D / V3 #27 + #21.

Tier 3 (per #27): *vendor's own Spine deployment improves the product;
eats own dogfood; drift audits, calibration, eval-on-every-release; always
on (vendor choice).* Per #21, the vendor's build team is solo-human +
AI, so the vendor's own Spine IS the proving ground for every feature
before it ships to customers.

This module is the seam where the vendor's deployment hooks INTO ITS
OWN audit chain (no cross-org consent required because the data is
the vendor's). Customer deployments must NOT call these functions; the
:func:`is_vendor_deployment` gate enforces that at runtime.

Detection: a deployment is the vendor's iff *any* of these holds —
  * ``SPINE_DEPLOYMENT_KIND=vendor`` env var, OR
  * the bundle policy snapshot has ``vendor_self_improvement: true``,
    OR
  * an explicit ``force_vendor=True`` arg (testing / drift-audit).

How Tier 3 hooks the vendor audit chain
---------------------------------------
1. Wave 1's ``shared.memory.writer_hooks.dispatch`` already fires on
   the 7 trigger points → produces ``spine_memory.lesson`` rows.
2. On a vendor deployment, the vendor sidecar subscribes to those
   audit rows and calls :func:`vendor_self_improvement_record` for
   each one. That function:
      a. Re-emits the lesson into ``spine_learning.lesson`` at
         ``scope='cross_org'`` UNCONDITIONALLY (vendor's own data).
      b. Stamps an audit row of its own (``vendor_self_improvement``)
         linking back to the source audit record.
      c. Optionally pushes the lesson + drift signal upstream into
         the vendor's *Master role* aggregation queue (which becomes
         improved role charters / bundles published via the federation
         update tree per #16).
3. Customer deployments never reach step (a)/(c) — :func:`is_vendor_
   deployment` short-circuits.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .contribute import (
    ContributionOutcome,
    LessonPayload,
    contribute_lesson,
)
from .scope import LearningScope, ScopeContext, ScopePolicy

logger = logging.getLogger(__name__)


VENDOR_ENV_KEY = "SPINE_DEPLOYMENT_KIND"
VENDOR_ENV_VALUE = "vendor"


@dataclass(frozen=True)
class VendorSelfImprovementEvent:
    """One audit event the vendor's deployment is folding into Tier 3."""
    source_audit_record_id: str
    lesson_text: str
    event_key: str  # e.g. 'verify.failed', 'phase.advance.success'
    role: str = "spine"
    hub_id: Optional[str] = None
    project_id: Optional[str] = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VendorSelfImprovementResult:
    """Outcome of a single Tier 3 record call."""
    accepted: bool
    outcome: Optional[ContributionOutcome]
    reason: str
    recorded_at: datetime
    upstream_dispatched: bool = False


# A push hook lets Wave 5 wire the actual federation publish step (#16)
# without this module taking a dependency on ``federation/``.
UpstreamPublisher = Callable[[VendorSelfImprovementEvent, ContributionOutcome], bool]


def is_vendor_deployment(
    *,
    bundle_flag: Optional[bool] = None,
    force_vendor: bool = False,
) -> bool:
    """Return True iff this process is the vendor's own Spine.

    Resolution: explicit ``force_vendor`` > ``bundle_flag`` arg >
    ``SPINE_DEPLOYMENT_KIND=vendor`` env var. The env var is metadata
    (deployment shape), NOT a secret value, so it does not violate #9.
    """
    if force_vendor:
        return True
    if bundle_flag is True:
        return True
    if bundle_flag is False:
        return False
    return os.environ.get(VENDOR_ENV_KEY, "").strip().lower() == VENDOR_ENV_VALUE


def _emit_self_improvement_audit(event: VendorSelfImprovementEvent) -> None:
    """Best-effort audit row marking the Tier 3 acceptance."""
    try:
        from shared.audit.audit_record import (  # type: ignore
            AuditRecord, chain_to_previous, write_via_psql,
        )
        meta = {
            "source_audit_record_id": event.source_audit_record_id,
            "event_key": event.event_key,
            "lesson_role": event.role,
        }
        rec = AuditRecord(
            role="vendor_self_improvement", subsystem="learning",
            action="vendor_self_improvement", actor="vendor",
            subject_type="lesson",
            subject_id=event.source_audit_record_id,
            metadata=meta,
        )
        rec = chain_to_previous(rec, None)
        write_via_psql(rec)
    except Exception as exc:  # noqa: BLE001 — audit is best-effort
        logger.info("tier3_audit_failed err=%s", exc)


def vendor_self_improvement_record(
    event: VendorSelfImprovementEvent,
    *,
    force_vendor: bool = False,
    bundle_flag: Optional[bool] = None,
    writer: Optional[Callable] = None,
    upstream_publisher: Optional[UpstreamPublisher] = None,
    writer_extras: Optional[dict[str, Any]] = None,
) -> VendorSelfImprovementResult:
    """Record an audit event into Tier 3 (vendor's cross-org lesson tier).

    On a non-vendor deployment this is a no-op returning
    ``accepted=False`` so it's safe to call from shared code paths.
    """
    now = datetime.now(timezone.utc)
    if not is_vendor_deployment(bundle_flag=bundle_flag, force_vendor=force_vendor):
        return VendorSelfImprovementResult(
            accepted=False, outcome=None,
            reason="not_vendor_deployment", recorded_at=now,
        )

    # Build a synthetic ScopePolicy that auto-permits cross_org for the
    # vendor's deployment — this bypasses customer consent because the
    # data IS the vendor's. Customer-facing code never reaches this
    # branch because of the deployment-kind guard above.
    vendor_policy = ScopePolicy(
        hub_id=event.hub_id,
        project_id=event.project_id,
        within_hub_enabled=True,
        cross_org_consent=True,
        granular_consent={},
    )
    ctx = ScopeContext(
        hub_id=event.hub_id,
        project_id=event.project_id,
        requested_scope=LearningScope.CROSS_ORG,
        data_category="vendor_self_improvement",
        bundle_cross_org_default=True,
    )
    payload = LessonPayload(
        lesson_text=event.lesson_text,
        source_audit_record_id=event.source_audit_record_id,
    )
    outcome = contribute_lesson(
        payload, ctx,
        explicit_policy=vendor_policy,
        writer=writer,
        writer_extras=writer_extras,
    )
    _emit_self_improvement_audit(event)

    dispatched = False
    if upstream_publisher is not None:
        try:
            dispatched = bool(upstream_publisher(event, outcome))
        except Exception as exc:  # noqa: BLE001
            logger.warning("tier3_upstream_publish_failed err=%s", exc)
            dispatched = False

    return VendorSelfImprovementResult(
        accepted=True,
        outcome=outcome,
        reason="vendor_self_improvement_recorded",
        recorded_at=now,
        upstream_dispatched=dispatched,
    )


__all__ = [
    "UpstreamPublisher",
    "VENDOR_ENV_KEY",
    "VENDOR_ENV_VALUE",
    "VendorSelfImprovementEvent",
    "VendorSelfImprovementResult",
    "is_vendor_deployment",
    "vendor_self_improvement_record",
]
