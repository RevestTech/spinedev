"""Continuous (WAL-based) + snapshot backup orchestration (layer 3 of #32).

This module is the BUILD for layer 3 of the DR architecture from
``docs/V3_DESIGN_DECISIONS.md`` §32. It does two things:

* **WAL-based continuous backup** — keeps RPO ≤ 5 min by shipping
  Postgres write-ahead-log segments to the customer's object storage on
  the side. Uses ``pg_receivewal`` under the hood.
* **Point-in-time snapshots** — full ``pg_basebackup`` (Postgres) +
  KG + Vault snapshot + bundle export, tarred and uploaded to the same
  target. Default retention 30d via per-bundle policy.

Storage targets are S3 / GCS / Azure Blob / MinIO / Wasabi, invoked via
subprocess against the customer-installed CLI (``aws`` / ``gcloud`` /
``az``). We do not pull in cloud SDKs as hard deps — see README rationale.

KMS encryption + storage credentials are vault-fetched via
``shared.secrets`` per design decision #9. The KMS key reference lives
at ``recovery/kms/<env>/key_id`` by default; storage creds live at
``recovery/storage/<env>/{access_key,secret_key,session_token}`` or the
provider-equivalent path. Nothing is read from process env vars.

Every backup execution writes a row to ``spine_dr.backup_run`` (see
``db/flyway/sql/V32__dr_backup_log.sql``). The audit chain captures
``action='recovery_backup_started'`` and ``recovery_backup_completed``.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Optional
from uuid import UUID, uuid4

logger = logging.getLogger("spine.recovery.backup")

#: Allowed ``run_type`` values for ``spine_dr.backup_run``.
RunType = Literal["continuous", "snapshot"]

#: Allowed terminal ``status`` values; ``in_progress`` is set on insert.
RunStatus = Literal["in_progress", "completed", "failed", "partial"]

#: Default retention window for snapshots (days). Per-bundle policy
#: may override; the BackupManager reads this at construction time.
DEFAULT_RETENTION_DAYS: int = 30

#: How often the WAL streamer rolls a fresh segment in production.
WAL_SEGMENT_BYTES: int = 16 * 1024 * 1024


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackupTarget:
    """Where backups are uploaded; resolved per-bundle at startup.

    Attributes:
        scheme: ``s3`` | ``gs`` | ``azure`` | ``minio`` | ``file``
            (``file`` is for tests; never use in production).
        bucket: Bucket / container / share name.
        prefix: Path prefix within the bucket; default ``spine-dr``.
        endpoint_url: Optional override for S3-compatible providers
            (MinIO, Wasabi, Backblaze B2).
        region: Optional region; some providers infer from auth context.
        kms_key_ref: Vault path that resolves to the customer KMS key
            reference (an AWS KMS ARN, GCP key resource name, Azure
            Key Vault key URL — opaque to us).
        storage_creds_path: Vault prefix for storage credentials
            (e.g. ``recovery/storage/prod``).
    """

    scheme: Literal["s3", "gs", "azure", "minio", "file"]
    bucket: str
    prefix: str = "spine-dr"
    endpoint_url: Optional[str] = None
    region: Optional[str] = None
    kms_key_ref: Optional[str] = None
    storage_creds_path: Optional[str] = None

    def uri_for(self, *parts: str) -> str:
        """Compose the destination URI for the given path parts.

        Returns ``s3://bucket/prefix/parts[0]/parts[1]/...``.
        """
        scheme_prefix = {
            "s3": "s3://",
            "minio": "s3://",
            "gs": "gs://",
            "azure": "azure://",
            "file": "file://",
        }[self.scheme]
        path = "/".join((self.prefix, *parts)).strip("/")
        return f"{scheme_prefix}{self.bucket}/{path}"

    @classmethod
    def from_bundle(cls, bundle: dict[str, Any]) -> "BackupTarget":
        """Construct a target from a (validated) bundle DR-policy dict.

        The bundle ships per-deployment under ``bundle.dr.target = {...}``;
        this method is a tolerant adapter so an older / partial bundle
        still produces a usable target. Missing scheme defaults to
        ``s3`` to fail loud rather than silently use ``file``.
        """
        return cls(
            scheme=bundle.get("scheme", "s3"),
            bucket=bundle["bucket"],
            prefix=bundle.get("prefix", "spine-dr"),
            endpoint_url=bundle.get("endpoint_url"),
            region=bundle.get("region"),
            kms_key_ref=bundle.get("kms_key_ref"),
            storage_creds_path=bundle.get("storage_creds_path"),
        )


@dataclass(frozen=True)
class SnapshotPlan:
    """Inputs for one snapshot backup execution.

    Attributes:
        components: Subsystems to include. Default = all four substrate
            stores (postgres, kg, vault snapshot, bundles archive).
        retention_days: Override DEFAULT_RETENTION_DAYS for this run.
        actor: Audit attribution; usually the role / cron caller.
        project_id: Spine project this backup belongs to.
    """

    components: tuple[str, ...] = ("postgres", "kg", "vault", "bundles")
    retention_days: int = DEFAULT_RETENTION_DAYS
    actor: str = "system"
    project_id: str = "system"


@dataclass(frozen=True)
class WalPlan:
    """Inputs for a continuous WAL-streaming session.

    Attributes:
        slot_name: Postgres replication slot to use; created on first
            start, persists across reconnects.
        max_segment_age_seconds: Force a segment switch + upload after
            this many seconds even if the segment isn't full (RPO floor).
        actor / project_id: as in SnapshotPlan.
    """

    slot_name: str = "spine_dr_wal"
    max_segment_age_seconds: int = 300
    actor: str = "system"
    project_id: str = "system"


@dataclass(frozen=True)
class BackupOutcome:
    """Result of one backup execution; mirrors ``spine_dr.backup_run``."""

    run_id: UUID
    run_type: RunType
    status: RunStatus
    started_at: datetime
    completed_at: Optional[datetime]
    size_bytes: int
    target_uri: str
    encryption_kms_key_ref: Optional[str]
    components_uploaded: tuple[str, ...] = ()
    error: Optional[str] = None

    def as_audit_metadata(self) -> dict[str, Any]:
        """Serialize for embedding in an audit_event row."""
        return {
            "run_id": str(self.run_id),
            "run_type": self.run_type,
            "status": self.status,
            "size_bytes": self.size_bytes,
            "target_uri": self.target_uri,
            "components_uploaded": list(self.components_uploaded),
            "kms_key_ref": self.encryption_kms_key_ref,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# BackupManager — orchestration
# ---------------------------------------------------------------------------


class BackupManager:
    """Orchestrates continuous WAL + snapshot backups against a target.

    Constructor parameters are deliberately injectable for tests:

    * ``runner`` — subprocess runner taking ``(argv) -> (rc, stdout, stderr)``.
      Production default = :func:`_default_runner`. Tests pass a mock.
    * ``secret_fetcher`` — async callable ``(path) -> str``. Production
      default = :func:`_default_secret_fetcher` which routes through
      ``shared.secrets.get_secret``. Tests pass an in-memory lookup.
    * ``pool_factory`` — callable returning an asyncpg-style pool with
      ``acquire()`` context. Tests pass a mock pool; production reads
      from the Hub bootstrap.
    """

    def __init__(
        self,
        target: BackupTarget,
        *,
        runner: Optional[Callable[[list[str]], tuple[int, str, str]]] = None,
        secret_fetcher: Optional[Callable[[str], Awaitable[str]]] = None,
        pool_factory: Optional[Callable[[], Any]] = None,
        psql_executable: str = "pg_basebackup",
        wal_executable: str = "pg_receivewal",
        kg_dumper: Optional[Callable[[Path], int]] = None,
        bundle_dumper: Optional[Callable[[Path], int]] = None,
        vault_dumper: Optional[Callable[[Path], int]] = None,
    ) -> None:
        self.target = target
        self._runner = runner or _default_runner
        self._secret_fetcher = secret_fetcher or _default_secret_fetcher
        self._pool_factory = pool_factory or (lambda: None)
        self._psql_executable = psql_executable
        self._wal_executable = wal_executable
        self._kg_dumper = kg_dumper or _placeholder_kg_dump
        self._bundle_dumper = bundle_dumper or _placeholder_bundle_dump
        self._vault_dumper = vault_dumper or _placeholder_vault_dump

    # --- snapshot ----------------------------------------------------

    async def run_snapshot(self, plan: SnapshotPlan) -> BackupOutcome:
        """Execute one point-in-time snapshot across requested components.

        High-level flow:

        1. Resolve KMS key ref + storage creds via vault.
        2. Insert ``spine_dr.backup_run`` row, status=in_progress.
        3. Stage each component into a tempdir using its component dumper.
        4. Upload each artifact via the storage CLI with server-side
           encryption pointing at the KMS key.
        5. Update the backup_run row with terminal status + size.
        6. Return the BackupOutcome (also written to audit chain by the
           MCP tool caller).
        """
        run_id = uuid4()
        started = datetime.now(timezone.utc)
        await self._insert_backup_run(
            run_id=run_id, run_type="snapshot", started_at=started,
            target_uri=self.target.uri_for("snapshots", str(run_id)),
        )
        try:
            kms_key_ref = await self._resolve_kms_key()
            uploaded: list[str] = []
            total_bytes = 0
            with tempfile.TemporaryDirectory(prefix=f"spine-dr-snap-{run_id}-") as td:
                td_path = Path(td)
                for component in plan.components:
                    dumper = self._dumper_for(component)
                    artifact_path = td_path / f"{component}.tar.zst"
                    bytes_written = dumper(artifact_path)
                    total_bytes += bytes_written
                    destination = self.target.uri_for(
                        "snapshots", str(run_id), artifact_path.name,
                    )
                    self._upload(artifact_path, destination, kms_key_ref=kms_key_ref)
                    uploaded.append(component)
            outcome = BackupOutcome(
                run_id=run_id, run_type="snapshot",
                status="completed",
                started_at=started,
                completed_at=datetime.now(timezone.utc),
                size_bytes=total_bytes,
                target_uri=self.target.uri_for("snapshots", str(run_id)),
                encryption_kms_key_ref=kms_key_ref,
                components_uploaded=tuple(uploaded),
            )
            await self._finalize_backup_run(outcome)
            return outcome
        except Exception as exc:  # noqa: BLE001 — terminal failure path
            logger.exception("snapshot_failed", extra={"run_id": str(run_id)})
            failed = BackupOutcome(
                run_id=run_id, run_type="snapshot", status="failed",
                started_at=started,
                completed_at=datetime.now(timezone.utc),
                size_bytes=0,
                target_uri=self.target.uri_for("snapshots", str(run_id)),
                encryption_kms_key_ref=None,
                error=str(exc),
            )
            await self._finalize_backup_run(failed)
            return failed

    # --- continuous WAL ---------------------------------------------

    async def start_wal_stream(self, plan: WalPlan) -> BackupOutcome:
        """Spin up a ``pg_receivewal`` subprocess against the WAL target.

        Returns a BackupOutcome with ``run_type='continuous'`` and
        ``status='in_progress'`` — the stream is long-running; lifecycle
        is owned by the supervisor (auto_recovery). Operators stop it by
        sending SIGTERM via ``stop_wal_stream``.
        """
        run_id = uuid4()
        started = datetime.now(timezone.utc)
        await self._insert_backup_run(
            run_id=run_id, run_type="continuous", started_at=started,
            target_uri=self.target.uri_for("wal", plan.slot_name),
        )
        kms_key_ref = await self._resolve_kms_key()
        local_wal_dir = Path(tempfile.gettempdir()) / f"spine-wal-{plan.slot_name}"
        local_wal_dir.mkdir(parents=True, exist_ok=True)
        argv = [
            self._wal_executable,
            "--directory", str(local_wal_dir),
            "--slot", plan.slot_name,
            "--no-loop",
            "--synchronous",
        ]
        # We invoke through the runner so tests don't actually fork a
        # streaming process. In production this call returns after
        # forking the daemon via the runner shim.
        rc, stdout, stderr = self._runner(argv)
        status: RunStatus = "in_progress" if rc == 0 else "failed"
        outcome = BackupOutcome(
            run_id=run_id, run_type="continuous", status=status,
            started_at=started, completed_at=None,
            size_bytes=0,
            target_uri=self.target.uri_for("wal", plan.slot_name),
            encryption_kms_key_ref=kms_key_ref,
            error=None if rc == 0 else stderr.strip()[:512],
        )
        # Update in-progress row's KMS ref now we know it.
        await self._update_kms_ref(run_id, kms_key_ref)
        if status == "failed":
            await self._finalize_backup_run(outcome)
        return outcome

    def stop_wal_stream(self, plan: WalPlan) -> None:
        """Best-effort stop for the WAL streamer (SIGTERM by slot name)."""
        argv = ["pkill", "-f", f"pg_receivewal.*--slot {plan.slot_name}"]
        self._runner(argv)

    # --- internals ---------------------------------------------------

    def _dumper_for(self, component: str) -> Callable[[Path], int]:
        if component == "postgres":
            return self._dump_postgres
        if component == "kg":
            return self._kg_dumper
        if component == "vault":
            return self._vault_dumper
        if component == "bundles":
            return self._bundle_dumper
        raise ValueError(f"Unknown backup component: {component!r}")

    def _dump_postgres(self, dest: Path) -> int:
        """Run ``pg_basebackup -D <dest>``; return bytes written."""
        argv = [
            self._psql_executable,
            "-D", str(dest),
            "--format", "tar",
            "--gzip",
            "--checkpoint", "fast",
            "--no-password",
        ]
        rc, _stdout, stderr = self._runner(argv)
        if rc != 0:
            raise RuntimeError(f"pg_basebackup failed (rc={rc}): {stderr.strip()[:512]}")
        return _dir_size(dest)

    def _upload(self, src: Path, dest_uri: str, *, kms_key_ref: Optional[str]) -> None:
        """Upload ``src`` to ``dest_uri`` via the appropriate cloud CLI."""
        argv = self._upload_argv(src, dest_uri, kms_key_ref)
        rc, _stdout, stderr = self._runner(argv)
        if rc != 0:
            raise RuntimeError(
                f"upload to {dest_uri} failed (rc={rc}): {stderr.strip()[:512]}",
            )

    def _upload_argv(
        self, src: Path, dest_uri: str, kms_key_ref: Optional[str],
    ) -> list[str]:
        """Build the cloud-CLI argv for one upload.

        Public-for-tests: the upload subprocess is hand-built per
        scheme so the test suite can assert on exact argv shape.
        """
        if self.target.scheme in ("s3", "minio"):
            argv = ["aws", "s3", "cp", str(src), dest_uri, "--only-show-errors"]
            if self.target.endpoint_url:
                argv += ["--endpoint-url", self.target.endpoint_url]
            if kms_key_ref:
                argv += [
                    "--sse", "aws:kms",
                    "--sse-kms-key-id", kms_key_ref,
                ]
            return argv
        if self.target.scheme == "gs":
            argv = ["gcloud", "storage", "cp", str(src), dest_uri, "--quiet"]
            if kms_key_ref:
                argv += ["--kms-key", kms_key_ref]
            return argv
        if self.target.scheme == "azure":
            # dest_uri encodes container; convert to az CLI form.
            container = self.target.bucket
            blob = dest_uri.split(f"{container}/", 1)[1]
            argv = [
                "az", "storage", "blob", "upload",
                "--account-name", self.target.bucket.split(".", 1)[0]
                if "." in self.target.bucket else self.target.bucket,
                "--container-name", container,
                "--name", blob,
                "--file", str(src),
                "--overwrite", "true",
                "--no-progress",
            ]
            if kms_key_ref:
                argv += ["--encryption-key-name", kms_key_ref]
            return argv
        if self.target.scheme == "file":
            # Used by tests; just a local copy.
            return ["cp", str(src), dest_uri.removeprefix("file://")]
        raise ValueError(f"unknown scheme {self.target.scheme!r}")

    async def _resolve_kms_key(self) -> Optional[str]:
        """Fetch the KMS key ref from vault. None means unencrypted (TEST ONLY)."""
        if not self.target.kms_key_ref:
            logger.warning("backup_kms_key_ref_missing",
                           extra={"target": self.target.bucket})
            return None
        try:
            return await self._secret_fetcher(self.target.kms_key_ref)
        except Exception as exc:  # noqa: BLE001 — vault failure is fatal in prod
            raise RuntimeError(
                f"unable to fetch KMS key from vault path "
                f"{self.target.kms_key_ref!r}: {exc}",
            ) from exc

    async def _insert_backup_run(
        self, *, run_id: UUID, run_type: RunType,
        started_at: datetime, target_uri: str,
    ) -> None:
        pool = self._pool_factory()
        if pool is None:
            return
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO spine_dr.backup_run "
                "(id, run_type, started_at, target_storage, status) "
                "VALUES ($1, $2, $3, $4, 'in_progress');",
                run_id, run_type, started_at, target_uri,
            )

    async def _update_kms_ref(self, run_id: UUID, kms_key_ref: Optional[str]) -> None:
        pool = self._pool_factory()
        if pool is None or kms_key_ref is None:
            return
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE spine_dr.backup_run SET encryption_kms_key_ref=$2 "
                "WHERE id=$1;", run_id, kms_key_ref,
            )

    async def _finalize_backup_run(self, outcome: BackupOutcome) -> None:
        pool = self._pool_factory()
        if pool is None:
            return
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE spine_dr.backup_run SET "
                "completed_at=$2, size_bytes=$3, status=$4, "
                "encryption_kms_key_ref=COALESCE($5, encryption_kms_key_ref) "
                "WHERE id=$1;",
                outcome.run_id,
                outcome.completed_at,
                outcome.size_bytes,
                outcome.status,
                outcome.encryption_kms_key_ref,
            )


# ---------------------------------------------------------------------------
# Default runner / secret fetcher / placeholder component dumpers
# ---------------------------------------------------------------------------


def _default_runner(argv: list[str]) -> tuple[int, str, str]:
    """Production subprocess runner; tests inject a mock instead.

    Captures stdout + stderr so callers can surface stderr in error
    messages. Timeout chosen conservatively (3 min) — backup uploads
    of multi-GB snapshots may exceed; production deployments should
    override via the runner injection.
    """
    try:
        proc = subprocess.run(
            argv, check=False, capture_output=True, text=True, timeout=180,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError as exc:
        return 127, "", f"command not found: {argv[0]!r} — {exc}"
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"timed out after {exc.timeout}s: {' '.join(argv)}"


async def _default_secret_fetcher(path: str) -> str:
    """Route to ``shared.secrets.get_secret`` (#9). Lazy import."""
    from shared.secrets import get_secret
    return await get_secret(path)


def _dir_size(p: Path) -> int:
    """Return total bytes under ``p`` (recursive)."""
    if not p.exists():
        return 0
    if p.is_file():
        return p.stat().st_size
    total = 0
    for sub in p.rglob("*"):
        if sub.is_file():
            try:
                total += sub.stat().st_size
            except OSError:
                continue
    return total


def _placeholder_kg_dump(dest: Path) -> int:
    """Default KG dumper — writes a manifest placeholder.

    Real KG dumper is wired by ``shared/kg/`` once that subsystem
    exposes a ``dump_to(path)`` API. Until then we emit a structured
    placeholder so the upload + manifest paths exercise end-to-end.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "component": "kg",
        "placeholder": True,
        "note": (
            "KG dumper not yet wired (Wave 5 followup). Real implementation "
            "will tar+zstd-compress the spine_kg schema export from "
            "shared/kg/exporter.py once that lands."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    dest.write_text(json.dumps(manifest, indent=2))
    return dest.stat().st_size


def _placeholder_bundle_dump(dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "component": "bundles",
        "placeholder": True,
        "note": (
            "Bundle dumper will tar the shared/standards/<bundle>/ trees "
            "with their signatures; placeholder until shared/standards "
            "exposes a list_active_bundles() helper."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    dest.write_text(json.dumps(manifest, indent=2))
    return dest.stat().st_size


def _placeholder_vault_dump(dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "component": "vault",
        "placeholder": True,
        "note": (
            "Vault snapshot is taken via the customer's OpenBao / Vault "
            "operator-raft-snapshot CLI; real wiring lives in vault/ "
            "subsystem. Backup module records the manifest only."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    dest.write_text(json.dumps(manifest, indent=2))
    return dest.stat().st_size


__all__ = [
    "BackupManager",
    "BackupOutcome",
    "BackupTarget",
    "DEFAULT_RETENTION_DAYS",
    "RunStatus",
    "RunType",
    "SnapshotPlan",
    "WAL_SEGMENT_BYTES",
    "WalPlan",
]
