#!/usr/bin/env python3
"""HMAC-signed phase-gate approval tokens for the Spine orchestrator.

Implements STORY-9.3.2 (HMAC tokens) and the verifier half of STORY-9.3.1
(gate check). Called from `orchestrator/lib/transition.sh` via subprocess.

Threat model
------------
- Goal: prevent forgery or tampering of phase-gate approvals **within a
  single Spine install**. Without the key file, an attacker cannot mint a
  token that verifies; any mutation invalidates the signature.
- Mechanism: per-install 256-bit symmetric HMAC key at
  ``~/.spine/secrets/hmac.key`` (mode 0600, never logged). Tokens carry
  ``(project_id, phase, approver, issued_at, expires_at)`` signed with
  HMAC-SHA256 over the base64url payload.
- Non-goals (deferred per OQ-2 in docs/PRD.md#req-init-9): key rotation,
  per-approver asymmetric keypairs, cross-install token portability.

Standard library only. Python 3.11+.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_KEY_PATH = Path.home() / ".spine" / "secrets" / "hmac.key"
DEFAULT_TTL_HOURS = 168  # 7 days; matches gate_policy.default_expiry_hours
DEFAULT_DB_URL = "postgresql://spine:spine@localhost:33000/spine"
KEY_BYTES = 32  # 256-bit
PAYLOAD_FIELDS = ("project_id", "phase", "approver", "issued_at", "expires_at")


class ApprovalError(Exception):
    """User-visible failure; main() emits structured JSON to stderr."""

    def __init__(self, message: str, code: str = "approval_error") -> None:
        super().__init__(message)
        self.code = code


# ─── key management ──────────────────────────────────────────────────

def _load_key(path: Path) -> bytes:
    if not path.exists():
        raise ApprovalError(
            f"HMAC key not found at {path}; run `approval.py genkey` first",
            code="key_missing")
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ApprovalError(
            f"HMAC key at {path} has insecure perms {oct(mode)}; expected 0600",
            code="key_insecure_perms")
    return path.read_bytes()

def cmd_genkey(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser()
    if path.exists():
        raise ApprovalError(
            f"key already exists at {path}; refusing to overwrite",
            code="key_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except PermissionError as e:
        raise ApprovalError(
            f"cannot chmod 0700 on {path.parent}: {e}",
            code="key_perm_error") from e
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:                                  # O_EXCL closes TOCTOU window
        os.write(fd, secrets.token_bytes(KEY_BYTES))
    finally:
        os.close(fd)
    print(json.dumps({"ok": True, "path": str(path), "bits": KEY_BYTES * 8}))
    return 0


# ─── token sign / verify ─────────────────────────────────────────────

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _now_iso() -> tuple[datetime, str]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return now, now.isoformat().replace("+00:00", "Z")


def sign_token(project_id: str, phase: str, approver: str,
               ttl_hours: int, key_path: Path) -> tuple[str, dict[str, str]]:
    key = _load_key(key_path)
    now, now_s = _now_iso()
    exp_s = (now + timedelta(hours=ttl_hours)).isoformat().replace("+00:00", "Z")
    payload = {
        "project_id": str(project_id), "phase": str(phase),
        "approver": str(approver), "issued_at": now_s, "expires_at": exp_s,
    }
    payload_b64 = _b64url(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    sig = hmac.new(key, payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url(sig)}", payload


def cmd_sign(args: argparse.Namespace) -> int:
    token, _ = sign_token(args.project_id, args.phase, args.approver,
                          args.ttl_hours, Path(args.key_path).expanduser())
    sys.stdout.write(token + "\n")  # token only — not logged anywhere
    return 0


def verify_token(token: str, key_path: Path,
                 expected_project_id: str | None = None,
                 expected_phase: str | None = None) -> dict[str, Any]:
    """Return {valid, payload, errors}. Never raises on a bad token."""
    if not token or "." not in token:
        return {"valid": False, "payload": {}, "errors": ["malformed_token"]}
    payload_b64, sig_b64 = token.rsplit(".", 1)
    try:
        key = _load_key(key_path)
    except ApprovalError as e:
        return {"valid": False, "payload": {}, "errors": [e.code]}

    errors: list[str] = []
    try:
        expected_sig = hmac.new(
            key, payload_b64.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected_sig, _b64url_decode(sig_b64)):
            errors.append("signature_mismatch")
    except Exception:
        return {"valid": False, "payload": {}, "errors": ["malformed_signature"]}

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return {"valid": False, "payload": {},
                "errors": errors + ["malformed_payload"]}

    for field in PAYLOAD_FIELDS:
        if field not in payload:
            errors.append(f"missing_field:{field}")

    if "expires_at" in payload:
        try:
            exp = datetime.fromisoformat(
                payload["expires_at"].replace("Z", "+00:00"))
            if exp <= datetime.now(timezone.utc):
                errors.append("expired")
        except Exception:
            errors.append("bad_expires_at")

    if expected_project_id is not None and \
            str(payload.get("project_id")) != str(expected_project_id):
        errors.append("project_id_mismatch")
    if expected_phase is not None and payload.get("phase") != expected_phase:
        errors.append("phase_mismatch")

    return {"valid": not errors, "payload": payload, "errors": errors}


def cmd_verify(args: argparse.Namespace) -> int:
    result = verify_token(args.token, Path(args.key_path).expanduser(),
                          args.project_id, args.phase)
    sys.stdout.write(json.dumps(result) + "\n")
    if not result["valid"]:
        sys.stderr.write(f"approval verification failed: "
                         f"{','.join(result['errors'])}\n")
        return 2
    return 0


# ─── postgres grant / revoke (psql subprocess) ───────────────────────

def _run_psql(sql: str, db_url: str) -> str:
    cmd = ["psql", db_url, "-At", "-v", "ON_ERROR_STOP=1", "-c", sql]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=15)
    except FileNotFoundError as e:
        raise ApprovalError("psql not on PATH", code="psql_missing") from e
    except subprocess.TimeoutExpired as e:
        raise ApprovalError("psql timed out", code="psql_timeout") from e
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip().replace("\n", " | ")
        raise ApprovalError(f"psql failed: {stderr}", code="psql_error") from e
    return result.stdout.strip()


def _esc(value: str) -> str:
    return value.replace("'", "''")


def cmd_grant(args: argparse.Namespace) -> int:
    token, payload = sign_token(args.project_id, args.phase, args.approver,
                                args.ttl_hours, Path(args.key_path).expanduser())
    db_url = os.environ.get("SPINE_DB_URL", DEFAULT_DB_URL)
    notes_sql = f"'{_esc(args.notes)}'" if args.notes else "NULL"
    sql = (
        "INSERT INTO spine_lifecycle.approval "
        "(project_id, phase, artifact_ref, approver, decision, notes, "
        "token, expires_at) VALUES ("
        f"{int(args.project_id)}, '{_esc(args.phase)}', "
        f"'phase:{_esc(args.phase)}', '{_esc(args.approver)}', "
        f"'approved', {notes_sql}, '{_esc(token)}', "
        f"'{_esc(payload['expires_at'])}'::timestamptz) RETURNING id;"
    )
    approval_id = _run_psql(sql, db_url)
    sys.stdout.write(json.dumps({
        "ok": True,
        "approval_id": int(approval_id) if approval_id else None,
        "token": token, "expires_at": payload["expires_at"],
    }) + "\n")
    return 0


def cmd_revoke(args: argparse.Namespace) -> int:
    db_url = os.environ.get("SPINE_DB_URL", DEFAULT_DB_URL)
    sql = ("UPDATE spine_lifecycle.approval SET expires_at = NOW() "
           f"WHERE id = {int(args.approval_id)} RETURNING id;")
    rid = _run_psql(sql, db_url)
    if not rid:
        raise ApprovalError(
            f"no approval row with id={args.approval_id}",
            code="approval_not_found")
    sys.stdout.write(json.dumps({"ok": True, "revoked_id": int(rid)}) + "\n")
    return 0


# ─── CLI ─────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="approval.py",
        description="HMAC approval tokens for Spine phase gates.")
    sub = p.add_subparsers(dest="cmd", required=True)
    kp = str(DEFAULT_KEY_PATH)

    gk = sub.add_parser("genkey", help="generate a fresh 256-bit HMAC key")
    gk.add_argument("--path", default=kp)
    gk.set_defaults(func=cmd_genkey)

    sg = sub.add_parser("sign", help="sign a payload, emit token to stdout")
    for f in ("--project-id", "--phase", "--approver"):
        sg.add_argument(f, required=True)
    sg.add_argument("--ttl-hours", type=int, default=DEFAULT_TTL_HOURS)
    sg.add_argument("--key-path", default=kp)
    sg.set_defaults(func=cmd_sign)

    vf = sub.add_parser("verify", help="verify a token; JSON to stdout")
    vf.add_argument("--token", required=True)
    vf.add_argument("--project-id", default=None)
    vf.add_argument("--phase", default=None)
    vf.add_argument("--key-path", default=kp)
    vf.set_defaults(func=cmd_verify)

    gr = sub.add_parser("grant", help="sign + INSERT approval row")
    for f in ("--project-id", "--phase", "--approver"):
        gr.add_argument(f, required=True)
    gr.add_argument("--notes", default=None)
    gr.add_argument("--ttl-hours", type=int, default=DEFAULT_TTL_HOURS)
    gr.add_argument("--key-path", default=kp)
    gr.set_defaults(func=cmd_grant)

    rv = sub.add_parser("revoke", help="set expires_at = NOW() on a row")
    rv.add_argument("--approval-id", required=True)
    rv.set_defaults(func=cmd_revoke)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except ApprovalError as e:
        sys.stderr.write(json.dumps(
            {"ok": False, "code": e.code, "error": str(e)}) + "\n")
        return 3
    except Exception as e:  # pragma: no cover — last-resort guard
        sys.stderr.write(json.dumps(
            {"ok": False, "code": "unexpected", "error": str(e)}) + "\n")
        return 4


if __name__ == "__main__":
    sys.exit(main())
