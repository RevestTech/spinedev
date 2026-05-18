"""Tiny psql shim for the evidence subsystem.

Pattern mirrors ``shared.audit.exporter._stream_rows`` — we shell out to
``psql -At -X -v ON_ERROR_STOP=1`` rather than carry a DB driver
dependency. This keeps the evidence package importable in stripped-down
test envs (no psycopg2 / asyncpg required) and means tests can mock the
single function instead of patching a connection pool.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Iterator, Optional


def _db_url(db_url: Optional[str]) -> str:
    """Resolve ``db_url`` arg → explicit value → ``SPINE_DB_URL`` env.

    NOTE: this reads ``SPINE_DB_URL`` (a DB connection URL), not a
    secret value — which is permitted under decision #9 (only secret
    *values* must go through ``shared.secrets``).
    """
    url = db_url or os.environ.get("SPINE_DB_URL")
    if not url:
        raise RuntimeError("SPINE_DB_URL not set and db_url not provided")
    return url


def query_rows(sql: str, db_url: Optional[str] = None) -> Iterator[dict[str, Any]]:
    """Run a SELECT, yield one dict per row via ``row_to_json``.

    Caller is responsible for parameter safety. The few collector
    queries that use external values do their own escaping (typed
    filters; no untrusted strings on this code path).
    """
    url = _db_url(db_url)
    wrapped = f"SELECT row_to_json(t) FROM ({sql}) t;"
    proc = subprocess.run(
        ["psql", url, "-At", "-X", "-v", "ON_ERROR_STOP=1", "-c", wrapped],
        check=True, capture_output=True, text=True,
    )
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


__all__ = ["query_rows"]
