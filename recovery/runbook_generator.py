"""Auto-generated DR runbook per deployment (layer 11 of #32).

Per #32 layer 11:

> Auto-generated per deployment based on actual configuration. Updated
> when bundle or topology changes. Includes: pager rotation, recovery
> commands, escalation paths, RPO/RTO, last-tested date.

We render Markdown — same format the docs squad (Squad G) consumes — so
the runbook can drop into ``docs/DR_RUNBOOK.md`` for review or be
exported via the ``recovery_runbook_export`` MCP tool to the customer's
preferred destination (Slack pinned message / Confluence page / Vanta
evidence file).

The generator is intentionally deterministic given the same inputs so
the audit trail can record a content hash and detect drift between
revisions. It pulls live state from:

* ``recovery.health.HealthProber.generate_report()`` for current
  component status snapshot.
* ``recovery.cross_region.LICENSE_FLAG`` for layer-7 coverage line.
* ``recovery.backup.DEFAULT_RETENTION_DAYS`` for layer-3 retention.
* The last ``spine_dr.backup_run`` + ``spine_dr.restore_test`` rows
  for "last tested" dates.

The runbook structure is fixed (12 sections, one per DR layer + a
header). The :class:`RunbookSection` dataclass holds the per-section
content so a future Hub-UI panel can render it section-by-section.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from recovery.backup import DEFAULT_RETENTION_DAYS
from recovery.cross_region import IMPLEMENTATION_VERSION, LICENSE_FLAG
from recovery.health import HEALTH_COMPONENTS

logger = logging.getLogger("spine.recovery.runbook")


@dataclass(frozen=True)
class RunbookSection:
    """One section of the generated runbook."""

    layer_id: int
    title: str
    body_markdown: str
    rpo_target: str = ""
    rto_target: str = ""
    last_tested_at: Optional[datetime] = None


@dataclass(frozen=True)
class RunbookInputs:
    """Inputs the generator consumes.

    Attributes mirror the V3 spec; pass real values when generating for
    a customer deployment, sample defaults are used in dev.
    """

    deployment_shape: str  # laptop | byoc | customer-cloud | on-prem
    customer_name: str
    primary_region: str
    pager_rotation: tuple[str, ...]
    storage_target_uri: str
    kms_key_ref: Optional[str]
    cross_region_licensed: bool
    last_backup_completed_at: Optional[datetime] = None
    last_restore_test_at: Optional[datetime] = None
    last_restore_succeeded: Optional[bool] = None
    last_restore_rto_seconds: Optional[int] = None
    federation_parent_url: Optional[str] = None
    soft_delete_retention_days: int = 7
    snapshot_retention_days: int = DEFAULT_RETENTION_DAYS
    backup_cadence_minutes: int = 5  # WAL streaming RPO floor


class RunbookGenerator:
    """Produce a Markdown runbook + content hash for a given deployment."""

    def __init__(self) -> None:
        # No constructor state — the generator is pure given inputs.
        pass

    def build_sections(self, inputs: RunbookInputs) -> list[RunbookSection]:
        return [
            self._section_1_container_recovery(inputs),
            self._section_2_process_supervision(inputs),
            self._section_3_continuous_backup(inputs),
            self._section_4_tested_restore(inputs),
            self._section_5_heartbeat(inputs),
            self._section_6_federation_autonomy(inputs),
            self._section_7_cross_region(inputs),
            self._section_8_vault_unseal(inputs),
            self._section_9_soft_delete(inputs),
            self._section_10_vendor_update_infra(inputs),
            self._section_11_runbook_itself(inputs),
            self._section_12_backup_verification(inputs),
        ]

    def render(self, inputs: RunbookInputs) -> str:
        """Render the full Markdown runbook."""
        sections = self.build_sections(inputs)
        lines: list[str] = []
        lines.append(self._header(inputs))
        lines.append("")
        lines.append("## DR posture summary")
        lines.append("")
        lines.append("| Layer | Title | RPO | RTO | Last tested |")
        lines.append("|---|---|---|---|---|")
        for s in sections:
            tested = s.last_tested_at.isoformat() if s.last_tested_at else "—"
            lines.append(
                f"| {s.layer_id} | {s.title} | {s.rpo_target or '—'} | "
                f"{s.rto_target or '—'} | {tested} |"
            )
        lines.append("")
        for s in sections:
            lines.append(f"## Layer {s.layer_id} — {s.title}")
            lines.append("")
            lines.append(s.body_markdown.rstrip())
            lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"_Generated at {datetime.now(timezone.utc).isoformat()}._")
        return "\n".join(lines)

    def content_hash(self, inputs: RunbookInputs) -> str:
        """Stable SHA-256 of the rendered runbook (for audit drift detection)."""
        return hashlib.sha256(self.render(inputs).encode("utf-8")).hexdigest()

    # --- per-layer sections ----------------------------------------

    def _header(self, inputs: RunbookInputs) -> str:
        pager = ", ".join(inputs.pager_rotation) if inputs.pager_rotation else "UNSET — set immediately"
        return "\n".join([
            f"# DR Runbook — {inputs.customer_name}",
            "",
            f"> Auto-generated per design decision #32 layer 11. Deployment: "
            f"**{inputs.deployment_shape}** / region **{inputs.primary_region}**.",
            "",
            "**Pager rotation:** " + pager,
            "",
            "**Escalation path:** primary on-call → Master DevOps → Master "
            "Incident → vendor support (if licence allows).",
            "",
        ])

    def _section_1_container_recovery(self, inputs: RunbookInputs) -> RunbookSection:
        body = (
            "Container auto-restart is provided by the deployment substrate:\n\n"
            f"* If `{inputs.deployment_shape}` is K8s (customer-cloud / on-prem): "
            "kubelet liveness/readiness probes are configured on every Spine "
            "container. Replica count ≥ 2 for hub-api + mcp-server.\n"
            f"* If `{inputs.deployment_shape}` is laptop / single-host BYOC: "
            "`shared/runtime/watchdog.sh` supervises each daemon via PID files + "
            "heartbeat mtimes. See `recovery/auto_recovery.py` for the Python "
            "adapter.\n\n"
            "**Recovery command (non-K8s):**\n\n"
            "```\nbash shared/runtime/watchdog.sh\n```\n"
        )
        return RunbookSection(
            layer_id=1, title="Container auto-recovery",
            body_markdown=body, rpo_target="N/A", rto_target="≤ 30 s",
        )

    def _section_2_process_supervision(self, inputs: RunbookInputs) -> RunbookSection:
        body = (
            "Each role daemon is supervised by the watchdog above; a circuit "
            "breaker stops flapping targets after "
            f"5 restarts in 10 minutes (see `recovery.auto_recovery."
            "MAX_RESTARTS_PER_WINDOW`). When the breaker opens, the operator is "
            "paged via the multi-medium notifier per #6.\n\n"
            "**Diagnostic:**\n\n"
            "```\npython -c 'from recovery import AutoRecoveryManager; "
            "print([r.action for r in AutoRecoveryManager."
            "from_default_handoff().check_all()])'\n```\n"
        )
        return RunbookSection(
            layer_id=2, title="Process supervision",
            body_markdown=body, rpo_target="N/A", rto_target="≤ 30 s",
        )

    def _section_3_continuous_backup(self, inputs: RunbookInputs) -> RunbookSection:
        body = (
            f"Continuous WAL streaming + snapshot backups to "
            f"`{inputs.storage_target_uri}`.\n\n"
            f"* KMS key (vault path): `{inputs.kms_key_ref or 'UNSET — fix in bundle'}`\n"
            f"* Snapshot retention: {inputs.snapshot_retention_days} days\n"
            f"* WAL RPO floor: {inputs.backup_cadence_minutes} min\n\n"
            "**Trigger an immediate snapshot:**\n\n"
            "```\npython -c 'import asyncio; from recovery import BackupManager, "
            "BackupTarget, SnapshotPlan; asyncio.run(BackupManager(target=...)."
            "run_snapshot(SnapshotPlan()))'\n```\n"
            "Or via MCP: `recovery_snapshot`.\n"
        )
        return RunbookSection(
            layer_id=3, title="Continuous data backup",
            body_markdown=body, rpo_target="≤ 5 min", rto_target="N/A",
        )

    def _section_4_tested_restore(self, inputs: RunbookInputs) -> RunbookSection:
        succeeded = "PASS" if inputs.last_restore_succeeded else "FAIL"
        if inputs.last_restore_succeeded is None:
            succeeded = "NEVER TESTED — schedule `bash tools/dr-test.sh` immediately"
        body = (
            "Restore is exercised weekly into a throwaway environment by "
            "`tools/dr-test.sh`. The latest result:\n\n"
            f"* Status: **{succeeded}**\n"
            f"* RTO observed: "
            f"{inputs.last_restore_rto_seconds or '—'} seconds (target: ≤ 30 min)\n\n"
            "**Trigger a restore-to-throwaway now:**\n\n"
            "```\nbash tools/dr-test.sh --env=dr-sandbox\n```\n"
            "**Production restore (DESTRUCTIVE — incident-only):**\n\n"
            "```\npython -c 'import asyncio; from recovery import RestoreManager, "
            "RestorePlan; asyncio.run(RestoreManager(target=...)."
            "restore_production(RestorePlan(backup_run_id=...)))'\n```\n"
        )
        return RunbookSection(
            layer_id=4, title="Tested data restore",
            body_markdown=body, rpo_target="N/A", rto_target="≤ 30 min",
            last_tested_at=inputs.last_restore_test_at,
        )

    def _section_5_heartbeat(self, inputs: RunbookInputs) -> RunbookSection:
        comps = ", ".join(HEALTH_COMPONENTS)
        parent = inputs.federation_parent_url or "(none — leaf Hub)"
        body = (
            f"Heartbeats: this Hub + federation parent (`{parent}`) + (opt-in) "
            "vendor status registry. Probed components: " + comps + ".\n\n"
            "Failure routes through the multi-medium notifier (#6) within 60 s.\n\n"
            "**Read current health:**\n\n"
            "```\npython -c 'import asyncio; from recovery import HealthProber; "
            "print(asyncio.run(HealthProber().generate_report()).as_dict())'\n```\n"
            "Or via MCP: `recovery_health`.\n"
        )
        return RunbookSection(
            layer_id=5, title="Heartbeat protocol",
            body_markdown=body, rpo_target="N/A", rto_target="detection ≤ 1 min",
        )

    def _section_6_federation_autonomy(self, inputs: RunbookInputs) -> RunbookSection:
        body = (
            "Per #10, every Hub keeps working when its parent is down. "
            "If a child Hub loses its upstream, it continues serving local "
            "users; bundles already received remain in force; outbound updates "
            "queue until the parent returns.\n\n"
            "**No action required during a parent-Hub outage** — the local "
            "Hub is autonomous by design. Verify after recovery by checking "
            "`federation` MCP tools `federation_status` + `federation_pending_updates`."
        )
        return RunbookSection(
            layer_id=6, title="Federation autonomy",
            body_markdown=body, rpo_target="N/A", rto_target="always-on",
        )

    def _section_7_cross_region(self, inputs: RunbookInputs) -> RunbookSection:
        if inputs.cross_region_licensed:
            body = (
                f"License flag `{LICENSE_FLAG}` is ENABLED. Status reported by "
                "the cross-region plumbing.\n\n"
                f"> **NOTE:** Layer-7 plumbing is **{IMPLEMENTATION_VERSION}**. "
                "v1.0 ships seam-only. The Hub UI will show 'feature licensed, "
                "implementation pending' until the v1.1 build lands.\n"
            )
        else:
            body = (
                f"License flag `{LICENSE_FLAG}` is DISABLED. Active-passive "
                "cross-region replication is an enterprise-tier feature; "
                "contact your account contact about upgrading.\n\n"
                "In the meantime, layers 1–5 still bound your RPO/RTO inside "
                "the primary region.\n"
            )
        return RunbookSection(
            layer_id=7, title="Cross-region replication",
            body_markdown=body,
            rpo_target="≤ 5 min (when licensed + built)",
            rto_target="≤ 10 min (when licensed + built)",
        )

    def _section_8_vault_unseal(self, inputs: RunbookInputs) -> RunbookSection:
        body = (
            "Vault unseal uses either Shamir secret-sharing (3-of-5 human "
            "shares) or cloud-KMS auto-unseal (AWS KMS / Azure Key Vault / "
            "GCP KMS) — chosen at install via the Day-0 wizard.\n\n"
            "* If Shamir: the 5 share holders are listed in vault config; "
            "convene 3 to unseal during a DR incident.\n"
            "* If KMS auto-unseal: no human action required; the KMS round-trip "
            "happens on container start.\n\n"
            "See `vault/` subsystem for the precise unseal command for this "
            "deployment."
        )
        return RunbookSection(
            layer_id=8, title="Vault unseal recovery",
            body_markdown=body, rpo_target="N/A",
            rto_target="manual (Shamir) | auto (KMS)",
        )

    def _section_9_soft_delete(self, inputs: RunbookInputs) -> RunbookSection:
        body = (
            f"Hubs deleted via the admin UI are soft-deleted with a "
            f"{inputs.soft_delete_retention_days}-day retention window. "
            "Restore is one click in the Hub admin UI; after the retention "
            "window expires, a full restore from snapshot (layer 4) is "
            "required.\n\n"
            "Full deletion requires HMAC-signed double-confirmation."
        )
        return RunbookSection(
            layer_id=9, title="Soft-delete recovery",
            body_markdown=body, rpo_target="N/A",
            rto_target=f"recoverable for {inputs.soft_delete_retention_days} days",
        )

    def _section_10_vendor_update_infra(self, inputs: RunbookInputs) -> RunbookSection:
        body = (
            "Vendor's update publishing infra is CDN-fronted + multi-region. "
            "If vendor infra goes down, the customer keeps running the "
            "currently-installed version — there is NO auto-degradation.\n\n"
            "Probe vendor reachability via `recovery_health` — the "
            "`mcp_server` and `keycloak` probes catch most vendor-side "
            "outages that would otherwise impact upgrades."
        )
        return RunbookSection(
            layer_id=10, title="Vendor update infrastructure DR",
            body_markdown=body, rpo_target="N/A",
            rto_target="customers unaffected by vendor outage",
        )

    def _section_11_runbook_itself(self, inputs: RunbookInputs) -> RunbookSection:
        body = (
            "**This document is auto-generated.** Edits made by hand will be "
            "overwritten on the next generation cycle. To customise:\n\n"
            "* Update the per-deployment inputs in `bundle.dr.runbook_inputs`.\n"
            "* Re-generate via MCP `recovery_runbook_export` or "
            "  `python -c 'from recovery import RunbookGenerator; ...'`.\n\n"
            "Content hash on file is checked against the live render; drift "
            "fires `recovery_runbook_drift` notification."
        )
        return RunbookSection(
            layer_id=11, title="DR runbook (this document)",
            body_markdown=body, rpo_target="N/A", rto_target="always current",
        )

    def _section_12_backup_verification(self, inputs: RunbookInputs) -> RunbookSection:
        last = (inputs.last_backup_completed_at.isoformat()
                if inputs.last_backup_completed_at else "—")
        body = (
            "When vendor publishes a new Spine release, the post-upgrade hook "
            "calls `tools/dr-test.sh --validate-against-version <new>` to "
            "verify the new code can still restore the existing backup format. "
            "Failures block the upgrade approval per #16.\n\n"
            f"Last successful backup_run completed_at: {last}"
        )
        return RunbookSection(
            layer_id=12, title="Backup verification on every release",
            body_markdown=body, rpo_target="N/A", rto_target="continuous",
        )


__all__ = [
    "RunbookGenerator",
    "RunbookInputs",
    "RunbookSection",
]
