"""User tier override (STORY-1.5.5; REQ-INIT-1 FR-6 §5).

Pin a tier (or specific model) per directive. Justified (≥4 chars),
audited (granted_by), counted vs budget by default (router still
hard-blocks on cap exceed), scoped (project + optional directive + role),
revocable + optionally time-boxed. Storage: V22 will introduce a dedicated
`spine_lifecycle.user_tier_override` table; until then overrides live on
`project.metadata` JSONB — public API is stable across that migration.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from shared.cost.router import ModelOverride, RouteRequest, Tier

_PYD = ConfigDict(protected_namespaces=())
DEFAULT_DB_URL = "postgresql://spine:spine@localhost:33000/spine"
SPINE_HOME = Path(os.environ.get("SPINE_HOME", str(Path.home() / ".spine")))
_now = lambda: datetime.now(timezone.utc)
_esc = lambda s: s.replace("'", "''")


class UserTierOverride(BaseModel):
    """One override row. JSON shape is forward-compatible with V22.
    `forced_tier` is validated as Tier (Literal) by pydantic."""
    model_config = _PYD
    override_id: int | None = None
    project_id: int = Field(gt=0)
    directive_id: str | None = None
    role: str | None = None
    forced_tier: Tier
    forced_model: str | None = None
    justification: str = Field(min_length=4)
    granted_by: str = Field(min_length=1)
    granted_at: datetime = Field(default_factory=_now)
    expires_at: datetime | None = None
    counted_against_budget: bool = True
    revoked: bool = False
    revoked_by: str | None = None
    revoked_reason: str | None = None


def _psql(sql: str, db_url: str | None) -> str | None:
    url = db_url or os.environ.get("SPINE_DB_URL", DEFAULT_DB_URL)
    try:
        r = subprocess.run(["psql", url, "-A", "-t", "-X", "-q", "-v", "ON_ERROR_STOP=1",
                            "-c", sql], capture_output=True, text=True, timeout=10, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return r.stdout.strip() or None

def _load(pid: int, db_url: str | None) -> list[UserTierOverride]:
    raw = _psql(f"SELECT COALESCE(metadata->'user_tier_overrides','[]'::jsonb)"
                f" FROM spine_lifecycle.project WHERE id={int(pid)};", db_url)
    if not raw: return []
    try: items = json.loads(raw)
    except json.JSONDecodeError: return []
    out: list[UserTierOverride] = []
    for it in items:
        try: out.append(UserTierOverride(**it))
        except Exception: continue  # noqa: BLE001
    return out

def _save(pid: int, rows: list[UserTierOverride], db_url: str | None) -> None:
    payload = json.dumps([json.loads(o.model_dump_json()) for o in rows])
    _psql(f"UPDATE spine_lifecycle.project SET metadata="
          f"metadata||jsonb_build_object('user_tier_overrides','{_esc(payload)}'::jsonb)"
          f" WHERE id={int(pid)};", db_url)


def set_override(override: UserTierOverride, *, db_url: str | None = None) -> int:
    """Persist; return generated id. Idempotent on (project, directive, role)."""
    rows = [o for o in _load(override.project_id, db_url)
            if o.revoked or not (o.directive_id == override.directive_id
                                 and o.role == override.role)]
    override.override_id = max((o.override_id or 0 for o in rows), default=0) + 1
    rows.append(override); _save(override.project_id, rows, db_url)
    return override.override_id

def lookup_override(project_id: int, directive_id: str | None, role: str | None,
                    *, db_url: str | None = None) -> UserTierOverride | None:
    """Most-specific active override. Specificity: dir+role > dir > role > project."""
    now = _now()
    cands = [o for o in _load(project_id, db_url)
             if not o.revoked and (o.expires_at is None or o.expires_at > now)
             and o.directive_id in (None, directive_id) and o.role in (None, role)]
    if not cands: return None
    cands.sort(key=lambda o: (2 if o.directive_id else 0) + (1 if o.role else 0), reverse=True)
    return cands[0]

def apply_to_route_request(req: RouteRequest, *, project_id: int, role: str,
                           directive_id: str | None = None,
                           db_url: str | None = None) -> RouteRequest:
    """Pin model via ModelOverride if forced_model set, else override intended_tier.
    Router still enforces menu + caps — override does NOT bypass caps."""
    o = lookup_override(project_id, directive_id, role, db_url=db_url)
    if o is None: return req
    upd: dict[str, Any] = {"intended_tier": o.forced_tier}
    if o.forced_model:
        upd["override"] = ModelOverride(model_id=o.forced_model,
                                        justification=o.justification, granted_by=o.granted_by)
    return req.model_copy(update=upd)

def list_active_overrides(project_id: int | None = None, *,
                          db_url: str | None = None) -> list[UserTierOverride]:
    """For UI / audit. project_id=None scans all projects with overrides."""
    now = _now()
    if project_id is not None: pids = [int(project_id)]
    else:
        raw = _psql("SELECT id FROM spine_lifecycle.project "
                    "WHERE metadata ? 'user_tier_overrides';", db_url)
        pids = [int(x) for x in (raw or "").splitlines() if x.strip().isdigit()]
    return [o for pid in pids for o in _load(pid, db_url)
            if not o.revoked and (o.expires_at is None or o.expires_at > now)]

def revoke_override(override_id: int, *, project_id: int, revoked_by: str,
                    reason: str, db_url: str | None = None) -> bool:
    """Mark revoked. Caller emits the separate audit row."""
    rows = _load(project_id, db_url); hit = False
    for o in rows:
        if o.override_id == override_id and not o.revoked:
            o.revoked, o.revoked_by, o.revoked_reason = True, revoked_by, reason; hit = True
    if hit: _save(project_id, rows, db_url)
    return hit


def _cli() -> int:  # python3 user_override.py set|lookup|list|revoke <args>
    p = argparse.ArgumentParser(prog="user_override.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    for n in ("set", "lookup", "list", "revoke"):
        sp = sub.add_parser(n); sp.add_argument("--project-id", type=int, required=(n != "list"))
        if n in ("set", "lookup"): sp.add_argument("--directive-id"); sp.add_argument("--role")
        if n == "set":
            sp.add_argument("--tier", required=True, choices=["low", "medium", "high", "premium"])
            sp.add_argument("--model"); sp.add_argument("--justification", required=True)
            sp.add_argument("--granted-by", required=True)
        if n == "revoke":
            sp.add_argument("--override-id", type=int, required=True)
            sp.add_argument("--revoked-by", required=True); sp.add_argument("--reason", required=True)
    a = p.parse_args()
    if a.cmd == "set":
        print(json.dumps({"ok": True, "override_id": set_override(UserTierOverride(
            project_id=a.project_id, directive_id=a.directive_id, role=a.role,
            forced_tier=a.tier, forced_model=a.model,
            justification=a.justification, granted_by=a.granted_by))}))
    elif a.cmd == "lookup":
        o = lookup_override(a.project_id, a.directive_id, a.role)
        print(o.model_dump_json(indent=2) if o else json.dumps({"ok": False}))
    elif a.cmd == "list":
        print(json.dumps([json.loads(r.model_dump_json())
                          for r in list_active_overrides(a.project_id)], indent=2))
    elif a.cmd == "revoke":
        print(json.dumps({"ok": revoke_override(a.override_id, project_id=a.project_id,
                                                revoked_by=a.revoked_by, reason=a.reason)}))
    return 0

__all__ = ["UserTierOverride", "set_override", "lookup_override",
           "apply_to_route_request", "list_active_overrides", "revoke_override"]
if __name__ == "__main__":
    sys.exit(_cli())
