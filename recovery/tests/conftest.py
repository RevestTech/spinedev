"""Shared fixtures for ``recovery.tests``.

* ``mock_runner`` — captures argv and returns scripted (rc, stdout, stderr).
* ``mock_secret_fetcher`` — in-memory async lookup keyed by vault path.
* ``mock_pool`` — minimal asyncpg-shaped pool mirroring
  ``license/tests/conftest.py``.
* ``backup_target_file`` — file:// BackupTarget for tests; never hits a
  real cloud.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

import pytest

from recovery.backup import BackupTarget


# ---------------------------------------------------------------------------
# Mock subprocess runner
# ---------------------------------------------------------------------------


@dataclass
class MockRunner:
    calls: list[list[str]] = field(default_factory=list)
    script: list[tuple[int, str, str]] = field(default_factory=list)
    default: tuple[int, str, str] = (0, "", "")

    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        self.calls.append(list(argv))
        if self.script:
            return self.script.pop(0)
        return self.default

    def queue(self, rc: int, stdout: str = "", stderr: str = "") -> None:
        self.script.append((rc, stdout, stderr))


@pytest.fixture
def mock_runner() -> MockRunner:
    return MockRunner()


# ---------------------------------------------------------------------------
# Mock secret fetcher
# ---------------------------------------------------------------------------


@dataclass
class MockSecretFetcher:
    secrets: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    async def __call__(self, path: str) -> str:
        self.calls.append(path)
        if path not in self.secrets:
            raise KeyError(f"no secret at {path!r}")
        return self.secrets[path]


@pytest.fixture
def mock_secret_fetcher() -> MockSecretFetcher:
    return MockSecretFetcher(secrets={
        "recovery/kms/test/key_id": "arn:aws:kms:us-east-1:123:key/test-kms-key",
        "recovery/storage/test/access_key": "AKIATESTTESTTEST",
    })


# ---------------------------------------------------------------------------
# Mock asyncpg pool (adapted from license/tests/conftest.py)
# ---------------------------------------------------------------------------


class _Row(dict):
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
            return self.pool.next_scalar()
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
    _scalar_scripts: list[Any] = field(default_factory=list)

    def script_row(self, row: Optional[dict]) -> None:
        self._row_scripts.append(_Row(row) if row is not None else None)

    def script_rows(self, rows: list[dict]) -> None:
        self._rows_scripts.append([_Row(r) for r in rows])

    def script_scalar(self, value: Any) -> None:
        self._scalar_scripts.append(value)

    def next_row(self) -> Optional[_Row]:
        if self._row_scripts:
            return self._row_scripts.pop(0)
        return None

    def next_rows(self) -> list[_Row]:
        if self._rows_scripts:
            return self._rows_scripts.pop(0)
        return []

    def next_scalar(self) -> Any:
        if self._scalar_scripts:
            return self._scalar_scripts.pop(0)
        return None

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self)


@pytest.fixture
def mock_pool() -> _MockPool:
    return _MockPool()


# ---------------------------------------------------------------------------
# File-backed BackupTarget (safe for tests — never hits real cloud)
# ---------------------------------------------------------------------------


@pytest.fixture
def backup_target_file(tmp_path) -> BackupTarget:
    bucket = str(tmp_path / "bucket")
    return BackupTarget(
        scheme="file",
        bucket=bucket,
        prefix="spine-dr-tests",
        kms_key_ref="recovery/kms/test/key_id",
    )


@pytest.fixture
def backup_target_s3() -> BackupTarget:
    return BackupTarget(
        scheme="s3",
        bucket="example-spine-dr",
        prefix="spine-dr",
        region="us-east-1",
        kms_key_ref="recovery/kms/test/key_id",
        storage_creds_path="recovery/storage/test",
    )


@pytest.fixture
def backup_target_gs() -> BackupTarget:
    return BackupTarget(
        scheme="gs",
        bucket="example-spine-dr",
        prefix="spine-dr",
        kms_key_ref="recovery/kms/test/key_id",
    )


@pytest.fixture
def backup_target_azure() -> BackupTarget:
    return BackupTarget(
        scheme="azure",
        bucket="examplespinedr",
        prefix="spine-dr",
        kms_key_ref="recovery/kms/test/key_id",
    )
