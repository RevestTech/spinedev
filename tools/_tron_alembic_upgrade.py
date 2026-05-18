"""Run TRON's alembic migrations against the Spine-managed TRON postgres.

Defaults align with verify/.env (spine_tron_postgres on host 127.0.0.1:33010).
Override via DATABASE_URL if the host port or password changes.

Usage:
    .venv/bin/python tools/_tron_alembic_upgrade.py [revision]

Examples:
    .venv/bin/python tools/_tron_alembic_upgrade.py            # → head
    .venv/bin/python tools/_tron_alembic_upgrade.py +1         # +1 step
    .venv/bin/python tools/_tron_alembic_upgrade.py 008        # to 008

Re-runnable: alembic skips revisions already in tron.alembic_version.
"""

from __future__ import annotations

import os
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIFY = REPO_ROOT / "verify"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _tron_local_default import resolve_tron_db_url  # noqa: E402

os.environ.setdefault("DATABASE_URL", resolve_tron_db_url("DATABASE_URL"))
sys.path.insert(0, str(VERIFY))

from alembic.config import Config  # noqa: E402
from alembic import command  # noqa: E402

cfg = Config(str(VERIFY / "alembic.ini"))
cfg.set_main_option("script_location", str(VERIFY / "alembic"))

revision = sys.argv[1] if len(sys.argv) > 1 else "head"
command.upgrade(cfg, revision)
print(f"alembic upgrade {revision}: OK")
