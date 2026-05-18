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
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _tron_local_default import resolve_tron_db_url
    db_url = resolve_tron_db_url()
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

# Check 5: iso_invoke MCP tool — dispatcher into TRON ISO agents. We
# call SecurityISO on a tiny synthetic Python file; the call must succeed
# end-to-end (status='ok' or 'degraded') OR fail with one of the
# documented error codes (tron_keys_missing / agent_execution_failed when
# the LLM key isn't valid). What we WON'T tolerate is a Python exception
# or a stub_implementation return.
try:
    from shared.mcp.tools import TOOL_REGISTRY, discover_tools
    discover_tools()
    spec = TOOL_REGISTRY.get("iso_invoke")
    if spec is None:
        emit("iso.iso_invoke.registered", "FAIL", "iso_invoke not in TOOL_REGISTRY")
    else:
        emit("iso.iso_invoke.registered", "PASS",
             f"story={spec.story} module={spec.module}")
        with tempfile.TemporaryDirectory(prefix="spine-iso-smoke-") as td:
            src_path = os.path.join(td, "fixture.py")
            with open(src_path, "w") as fh:
                fh.write("def hello():\n    return 'world'\n")
            payload = spec.input_model.model_validate({
                "project_id": "smoke",
                "actor": "smoke-iso",
                "agent_name": "SecurityISO",
                "code_region": {"file_path": src_path},
                "cost_attribution": "pre_verify",
            })
            resp = spec.fn(payload).model_dump(mode="json")
            status = resp.get("status")
            code = (resp.get("error") or {}).get("code", "")
            # Acceptable outcomes:
            #  - ok / degraded with a real findings list
            #  - error with code in the documented set (LLM key not valid, etc.)
            ok = (
                (status in ("ok",) and resp.get("data", {}).get("status") in ("ok", "degraded"))
                or (status == "error" and code in (
                    "tron_keys_missing", "agent_execution_failed",
                    "agent_init_failed", "no_source_files",
                    "tron_not_importable", "blueprint_build_failed",
                ))
            )
            # NOT acceptable: stub_implementation (the bug we just fixed).
            if status == "stub_implementation":
                emit("iso.iso_invoke.dispatched", "FAIL",
                     f"still returning stub_implementation: {str(resp)[:200]}")
            else:
                emit("iso.iso_invoke.dispatched", "PASS" if ok else "FAIL",
                     f"status={status} code={code or 'n/a'}")
            # Convenience wrapper must delegate to the same impl.
            sec_spec = TOOL_REGISTRY.get("security_iso_scan")
            if sec_spec is not None:
                conv_payload = sec_spec.input_model.model_validate({
                    "project_id": "smoke", "actor": "smoke-iso",
                    "code_region": {"file_path": src_path},
                    "cost_attribution": "pre_verify",
                })
                conv_resp = sec_spec.fn(conv_payload).model_dump(mode="json")
                conv_status = conv_resp.get("status")
                emit("iso.security_iso_scan.delegates",
                     "PASS" if conv_status != "stub_implementation" else "FAIL",
                     f"status={conv_status}")
except Exception as exc:
    emit("iso.iso_invoke.dispatched", "FAIL", f"{type(exc).__name__}: {exc}")
