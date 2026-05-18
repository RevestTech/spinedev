"""Shared fixtures for ``migration.tests`` (Wave 5 Squad F).

Every fixture is in-memory; no Postgres / Vault / GitHub / Linear is
contacted. Per ADR-F-003 in ``migration/README.md``.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import pytest

# These imports are at module scope so the test collection errors out
# loudly if the subsystem under test fails to import.
from migration.export import (
    SCHEMA_SLICES,
    Signer,
    StateReader,
)
from migration.import_ import DestWriter, Verifier
from migration.onboarding import HttpClient, WorkItemMapping, WorkItemSink


# ---------------------------------------------------------------------------
# Ed25519 keypair  —  one fixture; the same keypair is shared by both
# ---------------------------------------------------------------------------


@dataclass
class _Keypair:
    private: Any
    public_bytes: bytes
    fingerprint: str


@pytest.fixture
def keypair() -> _Keypair:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return _Keypair(
        private=priv, public_bytes=pub,
        fingerprint=hashlib.sha256(pub).hexdigest(),
    )


# ---------------------------------------------------------------------------
# In-memory Signer / Verifier
# ---------------------------------------------------------------------------


@dataclass
class InMemorySigner:
    keypair: _Keypair

    def fingerprint(self) -> str:
        return self.keypair.fingerprint

    def sign(self, message: bytes) -> bytes:
        return self.keypair.private.sign(message)


@dataclass
class InMemoryVerifier:
    keypair: _Keypair

    def expected_fingerprint(self) -> str:
        return self.keypair.fingerprint

    def verify(self, message: bytes, signature: bytes, fingerprint: str) -> None:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        from migration.import_ import ImportError as MIE

        if fingerprint.lower() != self.keypair.fingerprint:
            raise MIE("fingerprint_mismatch", "bad fp")
        try:
            Ed25519PublicKey.from_public_bytes(self.keypair.public_bytes).verify(
                signature, message,
            )
        except InvalidSignature as exc:
            raise MIE("signature_invalid", "bad sig") from exc


@pytest.fixture
def mock_signer(keypair) -> InMemorySigner:
    return InMemorySigner(keypair)


@pytest.fixture
def mock_verifier(keypair) -> InMemoryVerifier:
    return InMemoryVerifier(keypair)


# ---------------------------------------------------------------------------
# StateReader mock  —  emits 12 deterministic schema slices
# ---------------------------------------------------------------------------


@dataclass
class InMemoryReader:
    schema_rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    bundle_yaml: str = ""
    license_envelope: dict[str, Any] = field(default_factory=dict)
    role_charters: dict[str, str] = field(default_factory=dict)
    vault_refs: list[str] = field(default_factory=list)
    audit_integrity: dict[str, Any] = field(default_factory=dict)

    def fetch_schema_rows(self, schema: str) -> list[dict[str, Any]]:
        return list(self.schema_rows.get(schema, []))

    def fetch_active_bundle_yaml(self) -> str:
        return self.bundle_yaml

    def fetch_active_license_envelope(self) -> dict[str, Any]:
        return dict(self.license_envelope)

    def fetch_role_charters(self) -> dict[str, str]:
        return dict(self.role_charters)

    def fetch_vault_refs(self) -> list[str]:
        return list(self.vault_refs)

    def fetch_audit_chain_integrity_report(self) -> dict[str, Any]:
        return dict(self.audit_integrity)


@pytest.fixture
def mock_reader() -> InMemoryReader:
    reader = InMemoryReader(
        schema_rows={
            s: [
                {"id": f"{s}-1", "name": f"row-1 in {s}", "value": 1},
                {"id": f"{s}-2", "name": f"row-2 in {s}", "value": 2},
            ]
            for s in SCHEMA_SLICES
        },
        bundle_yaml="federation:\n  pipeline:\n    phases: []\n",
        license_envelope={
            "payload_canonical_b64": "Zm9v",
            "signature_b64": "YmFy",
            "signing_key_fingerprint": "0" * 64,
        },
        role_charters={
            "architect": "# Architect charter\n\nPMBOK anchor.\n",
            "engineer": "# Engineer charter\n\nIEEE anchor.\n",
        },
        vault_refs=[
            "integration/github/acme/token",
            "integration/linear/acme/api_key",
            "license/vendor_pubkey",
        ],
        audit_integrity={
            "ok": True,
            "rows_verified": 42,
            "first_bad_event_uuid": None,
            "verified_at": "2026-05-17T00:00:00+00:00",
            "chain_tip_hash": "a" * 64,
        },
    )
    return reader


# ---------------------------------------------------------------------------
# DestWriter mock  —  records calls; UPSERT semantics
# ---------------------------------------------------------------------------


@dataclass
class InMemoryWriter:
    written_rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    bundle_yaml: Optional[str] = None
    license_envelope: Optional[dict[str, Any]] = None
    role_charters: dict[str, str] = field(default_factory=dict)
    vault_paths: list[str] = field(default_factory=list)
    replay_result: dict[str, Any] = field(default_factory=lambda: {
        "ok": True, "rows_verified": 0, "first_bad_event_uuid": None,
        "verified_at": "2026-05-17T00:00:00+00:00",
        "chain_tip_hash": "b" * 64,
    })

    def write_schema_rows(self, schema: str, rows: list[dict[str, Any]]) -> int:
        # UPSERT-by-id idempotency.
        existing = {r.get("id"): r for r in self.written_rows.get(schema, [])}
        for r in rows:
            existing[r.get("id")] = r
        self.written_rows[schema] = list(existing.values())
        return len(rows)

    def write_bundle_yaml(self, yaml_text: str) -> None:
        self.bundle_yaml = yaml_text

    def write_license_envelope(self, envelope: dict[str, Any]) -> None:
        self.license_envelope = envelope

    def write_role_charters(self, charters: dict[str, str]) -> None:
        self.role_charters.update(charters)

    def write_vault_refs(self, paths: list[str]) -> None:
        self.vault_paths = list(paths)

    def replay_audit_chain(self) -> dict[str, Any]:
        return dict(self.replay_result)


@pytest.fixture
def mock_writer() -> InMemoryWriter:
    return InMemoryWriter()


# ---------------------------------------------------------------------------
# HttpClient mock  —  scripted responses for onboarding connectors
# ---------------------------------------------------------------------------


@dataclass
class ScriptedHttpClient:
    """Maps URL substrings to bodies.

    Two flavours:

    * ``script(sub, body)`` — single-use; first matching call returns it,
      then it pops.
    * ``script_persistent(sub, body)`` — every call matching ``sub``
      returns this body. Useful for endpoints that get re-fetched in a
      single run (e.g. GitHub's ``/orgs/<org>/repos`` is hit by both
      ``import_repos`` and ``import_issues``).

    Scripts are checked in (single-use, then persistent) order so a
    single-use overrides a persistent for the next call.
    """

    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    scripts: list[tuple[str, Any]] = field(default_factory=list)
    persistent_scripts: list[tuple[str, Any]] = field(default_factory=list)

    def script(self, url_substring: str, body: Any) -> None:
        self.scripts.append((url_substring, body))

    def script_persistent(self, url_substring: str, body: Any) -> None:
        self.persistent_scripts.append((url_substring, body))

    def get_json(self, url: str, *, headers: dict[str, str]) -> dict[str, Any]:
        self.calls.append((url, dict(headers)))
        for i, (sub, body) in enumerate(self.scripts):
            if sub in url:
                self.scripts.pop(i)
                return {"status_code": 200, "body": body}
        for sub, body in self.persistent_scripts:
            if sub in url:
                return {"status_code": 200, "body": body}
        return {"status_code": 404, "body": []}


@pytest.fixture
def mock_http() -> ScriptedHttpClient:
    return ScriptedHttpClient()


# ---------------------------------------------------------------------------
# WorkItemSink mock
# ---------------------------------------------------------------------------


@dataclass
class InMemorySink:
    items: list[WorkItemMapping] = field(default_factory=list)

    def upsert_work_items(self, items: list[WorkItemMapping]) -> int:
        self.items.extend(items)
        return len(items)


@pytest.fixture
def mock_sink() -> InMemorySink:
    return InMemorySink()


# ---------------------------------------------------------------------------
# Stub token loader  —  returns a deterministic "secret"
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_token_loader():
    async def _loader(path: str) -> str:
        return f"token-for-{path}"

    return _loader


@pytest.fixture
def stub_key_loader(keypair):
    """Async loader that returns the base64 of the keypair's private bytes."""
    from cryptography.hazmat.primitives import serialization

    raw = keypair.private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    enc = base64.b64encode(raw).decode("ascii")

    async def _loader(path: str) -> str:
        return enc

    return _loader


@pytest.fixture
def stub_pub_loader(keypair):
    """Async loader that returns the base64 of the public-key bytes."""
    enc = base64.b64encode(keypair.public_bytes).decode("ascii")

    async def _loader(path: str) -> str:
        return enc

    return _loader
