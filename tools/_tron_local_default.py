"""Local-dev TRON Postgres connection default with fail-closed guard.

The literal password below is a **development sentinel** for the
local-only TRON Postgres container (bound to 127.0.0.1:33010 by
`verify/docker-compose.override.yml`). It is intentionally loud + dated
so it cannot be mistaken for a real credential.

Per V3 design decision #9 (vault-only secrets) + V1_SHIP_CHECKLIST.md §4,
any production deployment MUST override via `TRON_DATABASE_URL` /
`DATABASE_URL` from a vault-managed value. To prevent the sentinel from
leaking into a non-loopback connection (a real prod risk if an operator
copies the default and changes only the host), this helper refuses
sentinel-on-non-loopback combinations at call time.

Rotation history:
  - 2026-05-18  `tron_dev_only` → `tron_LOCAL_DEV_ONLY_2026` (commit pending
    at write time; supersedes the literal exposed in old `verify/.env`
    via git history commit `493b07c`).
"""

from __future__ import annotations

import os
from typing import Optional

LOCAL_DEV_USER = "tron"
LOCAL_DEV_PASSWORD = "tron_LOCAL_DEV_ONLY_2026"  # nosec B105 — dev sentinel; see module docstring
LOCAL_DEV_HOST = "127.0.0.1"
LOCAL_DEV_PORT = 33010
LOCAL_DEV_DB = "tron"

DEFAULT_URL = (
    f"postgresql://{LOCAL_DEV_USER}:{LOCAL_DEV_PASSWORD}"
    f"@{LOCAL_DEV_HOST}:{LOCAL_DEV_PORT}/{LOCAL_DEV_DB}"
)

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")


def _is_loopback(url: str) -> bool:
    return any(host in url for host in _LOOPBACK_HOSTS)


def resolve_tron_db_url(env_var: str = "TRON_DATABASE_URL") -> str:
    """Return the TRON Postgres URL with a fail-closed sentinel guard.

    Resolution order:
      1. `env_var` (default `TRON_DATABASE_URL`)
      2. `DATABASE_URL`
      3. `DEFAULT_URL` (sentinel; loopback only)

    Raises SystemExit if the sentinel password appears in a URL whose host
    is not loopback — that combination indicates a misconfigured deployment
    and the connection MUST NOT proceed with the dev sentinel.
    """
    url: Optional[str] = os.environ.get(env_var) or os.environ.get("DATABASE_URL")
    if url is None:
        return DEFAULT_URL
    if LOCAL_DEV_PASSWORD in url and not _is_loopback(url):
        raise SystemExit(
            "refusing to connect: TRON local-dev sentinel password "
            f"({LOCAL_DEV_PASSWORD!r}) detected against a non-loopback host. "
            "Rotate the password via vault path `tron/postgres/password` "
            "before deploying. See docs/V1_SHIP_CHECKLIST.md §4."
        )
    return url
