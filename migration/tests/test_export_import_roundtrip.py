"""Tests for ``migration.export`` + ``migration.import_``.

Most importantly: **byte-identical round-trip** per #33 B. ``export A
-> import B -> export B`` must produce a tarball that is bit-for-bit
equal to the first export.
"""

from __future__ import annotations

import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from migration.export import (
    EXPORT_FILENAME_PREFIX,
    SCHEMA_SLICES,
    ExportManifest,
    MANIFEST_VERSION,
    export_state,
)
from migration.import_ import ImportError as MIE, import_state


# ---------------------------------------------------------------------------
# Export basics
# ---------------------------------------------------------------------------


def test_export_writes_signed_manifest_and_12_slices(
    tmp_path: Path, mock_reader, mock_signer,
) -> None:
    out = tmp_path / "spine-export-test-001.tar"
    when = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)

    manifest = export_state(
        str(out), reader=mock_reader, signer=mock_signer,
        bundle_id="test-001", when=when,
    )

    assert isinstance(manifest, ExportManifest)
    assert manifest.manifest_version == MANIFEST_VERSION
    assert manifest.bundle_id == "test-001"
    assert manifest.generated_at == when.isoformat()
    assert manifest.signing_key_fingerprint == mock_signer.fingerprint()
    assert {s.schema for s in manifest.schemas} == set(SCHEMA_SLICES)
    # Each row has 2 rows in the mock reader.
    for slice_ in manifest.schemas:
        assert slice_.row_count == 2

    with tarfile.open(out, "r") as tar:
        names = set(tar.getnames())
    assert "MANIFEST.json" in names
    assert "MANIFEST.sig" in names
    for s in SCHEMA_SLICES:
        assert f"schemas/{s}.jsonl" in names
    assert "bundle/org.yaml" in names
    assert "bundle/license.json" in names
    assert "vault_refs.json" in names
    assert "audit_chain_integrity.json" in names
    assert "charters/architect.md" in names
    assert "charters/engineer.md" in names


def test_export_filename_convention_prefix() -> None:
    assert EXPORT_FILENAME_PREFIX == "spine-export-"


# ---------------------------------------------------------------------------
# Round-trip determinism  —  the marquee #33 B property
# ---------------------------------------------------------------------------


def test_export_is_deterministic_for_fixed_when(
    tmp_path: Path, mock_reader, mock_signer,
) -> None:
    """Two exports with the same ``when`` produce byte-identical tarballs.

    This is the foundation of #33 B's round-trip claim: if export is
    deterministic, then export-import-export-compare is a meaningful
    test.
    """
    when = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    a = tmp_path / "spine-export-a.tar"
    b = tmp_path / "spine-export-b.tar"

    export_state(str(a), reader=mock_reader, signer=mock_signer,
                 bundle_id="round-trip", when=when)
    export_state(str(b), reader=mock_reader, signer=mock_signer,
                 bundle_id="round-trip", when=when)

    assert a.read_bytes() == b.read_bytes()


def test_export_import_export_roundtrip_bytes_equal(
    tmp_path: Path, mock_reader, mock_signer, mock_verifier, mock_writer,
) -> None:
    """The full round-trip from #33 B.

    1. export(A) -> tarball A
    2. import(A) into Hub B (mock_writer is the destination)
    3. construct a reader over Hub B's state
    4. export(B) -> tarball B
    5. assert tarball A == tarball B byte-for-byte
    """
    when = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)

    a_path = tmp_path / "spine-export-A.tar"
    export_state(str(a_path), reader=mock_reader, signer=mock_signer,
                 bundle_id="rt", when=when)

    # Import A into mock_writer.
    report = import_state(str(a_path), verifier=mock_verifier, writer=mock_writer)
    assert report.all_ok()

    # Build a reader-over-the-writer.
    from migration.tests.conftest import InMemoryReader
    reader_b = InMemoryReader(
        schema_rows=mock_writer.written_rows,
        bundle_yaml=mock_writer.bundle_yaml or "",
        license_envelope=mock_writer.license_envelope or {},
        role_charters=mock_writer.role_charters,
        vault_refs=mock_writer.vault_paths,
        audit_integrity=mock_reader.audit_integrity,  # round-trip the verdict
    )

    b_path = tmp_path / "spine-export-B.tar"
    export_state(str(b_path), reader=reader_b, signer=mock_signer,
                 bundle_id="rt", when=when)

    assert a_path.read_bytes() == b_path.read_bytes(), (
        "Round-trip byte equality (#33 B) failed; export/import/export "
        "produced different tarballs."
    )


# ---------------------------------------------------------------------------
# Manifest content
# ---------------------------------------------------------------------------


def test_manifest_canonicalisation_sorts_keys(
    tmp_path: Path, mock_reader, mock_signer,
) -> None:
    when = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    out = tmp_path / "out.tar"
    export_state(str(out), reader=mock_reader, signer=mock_signer,
                 bundle_id="canon", when=when)
    with tarfile.open(out, "r") as tar:
        manifest_bytes = tar.extractfile("MANIFEST.json").read()  # type: ignore[union-attr]
    # Sorted-keys -> re-parsing + re-encoding with sort_keys produces the
    # same bytes.
    parsed = json.loads(manifest_bytes)
    re_emitted = json.dumps(parsed, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False).encode("utf-8")
    assert manifest_bytes == re_emitted


# ---------------------------------------------------------------------------
# Import safety checks
# ---------------------------------------------------------------------------


def test_import_rejects_bad_signature(
    tmp_path: Path, mock_reader, mock_signer, mock_writer, keypair,
) -> None:
    out = tmp_path / "out.tar"
    export_state(str(out), reader=mock_reader, signer=mock_signer,
                 bundle_id="rt", when=datetime(2026, 5, 17, tzinfo=timezone.utc))

    # Construct a verifier rooted in a DIFFERENT keypair.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import hashlib as _h

    other_priv = Ed25519PrivateKey.generate()
    other_pub = other_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    from migration.tests.conftest import _Keypair, InMemoryVerifier
    bad_verifier = InMemoryVerifier(_Keypair(
        private=other_priv, public_bytes=other_pub,
        fingerprint=_h.sha256(other_pub).hexdigest(),
    ))

    with pytest.raises(MIE) as exc_info:
        import_state(str(out), verifier=bad_verifier, writer=mock_writer)
    assert exc_info.value.code == "fingerprint_mismatch"


def test_import_rejects_hash_tampering(
    tmp_path: Path, mock_reader, mock_signer, mock_verifier, mock_writer,
) -> None:
    """Manually rewrite a slice file inside the tarball; import must refuse."""
    import io

    out = tmp_path / "out.tar"
    export_state(str(out), reader=mock_reader, signer=mock_signer,
                 bundle_id="rt", when=datetime(2026, 5, 17, tzinfo=timezone.utc))

    # Read the original tar, rewrite one slice payload with garbage, write back.
    with tarfile.open(out, "r") as src:
        members = src.getmembers()
        bodies = {m.name: src.extractfile(m).read() if m.isfile() else b""
                  for m in members}
    bodies["schemas/spine_audit.jsonl"] = b'{"id":"tampered"}\n'
    out2 = tmp_path / "out_tampered.tar"
    with tarfile.open(out2, "w", format=tarfile.PAX_FORMAT) as dst:
        for m in members:
            payload = bodies[m.name]
            info = tarfile.TarInfo(name=m.name)
            info.size = len(payload)
            info.mtime = m.mtime
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            dst.addfile(info, io.BytesIO(payload))

    with pytest.raises(MIE) as exc_info:
        import_state(str(out2), verifier=mock_verifier, writer=mock_writer)
    assert exc_info.value.code == "slice_hash_mismatch"


def test_import_is_idempotent_under_rerun(
    tmp_path: Path, mock_reader, mock_signer, mock_verifier, mock_writer,
) -> None:
    out = tmp_path / "out.tar"
    export_state(str(out), reader=mock_reader, signer=mock_signer,
                 bundle_id="rt", when=datetime(2026, 5, 17, tzinfo=timezone.utc))
    r1 = import_state(str(out), verifier=mock_verifier, writer=mock_writer)
    r2 = import_state(str(out), verifier=mock_verifier, writer=mock_writer)
    assert r1.all_ok() and r2.all_ok()
    # Same row counts on the second run -> writer's UPSERT didn't double-count.
    for s in SCHEMA_SLICES:
        assert len(mock_writer.written_rows[s]) == 2


def test_import_dry_run_does_not_write(
    tmp_path: Path, mock_reader, mock_signer, mock_verifier, mock_writer,
) -> None:
    out = tmp_path / "out.tar"
    export_state(str(out), reader=mock_reader, signer=mock_signer,
                 bundle_id="rt", when=datetime(2026, 5, 17, tzinfo=timezone.utc))
    report = import_state(str(out), verifier=mock_verifier, writer=mock_writer,
                          dry_run=True)
    assert report.dry_run is True
    assert mock_writer.written_rows == {}
    assert mock_writer.bundle_yaml is None
