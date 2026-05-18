"""Shared fixtures for ``license.tests``.

* ``vendor_keypair`` — generates a fresh Ed25519 keypair for the test;
  pokes the public key fingerprint into ``TRUSTED_VENDOR_FINGERPRINT``
  so signature verification accepts our test signatures.
* ``signed_payload`` — convenience factory returning a
  ``SignedLicenseBundle`` envelope ready to feed to ``verify_signature``.
* ``mock_pool`` — tiny asyncpg-shaped mock so the quota-ledger /
  feature-flags DB code paths exercise without a live Postgres.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from license import bundle_verifier, feature_flags
from shared.schemas.license import (
    FeatureFlag,
    LicenseBundlePayload,
    SignedLicenseBundle,
)


# ---------------------------------------------------------------------------
# Vendor keypair fixture
# ---------------------------------------------------------------------------


@dataclass
class _Keypair:
    private: Ed25519PrivateKey
    public_bytes: bytes
    fingerprint: str


@pytest.fixture
def vendor_keypair(monkeypatch) -> _Keypair:
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    fp = hashlib.sha256(pub_bytes).hexdigest()
    monkeypatch.setattr(bundle_verifier, "TRUSTED_VENDOR_FINGERPRINT", fp,
                        raising=False)
    return _Keypair(private=priv, public_bytes=pub_bytes, fingerprint=fp)


# ---------------------------------------------------------------------------
# Signed-payload factory
# ---------------------------------------------------------------------------


@pytest.fixture
def make_signed():
    """Return a callable ``(payload=None, key=None) -> SignedLicenseBundle``.

    Default payload is a "team" tier bundle with three known flags
    (``federation`` enabled, ``role_devops`` enabled with quota=100,
    ``role_customer_support`` disabled).
    """

    def _factory(
        *,
        payload: Optional[LicenseBundlePayload] = None,
        key: Optional[Ed25519PrivateKey] = None,
        fingerprint: Optional[str] = None,
    ) -> SignedLicenseBundle:
        if payload is None:
            payload = LicenseBundlePayload(
                customer="test-customer",
                tier="team",
                bundle_id="bundle-test-001",
                issued_at=datetime.now(timezone.utc),
                expires_at=None,
                feature_flags=[
                    FeatureFlag(flag_name="federation", enabled=True),
                    FeatureFlag(flag_name="role_devops", enabled=True,
                                quota_value=100, quota_unit="agents_per_month"),
                    FeatureFlag(flag_name="role_customer_support", enabled=False),
                ],
            )
        if key is None:
            key = Ed25519PrivateKey.generate()
            pub = key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            fingerprint = fingerprint or hashlib.sha256(pub).hexdigest()
        canon = bundle_verifier.canonicalise(payload)
        sig = key.sign(canon)
        return SignedLicenseBundle(
            payload_canonical_b64=base64.b64encode(canon).decode("ascii"),
            signature_b64=base64.b64encode(sig).decode("ascii"),
            signing_key_fingerprint=(fingerprint or "0" * 64).lower(),
        )

    return _factory


# ---------------------------------------------------------------------------
# Mock asyncpg pool
# ---------------------------------------------------------------------------


class _Row(dict):
    """asyncpg ``Record``-ish: dict-shaped row with ``.values()``."""

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return super().get(key, default)


@dataclass
class _MockConn:
    pool: "_MockPool"

    async def fetchrow(self, sql: str, *args: Any) -> Optional[_Row]:
        self.pool.queries.append((sql, args))
        return self.pool.next_row()

    async def fetch(self, sql: str, *args: Any) -> list[_Row]:
        self.pool.queries.append((sql, args))
        return self.pool.next_rows()

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.pool.queries.append((sql, args))
        rows = self.pool.next_rows()
        if not rows:
            return None
        first = rows[0]
        for v in first.values():
            return v
        return None

    async def execute(self, sql: str, *args: Any) -> str:
        self.pool.queries.append((sql, args))
        self.pool.executes.append((sql, args))
        return "OK"


class _AcquireCtx:
    def __init__(self, pool: "_MockPool") -> None:
        self.pool = pool

    async def __aenter__(self) -> _MockConn:
        return _MockConn(self.pool)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@dataclass
class _MockPool:
    queries: list[tuple] = field(default_factory=list)
    executes: list[tuple] = field(default_factory=list)
    _row_scripts: list[Optional[_Row]] = field(default_factory=list)
    _rows_scripts: list[list[_Row]] = field(default_factory=list)

    def script_row(self, row: Optional[dict]) -> None:
        self._row_scripts.append(_Row(row) if row is not None else None)

    def script_rows(self, rows: list[dict]) -> None:
        self._rows_scripts.append([_Row(r) for r in rows])

    def next_row(self) -> Optional[_Row]:
        if self._row_scripts:
            return self._row_scripts.pop(0)
        return None

    def next_rows(self) -> list[_Row]:
        if self._rows_scripts:
            return self._rows_scripts.pop(0)
        return []

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self)


@pytest.fixture
def mock_pool() -> Iterator[_MockPool]:
    pool = _MockPool()
    feature_flags.set_pool(pool)
    try:
        yield pool
    finally:
        feature_flags.set_pool(None)


@pytest.fixture(autouse=True)
def _reset_active_bundle() -> Iterator[None]:
    """Each test starts with a clean licence cache."""
    bundle_verifier.set_active_bundle(None)
    feature_flags.invalidate_cache()
    yield
    bundle_verifier.set_active_bundle(None)
    feature_flags.invalidate_cache()
