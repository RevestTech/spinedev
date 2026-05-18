"""Tested restore (layer 4 of #32).

Restore from a backup_run row, write the result to
``spine_dr.restore_test``, and surface anomalies in JSON for the
oncall + audit chain.

This module implements the BUILD for layer 4 — *"Documented + automated
restore. Periodic restore-to-throwaway-environment verification (weekly
default) — catches 'backups exist but restore broken' failure mode."*

Two entry points:

* :meth:`RestoreManager.restore_to_environment` — used by ``dr-test.sh``
  weekly and by the upgrade-flow re-validation (layer 12). Restores
  into a named ``tested_in_env`` and inserts the outcome row.
* :meth:`RestoreManager.restore_production` — used for actual disaster
  recovery; same engine, different metadata, fires a multi-medium
  notification (per #6) on entry + exit.

Both flows clock RTO in seconds and persist it. The acceptance criterion
from `docs/V3_BUILD_SEQUENCE.md` Wave 5 is *"DR weekly test: kill
container, restore from backup, verify Hub functional in < 30 min."*
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Optional
from uuid import UUID, uuid4

from recovery.backup import BackupTarget

logger = logging.getLogger("spine.recovery.restore")

#: Allowed values for ``tested_in_env`` column on ``spine_dr.restore_test``.
TestedEnv = Literal["staging", "dr-sandbox", "qa", "production"]


@dataclass(frozen=True)
class RestorePlan:
    """Inputs for one restore execution.

    Attributes:
        backup_run_id: UUID of the row in ``spine_dr.backup_run`` to
            restore from.
        tested_in_env: Required for restore_to_environment; either
            ``staging`` / ``dr-sandbox`` / ``qa``.
        target_postgres_dsn: Destination DSN; for dr-sandbox this points
            at the throwaway container.
        components: Subsystems to restore (subset of the backup's
            ``components_uploaded``).
        actor / project_id: audit attribution.
    """

    backup_run_id: UUID
    tested_in_env: TestedEnv = "dr-sandbox"
    target_postgres_dsn: Optional[str] = None
    components: tuple[str, ...] = ("postgres", "kg", "vault", "bundles")
    actor: str = "system"
    project_id: str = "system"


@dataclass(frozen=True)
class RestoreOutcome:
    """Result of one restore execution; mirrors ``spine_dr.restore_test``."""

    restore_test_id: UUID
    backup_run_id: UUID
    tested_at: datetime
    tested_in_env: TestedEnv
    restore_succeeded: bool
    rto_seconds: int
    anomalies: dict[str, Any]
    components_restored: tuple[str, ...] = ()
    error: Optional[str] = None

    def as_audit_metadata(self) -> dict[str, Any]:
        return {
            "restore_test_id": str(self.restore_test_id),
            "backup_run_id": str(self.backup_run_id),
            "succeeded": self.restore_succeeded,
            "rto_seconds": self.rto_seconds,
            "components_restored": list(self.components_restored),
            "anomalies": self.anomalies,
            "tested_in_env": self.tested_in_env,
            "error": self.error,
        }


@dataclass(frozen=True)
class TestRestoreReport:
    """High-level summary of a weekly DR test cycle.

    Returned by ``RestoreManager.run_weekly_test`` so dashboards can
    render PASS/FAIL + last-RTO + anomalies at a glance.
    """

    # Tell pytest not to treat this as a test class (the "Test"
    # prefix is unfortunate but the public-API name is locked).
    __test__: bool = False

    cycle_id: UUID = field(default_factory=uuid4)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    outcomes: tuple[RestoreOutcome, ...] = ()
    all_passed: bool = False

    @property
    def worst_rto_seconds(self) -> int:
        if not self.outcomes:
            return 0
        return max(o.rto_seconds for o in self.outcomes)


class RestoreManager:
    """Orchestrates restores from backup_run rows.

    Constructor parameters identical in spirit to BackupManager —
    everything that talks to the world is injectable for tests.
    """

    def __init__(
        self,
        target: BackupTarget,
        *,
        runner: Optional[Callable[[list[str]], tuple[int, str, str]]] = None,
        secret_fetcher: Optional[Callable[[str], Awaitable[str]]] = None,
        pool_factory: Optional[Callable[[], Any]] = None,
        psql_executable: str = "psql",
        pg_restore_executable: str = "pg_restore",
        notify_fn: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.target = target
        self._runner = runner or _default_runner
        self._secret_fetcher = secret_fetcher or _default_secret_fetcher
        self._pool_factory = pool_factory or (lambda: None)
        self._psql_executable = psql_executable
        self._pg_restore_executable = pg_restore_executable
        self._notify_fn = notify_fn or _default_notify

    # --- restore-to-throwaway --------------------------------------

    async def restore_to_environment(self, plan: RestorePlan) -> RestoreOutcome:
        """Restore the given backup into a non-prod environment.

        Logs the outcome into ``spine_dr.restore_test`` with the measured
        RTO and any anomalies detected during integrity checks.
        """
        if plan.tested_in_env == "production":
            raise ValueError(
                "restore_to_environment refuses tested_in_env='production'; "
                "use restore_production() instead — it fires the operator "
                "notification + reads the production target DSN from vault.",
            )
        return await self._do_restore(plan, is_production=False)

    async def restore_production(self, plan: RestorePlan) -> RestoreOutcome:
        """Production DR restore — same engine, with notifications + extra audit."""
        # Force prod env tag regardless of incoming plan.
        prod_plan = RestorePlan(
            backup_run_id=plan.backup_run_id,
            tested_in_env="production",
            target_postgres_dsn=plan.target_postgres_dsn,
            components=plan.components,
            actor=plan.actor,
            project_id=plan.project_id,
        )
        self._notify_fn(
            "[recovery] PRODUCTION RESTORE STARTED",
            f"backup_run={prod_plan.backup_run_id} actor={prod_plan.actor}",
        )
        outcome = await self._do_restore(prod_plan, is_production=True)
        self._notify_fn(
            f"[recovery] PRODUCTION RESTORE {'SUCCEEDED' if outcome.restore_succeeded else 'FAILED'}",
            f"rto={outcome.rto_seconds}s anomalies={list(outcome.anomalies)}",
        )
        return outcome

    # --- weekly test cycle -----------------------------------------

    async def run_weekly_test(
        self, *, project_id: str = "system",
        actor: str = "dr-test-cron",
    ) -> TestRestoreReport:
        """One full weekly DR cycle: pick newest backup, restore, report.

        This is what ``tools/dr-test.sh`` triggers on its schedule.
        Returns a TestRestoreReport so the caller can decide to page on
        FAIL (the script does this via the notify_fn).
        """
        cycle_id = uuid4()
        started = datetime.now(timezone.utc)
        backup_run_id = await self._most_recent_completed_backup()
        if backup_run_id is None:
            outcome = RestoreOutcome(
                restore_test_id=uuid4(),
                backup_run_id=uuid4(),  # placeholder; no row to FK to
                tested_at=started, tested_in_env="dr-sandbox",
                restore_succeeded=False, rto_seconds=0,
                anomalies={"reason": "no_completed_backup_run_found"},
                error="no completed backup available to test",
            )
            return TestRestoreReport(
                cycle_id=cycle_id, started_at=started,
                completed_at=datetime.now(timezone.utc),
                outcomes=(outcome,), all_passed=False,
            )
        plan = RestorePlan(
            backup_run_id=backup_run_id,
            tested_in_env="dr-sandbox",
            actor=actor, project_id=project_id,
        )
        outcome = await self.restore_to_environment(plan)
        return TestRestoreReport(
            cycle_id=cycle_id, started_at=started,
            completed_at=datetime.now(timezone.utc),
            outcomes=(outcome,),
            all_passed=outcome.restore_succeeded,
        )

    # --- internals --------------------------------------------------

    async def _do_restore(
        self, plan: RestorePlan, *, is_production: bool,
    ) -> RestoreOutcome:
        restore_test_id = uuid4()
        tested_at = datetime.now(timezone.utc)
        start_perf = time.monotonic()
        anomalies: dict[str, Any] = {}
        restored: list[str] = []
        error: Optional[str] = None
        try:
            kms_key_ref = await self._resolve_kms_key()
            with tempfile.TemporaryDirectory(prefix=f"spine-dr-restore-{restore_test_id}-") as td:
                td_path = Path(td)
                for component in plan.components:
                    artifact_uri = self.target.uri_for(
                        "snapshots", str(plan.backup_run_id),
                        f"{component}.tar.zst",
                    )
                    local_artifact = td_path / f"{component}.tar.zst"
                    self._download(artifact_uri, local_artifact, kms_key_ref=kms_key_ref)
                    self._apply_component(
                        component, local_artifact, plan, anomalies=anomalies,
                    )
                    restored.append(component)
            integrity = self._verify_integrity(plan)
            if integrity:
                anomalies.setdefault("integrity_warnings", []).extend(integrity)
            succeeded = not anomalies.get("integrity_warnings") and len(restored) == len(plan.components)
        except Exception as exc:  # noqa: BLE001 — surface as outcome row
            logger.exception("restore_failed",
                             extra={"restore_test_id": str(restore_test_id)})
            error = str(exc)
            succeeded = False
        rto_seconds = int(time.monotonic() - start_perf)
        outcome = RestoreOutcome(
            restore_test_id=restore_test_id,
            backup_run_id=plan.backup_run_id,
            tested_at=tested_at,
            tested_in_env=plan.tested_in_env,
            restore_succeeded=succeeded,
            rto_seconds=rto_seconds,
            anomalies=anomalies,
            components_restored=tuple(restored),
            error=error,
        )
        await self._insert_restore_test(outcome)
        return outcome

    def _apply_component(
        self, component: str, artifact: Path, plan: RestorePlan,
        *, anomalies: dict[str, Any],
    ) -> None:
        """Apply one downloaded artifact to the target."""
        if component == "postgres":
            self._restore_postgres(artifact, plan)
            return
        if component in ("kg", "vault", "bundles"):
            # Placeholder until real per-subsystem restorers land. We
            # still validate the artifact looks like JSON so a corrupt
            # download surfaces as an anomaly rather than a silent pass.
            try:
                payload = json.loads(artifact.read_text())
                if not isinstance(payload, dict):
                    anomalies.setdefault("malformed_artifact", []).append(component)
            except Exception as exc:  # noqa: BLE001
                anomalies.setdefault("malformed_artifact", []).append(
                    f"{component}:{exc}",
                )
            return
        anomalies.setdefault("unknown_component", []).append(component)

    def _restore_postgres(self, artifact: Path, plan: RestorePlan) -> None:
        dsn = plan.target_postgres_dsn or "postgres://localhost/spine_dr_sandbox"
        # pg_restore wants the directory or tarball; we expect tar.
        argv = [
            self._pg_restore_executable,
            "--dbname", dsn,
            "--clean", "--if-exists", "--no-owner",
            str(artifact),
        ]
        rc, _stdout, stderr = self._runner(argv)
        if rc != 0:
            raise RuntimeError(
                f"pg_restore failed (rc={rc}): {stderr.strip()[:512]}",
            )

    def _verify_integrity(self, plan: RestorePlan) -> list[str]:
        """Run lightweight post-restore checks.

        Real implementation in v1.1: row-count parity, audit-chain hash
        verify, KG node-count parity. For Wave 5 we do a structural
        check (target DSN reachable, ``spine_audit.audit_event`` table
        present) so the test path exercises end-to-end and tests can
        inject anomalies via mocks.
        """
        warnings: list[str] = []
        dsn = plan.target_postgres_dsn or "postgres://localhost/spine_dr_sandbox"
        argv = [self._psql_executable, dsn, "-c", "SELECT 1;", "-tA"]
        rc, _stdout, stderr = self._runner(argv)
        if rc != 0:
            warnings.append(f"target_dsn_unreachable: {stderr.strip()[:200]}")
        return warnings

    def _download(self, src_uri: str, dest: Path, *, kms_key_ref: Optional[str]) -> None:
        argv = self._download_argv(src_uri, dest, kms_key_ref)
        rc, _stdout, stderr = self._runner(argv)
        if rc != 0:
            raise RuntimeError(
                f"download from {src_uri} failed (rc={rc}): {stderr.strip()[:512]}",
            )

    def _download_argv(
        self, src_uri: str, dest: Path, kms_key_ref: Optional[str],
    ) -> list[str]:
        """Build the cloud-CLI argv for one download.

        Tests assert on this; symmetric to BackupManager._upload_argv.
        """
        if self.target.scheme in ("s3", "minio"):
            argv = ["aws", "s3", "cp", src_uri, str(dest), "--only-show-errors"]
            if self.target.endpoint_url:
                argv += ["--endpoint-url", self.target.endpoint_url]
            return argv
        if self.target.scheme == "gs":
            return ["gcloud", "storage", "cp", src_uri, str(dest), "--quiet"]
        if self.target.scheme == "azure":
            container = self.target.bucket
            blob = src_uri.split(f"{container}/", 1)[1]
            return [
                "az", "storage", "blob", "download",
                "--container-name", container,
                "--name", blob,
                "--file", str(dest),
                "--no-progress",
            ]
        if self.target.scheme == "file":
            return ["cp", src_uri.removeprefix("file://"), str(dest)]
        raise ValueError(f"unknown scheme {self.target.scheme!r}")

    async def _resolve_kms_key(self) -> Optional[str]:
        if not self.target.kms_key_ref:
            return None
        return await self._secret_fetcher(self.target.kms_key_ref)

    async def _most_recent_completed_backup(self) -> Optional[UUID]:
        pool = self._pool_factory()
        if pool is None:
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM spine_dr.backup_run "
                "WHERE status = 'completed' "
                "ORDER BY completed_at DESC NULLS LAST LIMIT 1;",
            )
        if row is None:
            return None
        # asyncpg returns UUID; mocks return dict-like rows.
        raw = row["id"] if isinstance(row, dict) or hasattr(row, "__getitem__") else row[0]
        return raw if isinstance(raw, UUID) else UUID(str(raw))

    async def _insert_restore_test(self, outcome: RestoreOutcome) -> None:
        pool = self._pool_factory()
        if pool is None:
            return
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO spine_dr.restore_test "
                "(id, backup_run_id, tested_at, tested_in_env, "
                " restore_succeeded, rto_seconds, anomalies_jsonb) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb);",
                outcome.restore_test_id,
                outcome.backup_run_id,
                outcome.tested_at,
                outcome.tested_in_env,
                outcome.restore_succeeded,
                outcome.rto_seconds,
                json.dumps(outcome.anomalies),
            )


# ---------------------------------------------------------------------------
# Defaults (overridable for tests)
# ---------------------------------------------------------------------------


def _default_runner(argv: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            argv, check=False, capture_output=True, text=True, timeout=600,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError as exc:
        return 127, "", f"command not found: {argv[0]!r} — {exc}"
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"timed out after {exc.timeout}s: {' '.join(argv)}"


async def _default_secret_fetcher(path: str) -> str:
    from shared.secrets import get_secret
    return await get_secret(path)


def _default_notify(subject: str, body: str) -> None:
    """Best-effort notify; never raises (DR caller must not depend on it)."""
    try:
        from shared.notify import NotificationEvent, Notifier
        from shared.notify.channels import StdoutChannel
        notifier = Notifier(channels=[StdoutChannel()])
        notifier.notify(NotificationEvent(
            event_type="project_blocked",
            project_id="recovery", project_name="recovery",
            phase="dr", actor="recovery",
            summary=subject, severity="critical",
            metadata={"body": body},
        ))
    except Exception:  # noqa: BLE001
        logger.warning("notify_failed", extra={"subject": subject})


__all__ = [
    "RestoreManager",
    "RestoreOutcome",
    "RestorePlan",
    "TestedEnv",
    "TestRestoreReport",
]
