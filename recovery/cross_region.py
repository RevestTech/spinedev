"""Cross-region active-passive replication (layer 7 of #32) — v1.0 STUB.

Per ``docs/V3_DESIGN_DECISIONS.md`` §32 + ``docs/V3_BUILD_SEQUENCE.md``
Part 4.4, layer 7 ships in v1.0 as a *seam only*:

* Default OFF — gated by the ``dr.cross_region`` license flag.
* Real replication plumbing arrives in v1.1+ enterprise tier.
* Active-active multi-cloud failover deferred to v1.1+ (CAP-theorem).

This module ships:

1. The license-flag check (per #23, every feature has a flag and is
   gated at the entry point).
2. The structured ``CrossRegionDisabled`` error so the Hub UI can light
   up the upgrade path (#23 — "Licensing becomes product discovery, not
   a wall").
3. A ``CrossRegionReplicator`` skeleton with documented contracts so
   v1.1 work has a stable interface to fill in.
4. ``promote_standby`` — module-level helper for the failover path; same
   gating + same v1.1 NotImplementedError stub.

The license flag check uses ``license.is_enabled("dr.cross_region")``
which already exists per Wave 4 Squad B. When the bundle disables the
flag (or no bundle is loaded), ``is_enabled`` returns False and we
raise. When the bundle enables it, we raise NotImplementedError so the
operator knows the feature is licensed but the build is v1.1+.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

logger = logging.getLogger("spine.recovery.cross_region")

#: License flag name that gates this whole subsystem.
LICENSE_FLAG: str = "dr.cross_region"

#: v1.0 ships seam-only; flip this when the real plumbing lands in v1.1.
IMPLEMENTATION_VERSION: str = "v1.1+ enterprise tier"


class CrossRegionDisabled(RuntimeError):
    """Raised when the license bundle doesn't enable ``dr.cross_region``.

    The Hub UI is expected to catch this and surface an upgrade CTA
    rather than treating it as a bug. ``message_for_ui`` is a stable
    string the UI may render verbatim.
    """

    def __init__(self, *, message_for_ui: Optional[str] = None) -> None:
        self.message_for_ui = message_for_ui or (
            "Cross-region active-passive replication is an enterprise-tier "
            "feature. Your current licence does not include dr.cross_region. "
            "Talk to your account contact about upgrading."
        )
        super().__init__(self.message_for_ui)


@dataclass(frozen=True)
class ReplicationTopology:
    """Static description of the active + standby region pair.

    Carried into the v1.1 plumbing as the durable contract — when the
    real implementation lands it consumes the same dataclass.

    Attributes:
        primary_region: Active region (cloud-provider region name).
        standby_region: Passive standby region.
        provider: ``aws`` | ``gcp`` | ``azure``.
        replication_mode: Per #32, ``active-passive`` is the v1.1 BUILD
            target; ``active-active`` is explicitly deferred to v1.1+.
        rpo_seconds_target: From #32 — 5 min for active-passive.
        rto_seconds_target: From #32 — 10 min for active-passive.
    """

    primary_region: str
    standby_region: str
    provider: Literal["aws", "gcp", "azure"]
    replication_mode: Literal["active-passive"] = "active-passive"
    rpo_seconds_target: int = 300
    rto_seconds_target: int = 600


class CrossRegionReplicator:
    """v1.0 stub for layer 7. All operations raise via :meth:`_gate`.

    The class exists so the Hub UI and the runbook generator can
    construct an instance and read the topology without crashing —
    only the actual operations refuse.
    """

    def __init__(self, topology: ReplicationTopology) -> None:
        self.topology = topology

    # --- gate -------------------------------------------------------

    def _gate(self, op_name: str) -> None:
        """Check ``dr.cross_region`` flag; raise the right error."""
        try:
            from license import is_enabled
        except Exception as exc:  # noqa: BLE001
            logger.warning("license_module_unavailable",
                           extra={"op": op_name, "err": str(exc)})
            raise CrossRegionDisabled(
                message_for_ui=(
                    "Cross-region replication requires the licence "
                    "subsystem to be loaded. The Hub bootstrap has not "
                    "completed (or is degraded). Retry once the licence "
                    "panel reports OK."
                ),
            ) from exc
        try:
            enabled = is_enabled(LICENSE_FLAG)
        except KeyError:
            # Flag not in KNOWN_FEATURE_FLAGS yet — treat as disabled
            # but log loudly so the licensing registry can be updated.
            logger.error("license_flag_unknown",
                         extra={"flag": LICENSE_FLAG, "op": op_name})
            raise CrossRegionDisabled(
                message_for_ui=(
                    f"Licence flag {LICENSE_FLAG!r} is not registered in "
                    "the Hub's KNOWN_FEATURE_FLAGS. This is a Hub-build "
                    "configuration error; contact support."
                ),
            ) from None
        if not enabled:
            raise CrossRegionDisabled()
        # Flag IS on → v1.1+ build hasn't landed → NotImplementedError.
        raise NotImplementedError(IMPLEMENTATION_VERSION)

    # --- operations (all stubs) ------------------------------------

    def start_replication(self) -> None:
        """Begin shipping WAL + KG events to the standby region."""
        self._gate("start_replication")

    def stop_replication(self) -> None:
        """Stop the replicator (planned maintenance / region change)."""
        self._gate("stop_replication")

    def status(self) -> dict[str, object]:
        """Read-only status snapshot. Even reads gate on the flag —
        the status itself is enterprise information."""
        self._gate("status")
        # Never reached; documenting the v1.1 return contract.
        return {  # pragma: no cover
            "primary_region": self.topology.primary_region,
            "standby_region": self.topology.standby_region,
            "provider": self.topology.provider,
            "replication_mode": self.topology.replication_mode,
            "lag_seconds": 0,
            "healthy": True,
        }

    def promote(self) -> None:
        """Promote the standby to primary (failover)."""
        self._gate("promote")


def promote_standby(topology: ReplicationTopology) -> None:
    """Module-level convenience for the one-shot promotion path.

    Same gating contract as :meth:`CrossRegionReplicator.promote`. Used
    by ``shared/mcp/tools/recovery.py`` (future ``recovery_failover``
    tool) so the MCP wrapper doesn't need to know about the class.
    """
    CrossRegionReplicator(topology).promote()


__all__ = [
    "IMPLEMENTATION_VERSION",
    "LICENSE_FLAG",
    "CrossRegionDisabled",
    "CrossRegionReplicator",
    "ReplicationTopology",
    "promote_standby",
]
