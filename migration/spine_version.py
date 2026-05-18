"""Spine version migrations — design decision #33 D.

When the vendor publishes a new Spine release with breaking changes,
the customer's running deployment needs a coherent upgrade across:

* DB schemas (Flyway migrations under ``db/flyway/sql/``)
* Org-policy + license bundle formats (``shared/standards/`` +
  ``shared/schemas/license/``)
* Role-charter spec version (``shared/charters/``)
* Vault namespace layout (``shared/secrets`` reserved prefixes)
* KG schema (``spine_kg`` Flyway baseline + extractor contracts)

Per the design doc this is **engineering hygiene** — required
Day 1, wired into the update-distribution flow (#16) with a
**customer-admin approval gate per migration** and an
**N-2 cross-version compatibility** commitment.

Hard policy:

* **Downgrades are BLOCKED.** Attempting ``to_version < from_version``
  raises :class:`DowngradeBlocked` with an error message pointing the
  admin at restoring from a ``recovery/`` snapshot (Squad E's domain).
* **N-2 only for direct upgrades.** Anything outside the
  ``N_MINUS_K_DIRECT_UPGRADE_DISTANCE`` window must hop through an
  intermediate version. The planner emits the explicit hop chain.
* **Idempotent.** Re-running ``upgrade`` against an already-current
  deployment is a no-op with a clear log line — no schema changes,
  no audit-chain entries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol

from migration.version_registry import (
    CURRENT_SPINE_VERSION,
    N_MINUS_K_DIRECT_UPGRADE_DISTANCE,
    SUPPORTED_SPINE_VERSIONS,
    SUBSYSTEM_VERSIONS,
    SubsystemVersion,
)

logger = logging.getLogger("spine.migration.spine_version")


class DowngradeBlocked(Exception):
    """Raised when ``to_version`` precedes ``from_version``.

    Per #33 D the downgrade path is unsafe in general (newer schemas
    may carry columns / KG nodes / charter clauses that v(n-1) has no
    handler for). Operators who need to roll back must restore from a
    pre-upgrade :mod:`recovery` snapshot.
    """


class UnsupportedUpgradePath(Exception):
    """Raised when ``upgrade`` can't compute a valid path.

    Reasons:

    * Either version is not in :data:`SUPPORTED_SPINE_VERSIONS`.
    * The gap exceeds the N-2 commitment and the caller did not
      explicitly opt into the multi-hop plan via :func:`supported_paths`.
    """


@dataclass(frozen=True)
class UpgradeStep:
    """One subsystem-scoped step inside an :class:`UpgradePlan`."""

    subsystem: str
    from_version: str
    to_version: str
    handler_id: str
    rationale: str = ""


@dataclass
class UpgradePlan:
    """An ordered list of :class:`UpgradeStep` items + provenance metadata."""

    from_spine_version: str
    to_spine_version: str
    steps: list[UpgradeStep] = field(default_factory=list)
    intermediate_stops: list[str] = field(default_factory=list)
    requires_admin_approval: bool = True

    def is_noop(self) -> bool:
        return not self.steps


@dataclass
class UpgradeReport:
    """Per-step outcome of an :func:`upgrade` execution."""

    plan: UpgradePlan
    started_at: str
    finished_at: str = ""
    step_outcomes: list[tuple[UpgradeStep, str, str]] = field(default_factory=list)
    # tuples: (step, status, message)
    all_ok: bool = False


# ---------------------------------------------------------------------------
# Plan computation
# ---------------------------------------------------------------------------


def _version_index(v: str) -> int:
    try:
        return SUPPORTED_SPINE_VERSIONS.index(v)
    except ValueError as exc:
        raise UnsupportedUpgradePath(
            f"spine version {v!r} not in supported set "
            f"{SUPPORTED_SPINE_VERSIONS}",
        ) from exc


def supported_paths(
    from_version: str, to_version: str,
) -> list[str]:
    """Return the ordered list of Spine versions the upgrade must walk.

    * Same version → ``[from_version]`` (no-op signal).
    * Within N-2 → direct: ``[from_version, to_version]``.
    * Beyond N-2 → emits each intermediate version inclusive.

    Raises:
        DowngradeBlocked: ``to_version < from_version``.
        UnsupportedUpgradePath: either version unknown.
    """
    i_from = _version_index(from_version)
    i_to = _version_index(to_version)
    if i_to < i_from:
        raise DowngradeBlocked(
            f"downgrade blocked: {from_version} -> {to_version}; "
            "restore from a recovery/ snapshot taken before the previous "
            "upgrade. See docs/DR_RUNBOOK.md.",
        )
    if i_to == i_from:
        return [from_version]
    gap = i_to - i_from
    if gap <= N_MINUS_K_DIRECT_UPGRADE_DISTANCE:
        return [from_version, to_version]
    # Emit a per-version hop chain; each hop is itself within the N-2
    # window.
    return list(SUPPORTED_SPINE_VERSIONS[i_from:i_to + 1])


def _build_step(
    subsystem: SubsystemVersion, hop_from: str, hop_to: str,
) -> UpgradeStep:
    """Materialise one upgrade step for ``subsystem`` between two Spine versions.

    Handler IDs follow the convention ``<schema_kind>__<from>__to__<to>``.
    The :class:`UpgradeExecutor` looks these up in its handler table; the
    in-tree :class:`StubExecutor` recognises them as no-ops so tests can
    exercise the planner without owning the entire upgrade matrix.
    """
    handler_id = (
        f"{subsystem.schema_kind}__{subsystem.subsystem}__"
        f"{hop_from}__to__{hop_to}"
    )
    return UpgradeStep(
        subsystem=subsystem.subsystem,
        from_version=subsystem.min_supported_version
            if hop_from == SUPPORTED_SPINE_VERSIONS[0] else subsystem.current_version,
        to_version=subsystem.current_version,
        handler_id=handler_id,
        rationale=(
            f"{subsystem.subsystem}: {subsystem.notes} "
            f"(spine {hop_from} -> {hop_to})"
        ),
    )


def plan(from_version: str, to_version: str) -> UpgradePlan:
    """Compute an :class:`UpgradePlan` for a Spine-version upgrade.

    Raises:
        DowngradeBlocked / UnsupportedUpgradePath: per
        :func:`supported_paths`.
    """
    hops = supported_paths(from_version, to_version)
    if len(hops) == 1:
        return UpgradePlan(
            from_spine_version=from_version,
            to_spine_version=to_version,
            steps=[],
            intermediate_stops=[],
            requires_admin_approval=False,
        )
    intermediate_stops = list(hops[1:-1])
    steps: list[UpgradeStep] = []
    # For every (hop_n, hop_n+1) pair walk every subsystem.
    for i in range(len(hops) - 1):
        hop_from, hop_to = hops[i], hops[i + 1]
        for subsystem in SUBSYSTEM_VERSIONS:
            steps.append(_build_step(subsystem, hop_from, hop_to))
    return UpgradePlan(
        from_spine_version=from_version,
        to_spine_version=to_version,
        steps=steps,
        intermediate_stops=intermediate_stops,
        requires_admin_approval=True,
    )


# ---------------------------------------------------------------------------
# Executor + the in-tree stub
# ---------------------------------------------------------------------------


class UpgradeExecutor(Protocol):
    """Per-handler executor surface.

    Production wires this to real Flyway runners, bundle validators,
    charter spec migrators, vault-namespace updaters, and KG schema
    runners. Tests pass an in-memory stub that records calls.

    Every handler MUST be idempotent for a given (deployment, step).
    """

    def execute(self, step: UpgradeStep) -> str:
        """Execute ``step``; return a short message for the audit log."""
        ...


@dataclass
class StubExecutor:
    """Records calls + emits a uniform "noop" message.

    Used as the default executor when callers don't supply one — keeps
    :func:`upgrade` callable in tests + dry-run paths without owning the
    upgrade matrix.
    """

    calls: list[UpgradeStep] = field(default_factory=list)

    def execute(self, step: UpgradeStep) -> str:
        self.calls.append(step)
        return (
            f"stub executor: would run {step.handler_id} "
            f"(subsystem={step.subsystem}, {step.from_version} -> {step.to_version})"
        )


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------


ApprovalGate = Callable[[UpgradePlan], bool]
"""Function signature for the customer-admin approval check.

Production wires this to a Hub decision-card flow (#5); tests inject a
plain lambda. The gate is called exactly once per :func:`upgrade` run,
before any handler executes.
"""


def _auto_deny_gate(plan: UpgradePlan) -> bool:  # pragma: no cover
    """Default gate: refuse to upgrade without an explicit approval gate.

    Per #16, no auto-push: customer admin MUST approve every migration.
    The :func:`upgrade` entry point therefore refuses to proceed when
    the caller doesn't supply an approval callable.
    """
    return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def upgrade(
    *,
    from_version: str,
    to_version: str,
    executor: Optional[UpgradeExecutor] = None,
    approve: Optional[ApprovalGate] = None,
    dry_run: bool = False,
) -> UpgradeReport:
    """Run a Spine-version upgrade end-to-end.

    Args:
        from_version: Source Spine version (must be in
            :data:`SUPPORTED_SPINE_VERSIONS`).
        to_version: Target Spine version. Must be >= ``from_version``;
            downgrades raise :class:`DowngradeBlocked`.
        executor: Per-step handler runner; defaults to
            :class:`StubExecutor` so tests / dry-runs work out of the
            box.
        approve: Customer-admin approval callable; required when the
            plan has any steps. Per #16, no auto-push.
        dry_run: When True, the plan is computed + approval is still
            requested + each step is recorded as "skipped (dry_run)",
            but no executor call happens.

    Returns:
        An :class:`UpgradeReport` summarising every step.

    Raises:
        DowngradeBlocked: per the downgrade policy.
        UnsupportedUpgradePath: per :func:`supported_paths`.
        PermissionError: when ``approve`` returns False.
    """
    started = datetime.now(timezone.utc)
    upgrade_plan = plan(from_version, to_version)
    report = UpgradeReport(
        plan=upgrade_plan,
        started_at=started.isoformat(),
    )

    if upgrade_plan.is_noop():
        report.all_ok = True
        report.finished_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            "spine.migration.spine_version.noop",
            extra={"from": from_version, "to": to_version},
        )
        return report

    gate = approve or _auto_deny_gate
    if not gate(upgrade_plan):
        raise PermissionError(
            f"upgrade {from_version} -> {to_version} requires customer-admin "
            "approval; none granted (per #16, no auto-push).",
        )

    exec_ = executor or StubExecutor()
    ok = True
    for step in upgrade_plan.steps:
        if dry_run:
            report.step_outcomes.append(
                (step, "skipped", f"dry_run; would run {step.handler_id}"),
            )
            continue
        try:
            msg = exec_.execute(step)
            report.step_outcomes.append((step, "ok", msg))
        except Exception as exc:  # noqa: BLE001
            ok = False
            report.step_outcomes.append((step, "error", str(exc)))
            logger.error(
                "spine.migration.spine_version.step_failed",
                extra={"step": step.handler_id, "err": str(exc)},
            )
            break  # halt the plan on first failure; recovery is manual

    report.all_ok = ok and not dry_run or (dry_run and all(
        s[1] in ("skipped", "ok") for s in report.step_outcomes
    ))
    report.finished_at = datetime.now(timezone.utc).isoformat()
    return report


__all__ = [
    "ApprovalGate",
    "DowngradeBlocked",
    "StubExecutor",
    "UnsupportedUpgradePath",
    "UpgradeExecutor",
    "UpgradePlan",
    "UpgradeReport",
    "UpgradeStep",
    "plan",
    "supported_paths",
    "upgrade",
]
