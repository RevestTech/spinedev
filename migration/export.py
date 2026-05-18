"""Full Spine state export — design decision #33 B (Spine portability).

Produces a **signed, integrity-verified tarball** containing every piece
of persistent state owned by a Spine Hub. The output is the architectural
realisation of the "no lock-in" promise: any Spine deployment can be
moved between shapes (laptop → BYOC → on-prem) or between clouds
(AWS → GCP) without losing audit chain, KG, role charters, bundle
config, vault references, memory, lessons, or project history.

Tarball layout (deterministic; required for round-trip byte equality)::

    spine-export-<bundle_id>.tar
    ├── MANIFEST.json                 — version + slice index + content hashes
    ├── MANIFEST.sig                  — Ed25519 signature over MANIFEST.json
    ├── schemas/
    │   ├── spine_lifecycle.jsonl
    │   ├── spine_audit.jsonl
    │   ├── spine_kg.jsonl
    │   ├── spine_memory.jsonl
    │   ├── spine_federation.jsonl
    │   ├── spine_evidence.jsonl
    │   ├── spine_learning.jsonl
    │   ├── spine_devops.jsonl
    │   ├── spine_license.jsonl
    │   ├── spine_workitem.jsonl
    │   ├── spine_hub.jsonl
    │   └── spine_identity.jsonl
    ├── bundle/
    │   ├── org.yaml                  — active org-policy bundle
    │   └── license.json              — active license bundle envelope
    ├── charters/
    │   └── <role>.md                 — every role charter under shared/charters/
    ├── vault_refs.json               — vault PATHS only; never the secret VALUES
    └── audit_chain_integrity.json    — replay verdict produced at export time

Determinism rules (for byte-identical round-trip):

* JSONL rows are sorted by primary key within each slice.
* JSON objects emit keys in sorted order, no whitespace, UTF-8.
* tarinfo mtime is **frozen** to the manifest ``generated_at`` value.
* tarinfo uid/gid/uname/gname are zeroed.
* Manifest carries ``content_sha256`` per slice file; consumers can
  verify each slice independently of the signature.

Signing:

The signature covers the canonical bytes of ``MANIFEST.json``. The key
is loaded via :mod:`shared.secrets` at the vault path
``license/vendor_signing_key`` (the same Ed25519 key used by
``tools/license-sign.sh``; see ``ADR-F-002`` in ``README.md`` for the
rationale of re-using vs minting a distinct migration key).
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

from migration.version_registry import (
    CURRENT_SPINE_VERSION,
    SUBSYSTEM_VERSIONS,
    SubsystemVersion,
)

logger = logging.getLogger("spine.migration.export")

#: Wire-format version of the export manifest. Bumped on incompatible
#: changes to the tarball layout or MANIFEST.json shape. The importer
#: refuses ``manifest_version`` values it does not recognise.
MANIFEST_VERSION: int = 1

#: Stable filename prefix; the importer accepts any ``spine-export-*.tar``.
EXPORT_FILENAME_PREFIX: str = "spine-export-"

#: The 12 DB schema slices listed in the task brief (#33 B).
SCHEMA_SLICES: tuple[str, ...] = (
    "spine_lifecycle",
    "spine_audit",
    "spine_kg",
    "spine_memory",
    "spine_federation",
    "spine_evidence",
    "spine_learning",
    "spine_devops",
    "spine_license",
    "spine_workitem",
    "spine_hub",
    "spine_identity",
)


# ---------------------------------------------------------------------------
# Public protocols & dataclasses
# ---------------------------------------------------------------------------


class Signer(Protocol):
    """Ed25519 signer interface.

    Implementations must:

    * Source the private key via :mod:`shared.secrets` (per #9).
    * Return raw 64-byte Ed25519 signature bytes for the supplied digest.
    * NEVER expose the private key material to the caller.

    The default :class:`VaultSigner` below satisfies all three.
    """

    def fingerprint(self) -> str:
        """Hex SHA-256 of the public key (the Hub's trust anchor)."""
        ...

    def sign(self, message: bytes) -> bytes:
        """Return the Ed25519 signature over ``message``."""
        ...


class StateReader(Protocol):
    """Reads persistent state for an export run.

    Real implementation reads from asyncpg pool + filesystem; tests
    inject a mock that returns canned slices. Either way, the contract
    is: every method is synchronous (we wrap async DB calls in the
    runtime adapter), every method returns deterministically-ordered
    rows, and side-effects are read-only.
    """

    def fetch_schema_rows(self, schema: str) -> list[dict[str, Any]]:
        """Return all rows for the named DB schema, sorted by primary key."""
        ...

    def fetch_active_bundle_yaml(self) -> str:
        """Return the active org-policy bundle as YAML text."""
        ...

    def fetch_active_license_envelope(self) -> dict[str, Any]:
        """Return the active license bundle envelope as a dict.

        Vault PATH only; the signed payload itself is included so
        downstream Hubs can re-verify the signature.
        """
        ...

    def fetch_role_charters(self) -> dict[str, str]:
        """Return ``{role_name: charter_markdown}``."""
        ...

    def fetch_vault_refs(self) -> list[str]:
        """Return vault PATHS used by this deployment.

        Per #9, only the references travel; the secret values stay in
        the source vault. The receiving deployment must populate its
        own vault before activating the bundle.
        """
        ...

    def fetch_audit_chain_integrity_report(self) -> dict[str, Any]:
        """Return the audit-chain replay verdict snapshot.

        Shape::

            {
              "ok": bool,
              "rows_verified": int,
              "first_bad_event_uuid": str | None,
              "verified_at": iso8601,
              "chain_tip_hash": hex,
            }
        """
        ...


@dataclass(frozen=True)
class ExportSchemaSlice:
    """Index entry for one DB schema slice inside the manifest."""

    schema: str
    row_count: int
    content_sha256: str
    bytes_size: int


@dataclass(frozen=True)
class ExportManifest:
    """The signed manifest that anchors an export tarball.

    Wire format (post-canonicalisation) is JSON with sorted keys + no
    whitespace, so the signature covers a deterministic byte sequence.
    """

    manifest_version: int
    spine_version: str
    bundle_id: str
    generated_at: str  # ISO-8601 UTC
    schemas: tuple[ExportSchemaSlice, ...]
    auxiliary_files: tuple[tuple[str, str], ...]  # (relpath, content_sha256)
    subsystem_versions: tuple[SubsystemVersion, ...]
    signing_key_fingerprint: str
    source_hub_id: Optional[str] = None
    notes: str = ""

    def to_canonical_bytes(self) -> bytes:
        """Return the canonical UTF-8 bytes for signing.

        Sorted keys + no whitespace + JSON-compatible primitives. The
        importer recomputes this from the same inputs and verifies the
        signature against these bytes.
        """
        return _canonical_json(_manifest_to_dict(self))


# ---------------------------------------------------------------------------
# VaultSigner — reuses the license signing key per ADR-F-002
# ---------------------------------------------------------------------------


#: Vault path for the migration signing key. Defaults to the same path
#: ``tools/license-sign.sh`` uses; override via constructor for vendors
#: that want a distinct migration key.
DEFAULT_SIGNING_VAULT_PATH: str = "license/vendor_signing_key"


class VaultSigner:
    """Ed25519 signer that loads its private key from the vault on demand.

    Per #9 (vault-only secrets) + ADR-F-002 (reuse the license signing
    key), this signer never persists the private key, never accepts it
    via constructor, and refuses to hand it back to the caller.

    Construction validates that :mod:`cryptography` is importable and
    that the supplied secret loader is awaitable; actual vault access
    is deferred until :meth:`sign` is called so test code can avoid
    bootstrapping a real Vault.
    """

    def __init__(
        self,
        *,
        vault_path: str = DEFAULT_SIGNING_VAULT_PATH,
        secret_loader: Optional[Callable[[str], Awaitable[str]]] = None,
    ) -> None:
        try:  # pragma: no cover — exercised in tests via the dep-injected loader
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )

            self._Ed25519PrivateKey = Ed25519PrivateKey
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "cryptography is required for VaultSigner; install it as a "
                "runtime dep of the migration subsystem.",
            ) from exc
        self._vault_path = vault_path
        self._secret_loader = secret_loader
        self._cached_fp: Optional[str] = None

    def _load_key(self) -> Any:
        """Synchronously fetch + parse the Ed25519 private key.

        Uses :mod:`asyncio` to drive the async vault adapter, or the
        injected ``secret_loader`` if supplied. NEVER caches the key —
        each :meth:`sign` call re-derives it so a key rotation between
        signs is picked up on the very next call.
        """
        import asyncio

        loader = self._secret_loader
        if loader is None:
            from shared.secrets import get_secret as _get

            loader = _get  # type: ignore[assignment]

        coro = loader(self._vault_path)
        try:
            raw_b64 = asyncio.run(coro)
        except RuntimeError:
            # Already inside an event loop — synchronously drain via a
            # dedicated loop. Tests rarely hit this path.
            loop = asyncio.new_event_loop()
            try:
                raw_b64 = loop.run_until_complete(coro)
            finally:
                loop.close()
        raw = base64.b64decode(raw_b64.encode("ascii"))
        return self._Ed25519PrivateKey.from_private_bytes(raw)

    def fingerprint(self) -> str:
        """Return + cache the public-key SHA-256 fingerprint."""
        if self._cached_fp is not None:
            return self._cached_fp
        from cryptography.hazmat.primitives import serialization

        priv = self._load_key()
        pub = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        fp = hashlib.sha256(pub).hexdigest()
        self._cached_fp = fp
        return fp

    def sign(self, message: bytes) -> bytes:
        priv = self._load_key()
        return priv.sign(message)


# ---------------------------------------------------------------------------
# Canonicalisation helpers
# ---------------------------------------------------------------------------


def _canonical_json(obj: Any) -> bytes:
    """Sorted-keys, no-whitespace, UTF-8 JSON. Required for sig stability."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=_canon_default,
    ).encode("utf-8")


def _canon_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.astimezone(timezone.utc).isoformat()
    if isinstance(o, bytes):
        return base64.b64encode(o).decode("ascii")
    raise TypeError(f"Unserialisable: {type(o)!r}")


def _sha256_hex(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _subsystem_to_dict(s: SubsystemVersion) -> dict[str, Any]:
    return {
        "subsystem": s.subsystem,
        "schema_kind": s.schema_kind,
        "current_version": s.current_version,
        "min_supported_version": s.min_supported_version,
        "owner_module": s.owner_module,
        "notes": s.notes,
    }


def _slice_to_dict(s: ExportSchemaSlice) -> dict[str, Any]:
    return {
        "schema": s.schema,
        "row_count": s.row_count,
        "content_sha256": s.content_sha256,
        "bytes_size": s.bytes_size,
    }


def _manifest_to_dict(m: ExportManifest) -> dict[str, Any]:
    return {
        "manifest_version": m.manifest_version,
        "spine_version": m.spine_version,
        "bundle_id": m.bundle_id,
        "generated_at": m.generated_at,
        "schemas": [_slice_to_dict(s) for s in m.schemas],
        "auxiliary_files": [list(t) for t in m.auxiliary_files],
        "subsystem_versions": [_subsystem_to_dict(s) for s in m.subsystem_versions],
        "signing_key_fingerprint": m.signing_key_fingerprint,
        "source_hub_id": m.source_hub_id,
        "notes": m.notes,
    }


# ---------------------------------------------------------------------------
# Slice rendering — deterministic JSONL
# ---------------------------------------------------------------------------


def _row_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Sort rows by the first present "id-ish" column, then by all keys.

    The StateReader contract promises rows are pre-sorted, but we re-sort
    defensively so a faulty reader can't break round-trip equality.
    """
    for col in ("event_id", "event_uuid", "id", "node_id", "project_id"):
        if col in row:
            return (str(row[col]),)
    # Fall back to the full canonical JSON — always defined, always stable.
    return (json.dumps(row, sort_keys=True, default=_canon_default),)


def _render_schema_jsonl(rows: list[dict[str, Any]]) -> bytes:
    """Encode rows as deterministic JSONL (one canonical JSON object per line)."""
    sorted_rows = sorted(rows, key=_row_sort_key)
    buf = io.BytesIO()
    for row in sorted_rows:
        buf.write(_canonical_json(row))
        buf.write(b"\n")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@dataclass
class _StagedFile:
    relpath: str
    payload: bytes
    sha256_hex: str = field(default="")

    def __post_init__(self) -> None:
        if not self.sha256_hex:
            self.sha256_hex = _sha256_hex(self.payload)


def _stage_all(reader: StateReader, generated_at: datetime) -> list[_StagedFile]:
    """Build every file (except MANIFEST.json + MANIFEST.sig) for the tarball."""
    staged: list[_StagedFile] = []

    # 12 DB schema slices.
    for schema in SCHEMA_SLICES:
        rows = reader.fetch_schema_rows(schema)
        payload = _render_schema_jsonl(rows)
        staged.append(_StagedFile(f"schemas/{schema}.jsonl", payload))

    # Bundle artifacts.
    bundle_yaml = reader.fetch_active_bundle_yaml()
    staged.append(_StagedFile(
        "bundle/org.yaml", bundle_yaml.encode("utf-8"),
    ))
    license_env = reader.fetch_active_license_envelope()
    staged.append(_StagedFile(
        "bundle/license.json", _canonical_json(license_env),
    ))

    # Role charters — sorted by name so the resulting tarball is stable.
    charters = reader.fetch_role_charters()
    for role in sorted(charters):
        staged.append(_StagedFile(
            f"charters/{role}.md", charters[role].encode("utf-8"),
        ))

    # Vault references (paths only).
    refs = sorted(reader.fetch_vault_refs())
    staged.append(_StagedFile(
        "vault_refs.json", _canonical_json({"paths": refs}),
    ))

    # Audit chain integrity verdict.
    integrity = reader.fetch_audit_chain_integrity_report()
    staged.append(_StagedFile(
        "audit_chain_integrity.json", _canonical_json(integrity),
    ))

    return staged


def _build_manifest(
    *,
    bundle_id: str,
    generated_at: datetime,
    staged: list[_StagedFile],
    signing_fp: str,
    source_hub_id: Optional[str],
    notes: str,
) -> ExportManifest:
    schema_slices: list[ExportSchemaSlice] = []
    aux: list[tuple[str, str]] = []
    for sf in staged:
        if sf.relpath.startswith("schemas/") and sf.relpath.endswith(".jsonl"):
            schema_name = sf.relpath[len("schemas/"):-len(".jsonl")]
            row_count = sf.payload.count(b"\n")
            schema_slices.append(ExportSchemaSlice(
                schema=schema_name,
                row_count=row_count,
                content_sha256=sf.sha256_hex,
                bytes_size=len(sf.payload),
            ))
        else:
            aux.append((sf.relpath, sf.sha256_hex))

    # Schema slices in registry order (#33 B "12 schemas" listing).
    schema_slices.sort(key=lambda s: SCHEMA_SLICES.index(s.schema))
    aux.sort()

    return ExportManifest(
        manifest_version=MANIFEST_VERSION,
        spine_version=CURRENT_SPINE_VERSION,
        bundle_id=bundle_id,
        generated_at=generated_at.astimezone(timezone.utc).isoformat(),
        schemas=tuple(schema_slices),
        auxiliary_files=tuple(aux),
        subsystem_versions=SUBSYSTEM_VERSIONS,
        signing_key_fingerprint=signing_fp,
        source_hub_id=source_hub_id,
        notes=notes,
    )


def _add_tar_member(tar: tarfile.TarFile, relpath: str, payload: bytes, mtime: float) -> None:
    """Add ``payload`` as ``relpath`` to ``tar`` with frozen metadata."""
    info = tarfile.TarInfo(name=relpath)
    info.size = len(payload)
    info.mtime = int(mtime)
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.type = tarfile.REGTYPE
    tar.addfile(info, io.BytesIO(payload))


def export_state(
    out_path: str,
    *,
    reader: StateReader,
    signer: Signer,
    bundle_id: str,
    source_hub_id: Optional[str] = None,
    notes: str = "",
    when: Optional[datetime] = None,
) -> ExportManifest:
    """Write a signed Spine state tarball to ``out_path``.

    Args:
        out_path: Destination path; convention is ``spine-export-<bundle_id>.tar``.
        reader: Synchronous facade over the live state stores. Tests
            inject an in-memory mock; production code uses the asyncpg+
            filesystem-backed reader built by the Hub.
        signer: Ed25519 signer; defaults to :class:`VaultSigner` in
            production (loads from ``license/vendor_signing_key``).
        bundle_id: Unique identifier for this export run. Convention:
            ``<hub_id>-<utc_yyyymmdd_hhmmss>``.
        source_hub_id: Optional Hub identifier for audit attribution.
        notes: Operator-visible message embedded in the manifest.
        when: Override the export wall-clock time (for round-trip tests
            that need byte-identical re-exports).

    Returns:
        The fully populated :class:`ExportManifest` written into the
        tarball. Callers may persist this in their own audit trail.

    Notes:
        * The tar mtime on every member is frozen to ``when`` so two
          exports of the same state at the same ``when`` produce
          byte-identical tarballs (the round-trip guarantee from #33 B).
        * Per #9, only vault PATHS are exported — never values.
    """
    generated_at = when or datetime.now(timezone.utc)
    mtime = generated_at.timestamp()

    logger.info(
        "spine.migration.export.start",
        extra={"bundle_id": bundle_id, "out_path": out_path},
    )

    staged = _stage_all(reader, generated_at)
    signing_fp = signer.fingerprint()
    manifest = _build_manifest(
        bundle_id=bundle_id, generated_at=generated_at, staged=staged,
        signing_fp=signing_fp, source_hub_id=source_hub_id, notes=notes,
    )
    manifest_bytes = manifest.to_canonical_bytes()
    signature = signer.sign(manifest_bytes)
    sig_bytes = base64.b64encode(signature) + b"\n"

    # `tarfile.open(out_path, "w")` writes an uncompressed tar — required
    # so the byte-level diff is the same whether the file ends up gzipped
    # downstream or not. Compression is a transport concern, not a
    # canonicalisation concern.
    with tarfile.open(out_path, "w", format=tarfile.PAX_FORMAT) as tar:
        _add_tar_member(tar, "MANIFEST.json", manifest_bytes, mtime)
        _add_tar_member(tar, "MANIFEST.sig", sig_bytes, mtime)
        # Sort staged files by relpath so member order is deterministic.
        for sf in sorted(staged, key=lambda s: s.relpath):
            _add_tar_member(tar, sf.relpath, sf.payload, mtime)

    logger.info(
        "spine.migration.export.done",
        extra={
            "bundle_id": bundle_id,
            "out_path": out_path,
            "schema_slices": len(manifest.schemas),
            "aux_files": len(manifest.auxiliary_files),
            "signing_fp": signing_fp,
        },
    )
    return manifest


__all__ = [
    "DEFAULT_SIGNING_VAULT_PATH",
    "EXPORT_FILENAME_PREFIX",
    "ExportManifest",
    "ExportSchemaSlice",
    "MANIFEST_VERSION",
    "SCHEMA_SLICES",
    "Signer",
    "StateReader",
    "VaultSigner",
    "export_state",
]
