#!/usr/bin/env python3
"""proxy.py — Spine Approval Queue dev REST proxy.

DEV ONLY. Wraps orchestrator/lib/gate.sh subcommands behind a tiny HTTP
surface so the static UI can hit fetch() without CORS or SSH gymnastics.
Production replaces this with the FastAPI surface from STORY-9.9.2.

Routes:
  GET  /api/v2/approvals?status=pending           → gate.sh list-pending
  GET  /api/v2/approvals?status=approved&since=*  → best-effort recent list
  POST /api/v2/approvals  {project_id, phase, action, approver, notes}
       action ∈ {approve, reject, request_changes}
  GET  /api/v2/artifacts?path=docs/projects/foo/prd.md  → markdown text
  GET  /healthz
"""
from __future__ import annotations
import argparse, json, os, pathlib, subprocess, sys, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SPINE_ROOT = pathlib.Path(os.environ.get("SPINE_ROOT", pathlib.Path(__file__).resolve().parents[3]))
GATE_SH = pathlib.Path(os.environ.get("SPINE_GATE_SH", SPINE_ROOT / "orchestrator/lib/gate.sh"))


def _cors(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "content-type,accept")


def _gate(*args: str) -> tuple[int, str, str]:
    """Invoke gate.sh with args; capture stdout/stderr/rc."""
    try:
        r = subprocess.run(["bash", str(GATE_SH), *args], capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired:
        return 124, "", "gate.sh timed out"


def _parse_json(stdout: str) -> dict | None:
    try:
        return json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else None
    except Exception:
        return None


def _safe_artifact_path(rel: str) -> pathlib.Path | None:
    """Resolve `rel` under SPINE_ROOT, refusing traversal."""
    if not rel or rel.startswith("phase:"):
        return None
    root = SPINE_ROOT.resolve()
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target if target.is_file() else None


class Handler(BaseHTTPRequestHandler):
    server_version = "SpineApprovalsProxy/1"

    # quieter logs
    def log_message(self, fmt, *args):
        sys.stderr.write("[proxy] " + (fmt % args) + "\n")

    def _send(self, code: int, payload, ctype: str = "application/json") -> None:
        body = payload if isinstance(payload, (bytes, bytearray)) else (
            payload if isinstance(payload, str) else json.dumps(payload)
        )
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        _cors(self)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204); _cors(self); self.end_headers()

    def do_GET(self):  # noqa: N802
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/healthz":
            return self._send(200, {"ok": True, "gate_sh": str(GATE_SH), "root": str(SPINE_ROOT)})
        if u.path == "/api/v2/approvals":
            status = (q.get("status", ["pending"])[0]).lower()
            if status == "approved":
                # gate.sh has no native "recent" feed; return [] until added.
                return self._send(200, {"ok": True, "recent": []})
            rc, out, err = _gate("list-pending")
            data = _parse_json(out) or {"ok": False, "error": err or "no output"}
            return self._send(200 if rc == 0 else 502, data)
        if u.path == "/api/v2/artifacts":
            rel = q.get("path", [""])[0]
            p = _safe_artifact_path(rel)
            if not p:
                return self._send(404, {"ok": False, "error": f"artifact not found: {rel}"})
            return self._send(200, p.read_text(encoding="utf-8", errors="replace"), ctype="text/markdown")
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):  # noqa: N802
        u = urllib.parse.urlparse(self.path)
        if u.path != "/api/v2/approvals":
            return self._send(404, {"ok": False, "error": "not found"})
        try:
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as e:
            return self._send(400, {"ok": False, "error": f"bad json: {e}"})
        pid = str(body.get("project_id", "")).strip()
        phase = str(body.get("phase", "")).strip()
        action = str(body.get("action", "")).strip()
        actor = str(body.get("approver", "")).strip() or "user"
        notes = str(body.get("notes", "")).strip()
        if not pid or not action:
            return self._send(400, {"ok": False, "error": "project_id + action required"})
        if action == "approve":
            args = ["approve", pid, actor] + ([notes] if notes else [])
        elif action == "reject":
            if not notes:
                return self._send(400, {"ok": False, "error": "reason required for reject"})
            args = ["reject", pid, actor, notes]
        elif action in ("request_changes", "request-changes"):
            if not notes:
                return self._send(400, {"ok": False, "error": "notes required for request-changes"})
            args = ["request-changes", pid, actor, notes]
        else:
            return self._send(400, {"ok": False, "error": f"unknown action: {action}"})
        rc, out, err = _gate(*args)
        data = _parse_json(out) or {"ok": rc == 0, "stdout": out, "stderr": err}
        self._send(200 if rc == 0 else 502, data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8081)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    sys.stderr.write(f"[proxy] listening on http://127.0.0.1:{args.port} (gate.sh={GATE_SH})\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
