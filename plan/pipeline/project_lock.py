"""project_lock.py — pin a project to a pipeline version at project start.

`STORY-1.7.5` + migration slice of `STORY-1.7.6` (`docs/BACKLOG.md`). Backs
PRD REQ-INIT-1 FR-8 (`docs/PRD.md`): locked projects only migrate via
explicit user action + diff preview. State lives in `spine_lifecycle.project`
(`pipeline_version` + `metadata.pipeline_manifest_snapshot` — see
`db/flyway/sql/V14__spine_lifecycle_schema.sql`). DB I/O via `psql` subprocess.

Wave 1 (v3) SQL-injection fix:
    The original implementation built SQL via f-string interpolation and
    relied on a single-quote-doubling escape on ``snap``. That escape is
    incomplete — backslashes, ``E'...'`` hex literals and Unicode escapes
    could still smuggle SQL through caller-controlled ``project_id``
    values.

    This module now binds every untrusted value as a *psql variable* via
    stdin (``\\set``) and references it inside the query with the
    auto-quoting form ``:'name'`` (for strings) or ``:"name"`` (for
    identifiers). psql performs the quoting + escaping itself, which is
    safe against the full grammar of Postgres string literals — including
    backslash, hex, and Unicode forms.
"""
from __future__ import annotations

import json, os, subprocess
from dataclasses import dataclass, field
from typing import Any, Optional

from .capability_checker import assert_rationale, require_capability
from .manifest_loader import PipelineManifest
from .versioning import compute_pipeline_version


@dataclass
class MigrationResult:
    """Outcome of `migrate_locked_project`."""
    project_id: str; from_version: str; to_version: str
    diff: dict[str, Any] = field(default_factory=dict)


def _db_url() -> str:
    url = os.environ.get("SPINE_DB_URL")
    if not url: raise RuntimeError("SPINE_DB_URL not set — project-lock needs a database")
    return url


def _psql(sql: str) -> str:
    """Run `psql -At` against SPINE_DB_URL; returns stripped stdout.

    Legacy helper retained for backwards compatibility — internal callers
    are migrated to ``_psql_bound`` (parameter-binding form) below. New
    code MUST NOT pass untrusted input through ``_psql``; build the query
    with named binds and call ``_psql_bound`` instead.
    """
    r = subprocess.run(["psql", _db_url(), "-At", "-v", "ON_ERROR_STOP=1", "-c", sql],
                       check=True, capture_output=True, text=True)
    return r.stdout.strip()


def _psql_bound(sql_with_binds: str, binds: dict[str, str]) -> str:
    """Run psql with safely-bound parameters.

    Args:
        sql_with_binds: a query referencing variables via ``:'name'`` for
            string literals or ``:"name"`` for identifiers — both forms
            are escaped by psql itself.
        binds: mapping of variable name -> string value. Values are
            passed via stdin as ``\\set`` commands so they never go on
            the command line (no argv leakage, no shell parsing).

    The full stdin script is therefore:

        \\set ON_ERROR_STOP 1
        \\set name 'value'   -- repeated per bind, single-quoted-escaped
        <sql_with_binds>

    psql validates that ``:'name'`` expansions are proper SQL string
    literals and that ``:"name"`` expansions are proper identifiers,
    rejecting anything that would break out.
    """
    # ── Compose the stdin script ──────────────────────────────────────
    # Each \set value is single-quote-wrapped here so psql receives a
    # literal-string variable value (the inner doubled-quote escape is
    # the documented psql way to embed a single quote in a \set value).
    # psql then re-escapes when the variable is interpolated with
    # :'name' (string) or :"name" (identifier).
    lines: list[str] = [r"\set ON_ERROR_STOP 1"]
    for name, value in binds.items():
        # Variable names must be safe — restrict to identifier shape.
        if not name.replace("_", "").isalnum():
            raise ValueError(f"unsafe bind name: {name!r}")
        # Escape ' as '' inside the \set value; the outer quoting is
        # done by ``\set name 'value'`` form.
        safe = value.replace("'", "''")
        lines.append(f"\\set {name} '{safe}'")
    lines.append(sql_with_binds)
    script = "\n".join(lines) + "\n"

    proc = subprocess.run(
        ["psql", _db_url(), "-At", "-X", "-q"],
        input=script,
        check=True, capture_output=True, text=True,
    )
    return proc.stdout.strip()


def _snapshot(manifest: PipelineManifest) -> str:
    """Canonical JSON of manifest body (what we store in metadata)."""
    body = manifest.model_dump(exclude={"resolved_version", "inheritance_chain"})
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)


def _audit(action: str, project_id: str, metadata: dict[str, Any], actor: str,
           rationale: Optional[str]) -> None:
    """Best-effort audit write; never blocks a lock if audit infra is missing."""
    try:
        from shared.audit.audit_record import AuditRecord, chain_to_previous, write_via_psql
    except Exception: return
    try: pid_int: Optional[int] = int(project_id)
    except (TypeError, ValueError): pid_int = None
    rec = AuditRecord(project_id=pid_int, role="orchestrator", subsystem="orchestrator",
                      action=action, actor=actor, rationale=rationale, metadata=metadata)
    rec = chain_to_previous(rec, None)
    try: write_via_psql(rec)
    except Exception: pass


def lock_project_to_pipeline(project_id: str, manifest: PipelineManifest) -> str:
    """Pin a project to a pipeline version. Returns the locked version sha.

    Hardened against SQL injection in ``project_id`` and the snapshot
    body — both are bound via psql ``:'name'`` interpolation rather than
    f-string-concatenated into the SQL text.
    """
    version = compute_pipeline_version(manifest)
    snap = _snapshot(manifest)
    sql = (
        "UPDATE spine_lifecycle.project SET "
        "pipeline_version = :'version', "
        "metadata = COALESCE(metadata,'{}'::jsonb) || jsonb_build_object("
        "'pipeline_manifest_snapshot', (:'snap')::jsonb) "
        "WHERE project_uuid::text = :'pid' OR id::text = :'pid';"
    )
    _psql_bound(sql, {"version": version, "snap": snap, "pid": project_id})
    _audit("project_locked", project_id, {"pipeline_version": version, "manifest_hash": version},
           actor="system", rationale="project locked at start (FR-8 / STORY-1.7.5)")
    return version


def get_locked_pipeline(project_id: str) -> PipelineManifest:
    """Reconstitute the locked manifest snapshot for `project_id`.

    ``project_id`` is bound via ``:'pid'`` so callers may safely pass any
    text from the API surface — psql performs the literal-quoting.
    """
    sql = (
        "SELECT pipeline_version, "
        "COALESCE(metadata->>'pipeline_manifest_snapshot','') "
        "FROM spine_lifecycle.project "
        "WHERE project_uuid::text = :'pid' OR id::text = :'pid' "
        "LIMIT 1;"
    )
    raw = _psql_bound(sql, {"pid": project_id})
    if not raw: raise LookupError(f"project {project_id} not found")
    version, _, snap = raw.partition("|")
    if not snap: raise LookupError(f"project {project_id} has no pipeline_manifest_snapshot")
    body = json.loads(snap)
    body.setdefault("resolved_version", version); body.setdefault("inheritance_chain", [])
    return PipelineManifest(**body)


def _diff_manifests(old: PipelineManifest, new: PipelineManifest) -> dict[str, Any]:
    """Section-level diff for the FR-8 'diff preview' requirement."""
    o = {p.get("id"): p for p in old.phases}; n = {p.get("id"): p for p in new.phases}
    return {"phases_added": sorted(set(n) - set(o)), "phases_removed": sorted(set(o) - set(n)),
            "phases_modified": sorted(pid for pid in (set(o) & set(n)) if o[pid] != n[pid]),
            "tier_routing_changed": old.tier_routing != new.tier_routing,
            "capabilities_changed": old.capabilities != new.capabilities}


def migrate_locked_project(project_id: str, new_manifest: PipelineManifest,
                           actor: str, rationale: str) -> MigrationResult:
    """Per FR-8: explicit migration — capability check + diff preview + audit."""
    rationale = assert_rationale(actor, "can_modify_sdlc_pipeline", rationale)
    require_capability(actor, "can_modify_sdlc_pipeline", new_manifest)
    old = get_locked_pipeline(project_id); diff = _diff_manifests(old, new_manifest)
    from_v = compute_pipeline_version(old)
    to_v = lock_project_to_pipeline(project_id, new_manifest)
    _audit("project_pipeline_migrated", project_id,
           {"from_version": from_v, "to_version": to_v, "diff": diff},
           actor=actor, rationale=rationale)
    return MigrationResult(project_id=project_id, from_version=from_v, to_version=to_v, diff=diff)


def is_pipeline_drifted(project_id: str, current: Optional[PipelineManifest] = None) -> bool:
    """True iff the active resolved manifest differs from the project's lock."""
    locked = get_locked_pipeline(project_id)
    if current is None:
        from .manifest_loader import load_pipeline  # local: break import cycle
        current = load_pipeline(project_id=project_id)
    return compute_pipeline_version(locked) != compute_pipeline_version(current)


__all__ = ["MigrationResult", "get_locked_pipeline", "is_pipeline_drifted",
           "lock_project_to_pipeline", "migrate_locked_project"]
