"""Phase 11 helper for tools/smoke-test.sh — TRON subsystem checks.

Kept as a separate Python file (vs an inline heredoc) so the embedded
double-quotes and f-strings don't fight the bash parser. Called with
PYTHONPATH already set by the harness (repo root + verify/).

Emits PASS/FAIL/INFO lines in the harness "id|status|message" format.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile


def emit(cid: str, status: str, msg: str = "") -> None:
    print(f"{cid}|{status}|{msg}")


# Check 1: import AuditManager via TRON's absolute tron.* path.
try:
    from tron.agents.manager import AuditManager, AuditRequest, AuditResult  # noqa: F401
    emit("tron.import.manager", "PASS", "tron.agents.manager imports clean")
except Exception as exc:
    emit("tron.import.manager", "FAIL", f"{type(exc).__name__}: {exc}")
    sys.exit(0)

# Check 1b: import via Spine wrapper style (verify.tron.*). Works because
# verify/ has no __init__.py — PEP 420 implicit-namespace package kicks in.
# Note: ``verify.tron.X`` and ``tron.X`` resolve to DIFFERENT module objects
# (same source file loaded under two distinct dotted names) — that's an
# expected Python quirk and not a problem for the wrapper, which always
# uses ``verify.tron.*``. We just need both imports to succeed.
try:
    from verify.tron.agents.manager import AuditManager as _AM2
    assert _AM2.__name__ == "AuditManager", "wrapper-style import returned wrong class"
    emit("tron.import.wrapper_style", "PASS",
         "verify.tron.agents.manager imports via namespace pkg")
except Exception as exc:
    emit("tron.import.wrapper_style", "FAIL", f"{type(exc).__name__}: {exc}")

# Check 2: instantiate AuditManager with empty secrets.
try:
    mgr = AuditManager(secrets={})
    assert mgr._agents == {}, f"new manager should have 0 agents, got {len(mgr._agents)}"
    emit("tron.instantiate.empty", "PASS", "AuditManager() with empty secrets OK")
except Exception as exc:
    emit("tron.instantiate.empty", "FAIL", f"{type(exc).__name__}: {exc}")

# Check 3: Bandit (Layer-1 deterministic scanner) callable + emits JSON.
# Direct subprocess invocation mirrors what TRON's LocalSandbox does. No
# LLM call; no docker; just the same shell-out a SecurityISO would do.
try:
    py = sys.executable
    bandit_bin = os.path.join(os.path.dirname(py), "bandit")
    if not os.path.exists(bandit_bin):
        emit("tron.bandit.runs", "FAIL", f"bandit not at {bandit_bin}")
    else:
        with tempfile.TemporaryDirectory(prefix="spine-bandit-smoke-") as td:
            src_path = os.path.join(td, "x.py")
            with open(src_path, "w") as fh:
                # B102: exec used. Bandit will flag this at low/low.
                fh.write("exec('whoami')\n")
            result = subprocess.run(
                [bandit_bin, "-r", td, "-f", "json", "-q",
                 "--severity-level", "low", "--confidence-level", "low"],
                capture_output=True, text=True, timeout=30,
            )
            # Bandit returns 1 when findings are present, 0 when clean.
            data = json.loads(result.stdout)
            n = len(data.get("results", []))
            ok = result.returncode in (0, 1) and n >= 1
            emit("tron.bandit.runs", "PASS" if ok else "FAIL",
                 f"exit={result.returncode} findings={n}")
except Exception as exc:
    emit("tron.bandit.runs", "FAIL", f"{type(exc).__name__}: {exc}")

# Check 4: TRON postgres reachable + alembic at head.
# Uses psycopg2 (sync) — keeps the smoke off the async hot path.
try:
    import psycopg2
    db_url = os.environ.get(
        "TRON_DATABASE_URL",
        "postgresql://tron:tron_dev_only@127.0.0.1:33010/tron",
    )
    conn = psycopg2.connect(db_url, connect_timeout=5)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE';"
        )
        tcount = cur.fetchone()[0]
        cur.execute("SELECT version_num FROM alembic_version;")
        rev = cur.fetchone()[0]
    conn.close()
    if tcount >= 14 and rev == "008":
        emit("tron.db.reachable", "PASS", f"tables={tcount} alembic={rev}")
    else:
        emit("tron.db.reachable", "FAIL",
             f"tables={tcount} alembic={rev} (want >=14, 008)")
except Exception as exc:
    emit("tron.db.reachable", "FAIL", f"{type(exc).__name__}: {exc}")
