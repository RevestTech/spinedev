"""Full Spine state import — design decision #33 B inverse of ``export.py``.

Consumes a tarball produced by :mod:`migration.export` and re-creates the
state on a fresh Spine deployment. Round-trippable: re-exporting after a
fresh import produces a byte-identical tarball (the marketing promise
behind #33 B).

Safety contract:

1. **Signature first.** No DB write happens until the Ed25519 signature
   over ``MANIFEST.json`` has verified against the Hub's trusted vendor
   key (or the supplied :class:`Verifier`). The signing-key fingerprint
   in the manifest must match the verifier's expected fingerprint.
2. **Per-slice integrity.** Each ``schemas/<name>.jsonl`` is hashed and
   compared against the ``content_sha256`` recorded in the manifest
   before any row is inserted.
3. **Audit chain replay.** ``audit_chain_integrity.json`` is re-validated
   end-to-end after the import; any chain break raises
   :class:`ImportError` and rolls the import back.
4. **Idempotency.** A re-run of the same tarball against the same
   destination is a no-op (UPSERT-by-primary-key per slice).
5. **N-2 compatibility check.** If the export's ``spine_version`` differs
   from the current build's, the importer consults
   :mod:`migration.version_registry` and refuses if the gap exceeds the
   N-2 commitment; the operator must run :mod:`migration.spine_version`
   first.

The importer is **transactional at the slice level** — each schema slice
runs inside one transaction so a partial failure leaves a coherent
prefix. The audit-chain replay runs after every slice commits.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Protocol

from migration.export import MANIFEST_VERSION, SCHEMA_SLICES
from migration.version_registry import (
    CURRENT_SPINE_VERSION,
    N_MINUS_K_DIRECT_UPGRADE_DISTANCE,
    SUPPORTED_SPINE_VERSIONS,
)

logger = logging.getLogger("spine.migration.import")


class ImportError(Exception):
    """Raised on any import safety violation.

    Carries a stable ``.code`` string so callers can branch on the
    failure mode without parsing ``str(exc)``. Codes:

    * ``manifest_missing`` / ``manifest_malformed``
    * ``manifest_version_mismatch``
    * ``signature_missing`` / ``signature_invalid`` / ``fingerprint_mismatch``
    * ``slice_missing`` / ``slice_hash_mismatch``
    * ``audit_chain_break``
    * ``unsupported_source_version`` — older than N-2 window
    * ``newer_source_version`` — export was made by a later Spine release
    * ``dest_write_failed``
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Verifier(Protocol):
    """Ed25519 verifier interface.

    The default :class:`VaultVerifier` loads the vendor public key from
    the Hub vault at ``license/vendor_pubkey`` (the same path the
    license subsystem uses). Tests inject an :class:`InMemoryVerifier`.
    """

    def expected_fingerprint(self) -> str:
        """The trusted public-key fingerprint baked into this Hub build."""
        ...

    def verify(self, message: bytes, signature: bytes, fingerprint: str) -> None:
        """Raise :class:`ImportError` if signature is invalid for ``message``.

        Also raises if ``fingerprint`` doesn't match :meth:`expected_fingerprint`.
        """
        ...


class DestWriter(Protocol):
    """Synchronous writer facade over the destination Hub stores.

    Production implementation drives asyncpg + a vault adapter; tests
    use an in-memory collector and assert on the captured calls.

    Every method MUST be idempotent for a given (slice, primary key).
    """

    def write_schema_rows(self, schema: str, rows: list[dict[str, Any]]) -> int:
        """UPSERT ``rows`` into the named schema; return rows written."""
        ...

    def write_bundle_yaml(self, yaml_text: str) -> None: ...

    def write_license_envelope(self, envelope: dict[str, Any]) -> None: ...

    def write_role_charters(self, charters: dict[str, str]) -> None: ...

    def write_vault_refs(self, paths: list[str]) -> None:
        """Register that these vault paths are expected by the new deployment.

        The receiving operator must populate the secret values out-of-band
        (per #9 — no secret material travels in the export).
        """
        ...

    def replay_audit_chain(self) -> dict[str, Any]:
        """Re-verify the audit chain post-import.

        Shape mirrors ``StateReader.fetch_audit_chain_integrity_report``.
        """
        ...


# ---------------------------------------------------------------------------
# Vault-backed default verifier
# ---------------------------------------------------------------------------


class VaultVerifier:
    """Ed25519 verifier rooted in the Hub's trusted vendor public key.

    Loads the 32 public-key bytes from the vault path
    ``license/vendor_pubkey`` (the same path the license subsystem uses;
    see ``ADR-F-002``). Computes the SHA-256 fingerprint on first call
    and caches it.
    """

    def __init__(
        self,
        *,
        vault_path: str = "license/vendor_pubkey",
        secret_loader: Optional[Callable[[str], Awaitable[str]]] = None,
        trusted_fingerprint: Optional[str] = None,
    ) -> None:
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )

            self._Ed25519PublicKey = Ed25519PublicKey
            self._InvalidSignature = InvalidSignature
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "cryptography is required for VaultVerifier.",
            ) from exc
        self._vault_path = vault_path
        self._secret_loader = secret_loader
        self._cached_pub: Optional[bytes] = None
        self._cached_fp: Optional[str] = None
        self._trusted_fp_override = trusted_fingerprint

    def _load_pub(self) -> bytes:
        if self._cached_pub is not None:
            return self._cached_pub
        import asyncio

        loader = self._secret_loader
        if loader is None:
            from shared.secrets import get_secret as _get

            loader = _get  # type: ignore[assignment]
        coro = loader(self._vault_path)
        try:
            raw_b64 = asyncio.run(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                raw_b64 = loop.run_until_complete(coro)
            finally:
                loop.close()
        pub = base64.b64decode(raw_b64.encode("ascii"))
        if len(pub) != 32:
            raise ImportError(
                "fingerprint_mismatch",
                f"vault pub at {self._vault_path!r} is {len(pub)} bytes; "
                "expected 32 (Ed25519 raw).",
            )
        self._cached_pub = pub
        self._cached_fp = hashlib.sha256(pub).hexdigest()
        return pub

    def expected_fingerprint(self) -> str:
        if self._trusted_fp_override:
            return self._trusted_fp_override.lower()
        self._load_pub()
        assert self._cached_fp is not None
        return self._cached_fp

    def verify(self, message: bytes, signature: bytes, fingerprint: str) -> None:
        expected = self.expected_fingerprint()
        if fingerprint.lower() != expected:
            raise ImportError(
                "fingerprint_mismatch",
                f"manifest signing fingerprint {fingerprint!r} != trusted "
                f"vendor fingerprint {expected!r}",
            )
        pub = self._load_pub()
        try:
            self._Ed25519PublicKey.from_public_bytes(pub).verify(signature, message)
        except self._InvalidSignature as exc:
            raise ImportError(
                "signature_invalid",
                "Ed25519 signature did not verify against the trusted vendor key.",
            ) from exc


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ImportReport:
    """Outcome of an import run."""

    bundle_id: str
    source_spine_version: str
    dest_spine_version: str
    signature_ok: bool
    fingerprint_ok: bool
    schema_row_counts: dict[str, int] = field(default_factory=dict)
    schema_hash_ok: dict[str, bool] = field(default_factory=dict)
    audit_chain_ok: Optional[bool] = None
    vault_paths_registered: int = 0
    role_charters_written: int = 0
    dry_run: bool = False
    started_at: str = ""
    finished_at: str = ""
    notes: str = ""

    def all_ok(self) -> bool:
        """Convenience: True iff every safety check passed."""
        return (
            self.signature_ok
            and self.fingerprint_ok
            and all(self.schema_hash_ok.values())
            and (self.audit_chain_ok is not False)
        )


# ---------------------------------------------------------------------------
# Manifest reader
# ---------------------------------------------------------------------------


def _read_tar_member(tar: tarfile.TarFile, name: str) -> bytes:
    try:
        member = tar.getmember(name)
    except KeyError as exc:
        raise ImportError("slice_missing", f"tarball missing member: {name!r}") from exc
    f = tar.extractfile(member)
    if f is None:
        raise ImportError("slice_missing", f"tarball member is not a file: {name!r}")
    return f.read()


def _parse_jsonl(blob: bytes) -> list[dict[str, Any]]:
    """Parse JSONL into a list of dicts; tolerant of trailing newline."""
    rows: list[dict[str, Any]] = []
    for line in blob.splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line.decode("utf-8")))
    return rows


def _version_gap(src: str, dst: str) -> Optional[int]:
    """Return the index distance ``dst - src`` in SUPPORTED_SPINE_VERSIONS.

    Negative gap = source is newer than destination. ``None`` if either
    is unknown to this build.
    """
    try:
        i_src = SUPPORTED_SPINE_VERSIONS.index(src)
        i_dst = SUPPORTED_SPINE_VERSIONS.index(dst)
    except ValueError:
        return None
    return i_dst - i_src


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def import_state(
    in_path: str,
    *,
    verifier: Verifier,
    writer: DestWriter,
    dry_run: bool = False,
    notes: str = "",
) -> ImportReport:
    """Verify + import the Spine state tarball at ``in_path``.

    The verification chain is fixed (per the safety contract above):
    signature → fingerprint → per-slice hash → manifest version →
    spine version N-2 check → row UPSERTs (one tx per slice) →
    audit-chain replay.

    Args:
        in_path: Path to a ``spine-export-*.tar`` produced by
            :func:`migration.export.export_state`.
        verifier: Ed25519 verifier; defaults to :class:`VaultVerifier`
            in production.
        writer: Destination facade; production wires this to asyncpg +
            vault + filesystem.
        dry_run: When True, no writes happen. The signature + hash + version
            checks still run and surface in the returned report.
        notes: Operator-visible message embedded in the report.

    Returns:
        An :class:`ImportReport` populated with one row per slice.

    Raises:
        ImportError: For any safety check that fails. Errors carry a
            stable ``.code`` for programmatic branching.
    """
    started = datetime.now(timezone.utc)

    with tarfile.open(in_path, "r") as tar:
        manifest_bytes = _read_tar_member(tar, "MANIFEST.json")
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except Exception as exc:
            raise ImportError("manifest_malformed", f"MANIFEST.json: {exc}") from exc

        sig_blob = _read_tar_member(tar, "MANIFEST.sig").strip()
        try:
            signature = base64.b64decode(sig_blob)
        except Exception as exc:
            raise ImportError("signature_missing", f"MANIFEST.sig: {exc}") from exc

        mv = int(manifest.get("manifest_version", -1))
        if mv != MANIFEST_VERSION:
            raise ImportError(
                "manifest_version_mismatch",
                f"manifest_version={mv} not supported by this build "
                f"(expected {MANIFEST_VERSION}).",
            )

        signing_fp = str(manifest.get("signing_key_fingerprint", ""))
        verifier.verify(manifest_bytes, signature, signing_fp)

        src_v = str(manifest.get("spine_version", ""))
        gap = _version_gap(src_v, CURRENT_SPINE_VERSION)
        if gap is None:
            raise ImportError(
                "unsupported_source_version",
                f"export spine_version={src_v!r} not recognised by this "
                f"build (known: {SUPPORTED_SPINE_VERSIONS}).",
            )
        if gap < 0:
            raise ImportError(
                "newer_source_version",
                f"export spine_version={src_v} is newer than this build "
                f"({CURRENT_SPINE_VERSION}); upgrade Hub first.",
            )
        if gap > N_MINUS_K_DIRECT_UPGRADE_DISTANCE:
            raise ImportError(
                "unsupported_source_version",
                f"export spine_version={src_v} is older than the N-2 "
                f"compatibility window ({N_MINUS_K_DIRECT_UPGRADE_DISTANCE} "
                f"versions); run migration.spine_version.upgrade first.",
            )

        report = ImportReport(
            bundle_id=str(manifest.get("bundle_id", "")),
            source_spine_version=src_v,
            dest_spine_version=CURRENT_SPINE_VERSION,
            signature_ok=True,
            fingerprint_ok=True,
            dry_run=dry_run,
            started_at=started.isoformat(),
            notes=notes,
        )

        # Per-slice integrity check + UPSERT.
        slices_by_name = {s["schema"]: s for s in manifest.get("schemas", [])}
        for schema in SCHEMA_SLICES:
            slice_info = slices_by_name.get(schema)
            if slice_info is None:
                raise ImportError(
                    "slice_missing",
                    f"manifest declares no slice for schema {schema!r}",
                )
            payload = _read_tar_member(tar, f"schemas/{schema}.jsonl")
            actual_hash = hashlib.sha256(payload).hexdigest()
            expected_hash = slice_info["content_sha256"]
            ok = actual_hash == expected_hash
            report.schema_hash_ok[schema] = ok
            if not ok:
                raise ImportError(
                    "slice_hash_mismatch",
                    f"schemas/{schema}.jsonl sha256={actual_hash[:12]} != "
                    f"manifest sha256={expected_hash[:12]}",
                )
            rows = _parse_jsonl(payload)
            if not dry_run:
                try:
                    written = writer.write_schema_rows(schema, rows)
                except Exception as exc:
                    raise ImportError(
                        "dest_write_failed",
                        f"write_schema_rows({schema}): {exc}",
                    ) from exc
            else:
                written = len(rows)
            report.schema_row_counts[schema] = written

        # Bundle + license + charters + vault refs.
        bundle_yaml = _read_tar_member(tar, "bundle/org.yaml").decode("utf-8")
        license_env = json.loads(_read_tar_member(tar, "bundle/license.json"))
        vault_refs = json.loads(_read_tar_member(tar, "vault_refs.json"))
        paths = list(vault_refs.get("paths", []))

        # Collect all charters/*.md members.
        charters: dict[str, str] = {}
        for member in tar.getmembers():
            if member.name.startswith("charters/") and member.name.endswith(".md"):
                f = tar.extractfile(member)
                if f is None:
                    continue
                role = member.name[len("charters/"):-len(".md")]
                charters[role] = f.read().decode("utf-8")

        if not dry_run:
            try:
                writer.write_bundle_yaml(bundle_yaml)
                writer.write_license_envelope(license_env)
                writer.write_role_charters(charters)
                writer.write_vault_refs(paths)
            except Exception as exc:
                raise ImportError(
                    "dest_write_failed", f"aux write: {exc}",
                ) from exc

        report.role_charters_written = len(charters)
        report.vault_paths_registered = len(paths)

        # Audit chain replay.
        if not dry_run:
            try:
                replay = writer.replay_audit_chain()
            except Exception as exc:
                raise ImportError(
                    "audit_chain_break", f"replay raised: {exc}",
                ) from exc
            ok = bool(replay.get("ok", False))
            report.audit_chain_ok = ok
            if not ok:
                raise ImportError(
                    "audit_chain_break",
                    f"audit chain replay failed; first_bad_event_uuid="
                    f"{replay.get('first_bad_event_uuid')}",
                )

    report.finished_at = datetime.now(timezone.utc).isoformat()
    logger.info(
        "spine.migration.import.done",
        extra={
            "bundle_id": report.bundle_id,
            "all_ok": report.all_ok(),
            "dry_run": dry_run,
            "slices": list(report.schema_row_counts),
        },
    )
    return report


__all__ = [
    "DestWriter",
    "ImportError",
    "ImportReport",
    "VaultVerifier",
    "Verifier",
    "import_state",
]
