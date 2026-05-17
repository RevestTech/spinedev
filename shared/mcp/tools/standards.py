"""Standards / org-bundle MCP tools (EPIC-2.2, STORY-2.2.5).

* ``org_standards_get`` — return the parsed org-bundle for a project so an
  agent can make policy-aware decisions mid-task (banned patterns, approved
  libs, cost caps, compliance packs, etc.).

Bundle resolution order (first hit wins):

1. explicit ``bundle_name`` argument
2. project row's ``org_bundle`` column (or ``metadata.org_bundle`` JSON key)
3. ``"default"`` — repo-local reference bundle

Bundle files are read from ``shared/standards/bundle-<name>.yaml`` (the
canonical bundles shipped with stock Spine) with a fallback to
``$SPINE_HOME/bundles/<name>/v*/bundle.yaml`` (where installed bundles live
per ``shared.cost.router._load_active_bundle``).
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolError, ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)

_FORBID = ConfigDict(extra="forbid")

#: Where the canonical reference bundles live in-repo. Lifted from TRON's
#: Standards Hierarchy by EPIC-2.4; ``bundle-<name>.yaml`` filename convention.
_REPO_BUNDLES_DIR = Path(__file__).resolve().parents[2] / "standards"

#: ``$SPINE_HOME/bundles/<name>/v*/bundle.yaml`` is where org-installed
#: bundles land (see ``shared.cost.router``). Used as a fallback when the
#: requested bundle isn't shipped in-repo.
_SPINE_HOME = Path(os.environ.get("SPINE_HOME", str(Path.home() / ".spine")))
_INSTALLED_BUNDLES_DIR = _SPINE_HOME / "bundles"

#: Friendly name → on-disk filename mapping for repo bundles. Stock Spine
#: ships ``default``, ``startup-saas``, and ``regulated-enterprise``.
_REPO_BUNDLE_FILES: dict[str, str] = {
    "default": "bundle-startup-saas.yaml",
    "startup-saas": "bundle-startup-saas.yaml",
    "startup_saas": "bundle-startup-saas.yaml",
    "regulated-enterprise": "bundle-regulated-enterprise.yaml",
    "regulated_enterprise": "bundle-regulated-enterprise.yaml",
}


class OrgStandardsGetInput(BaseModel):
    """Inputs for ``org_standards_get`` (STORY-2.2.5).

    ``project_id`` accepts the same surface as orchestrator tools (BIGINT id,
    project UUID, or name). ``bundle_name`` is an explicit override; when
    omitted the project's recorded bundle (or ``"default"``) is loaded.
    """

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    bundle_name: str | None = Field(default=None, min_length=1,
        description="Explicit bundle to fetch; falls back to project's recorded "
                    "org_bundle, then 'default'.")
    actor: str = Field(default="system", min_length=1)


class OrgStandardsResponse(BaseModel):
    """``ToolResponse.data`` payload for ``org_standards_get``."""

    model_config = _FORBID
    project_id: str
    bundle_name: str
    bundle_version: int | None
    bundle_id: str | None
    source_path: str
    content_sha256: str
    resolved_from: str  # 'argument' | 'project_row' | 'project_metadata' | 'default'
    standards: dict[str, Any]
    audit_id: UUID


def _log(tool: str, project_id: str, actor: str) -> None:
    logger.info("mcp_tool_call",
                extra={"tool": tool, "project_id": project_id, "actor": actor})


def _error(code: str, message: str, *, retryable: bool = False,
           audit_id: UUID | None = None) -> ToolResponse:
    aid = audit_id or uuid4()
    return ToolResponse(status="error", audit_id=aid,
                        error=ToolError(code=code, message=message,
                                        retryable=retryable))


def _db_url() -> str | None:
    """``SPINE_DB_URL``; ``db/.env`` if absent. None on miss (best-effort)."""
    url = os.environ.get("SPINE_DB_URL")
    if url:
        return url
    # Match the convention used by intake_runner / build_dispatcher: source
    # db/.env if it exists. The .env file is the canonical local-dev source.
    env_file = Path(__file__).resolve().parents[2].parent / "db" / ".env"
    if not env_file.is_file():
        return None
    try:
        envs: dict[str, str] = {}
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            envs[k.strip()] = v.strip().strip("'").strip('"')
        user = envs.get("POSTGRES_USER", "spine")
        pw = envs.get("POSTGRES_PASSWORD", "spine")
        port = envs.get("POSTGRES_HOST_PORT", "33000")
        db = envs.get("POSTGRES_DB", "spine")
        return f"postgresql://{user}:{pw}@127.0.0.1:{port}/{db}"
    except Exception:  # pragma: no cover
        return None


def _esc(value: str) -> str:
    return value.replace("'", "''")


def _resolve_project_bundle(project_id: str) -> tuple[str | None, str]:
    """Look up the project's recorded org_bundle.

    Returns ``(bundle_name, resolved_from)`` where ``resolved_from`` is one
    of ``'project_row'`` (matched the dedicated column), ``'project_metadata'``
    (pulled from the JSON ``metadata.org_bundle`` key), or ``'default'``
    (project not found or no bundle recorded).
    """
    url = _db_url()
    if not url:
        return (None, "default")
    # Project lookup mirrors orchestrator._resolve_project — BIGINT > UUID > name.
    candidates: list[str] = []
    if project_id.isdigit():
        candidates.append(f"id = {int(project_id)}")
    try:
        UUID(project_id)
        candidates.append(f"project_uuid = '{_esc(project_id)}'::uuid")
    except (ValueError, AttributeError):
        pass
    candidates.append(f"name = '{_esc(project_id)}'")
    where = " OR ".join(candidates)
    sql = (
        "SELECT COALESCE(org_bundle, '') || '|' || "
        "       COALESCE(metadata->>'org_bundle', '') "
        f"FROM spine_lifecycle.project WHERE ({where}) AND status = 'active' "
        "ORDER BY id ASC LIMIT 1;"
    )
    try:
        proc = subprocess.run(
            ["psql", url, "-At", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
            capture_output=True, text=True, timeout=10)
    except Exception:  # pragma: no cover — DB unreachable; fall back to default
        return (None, "default")
    if proc.returncode != 0:
        return (None, "default")
    out = proc.stdout.strip()
    if not out:
        return (None, "default")
    col, _, meta = out.partition("|")
    if col:
        return (col, "project_row")
    if meta:
        return (meta, "project_metadata")
    return (None, "default")


def _bundle_path(bundle_name: str) -> Path | None:
    """Resolve a bundle name to its on-disk path; None if not installed.

    Checks the repo bundles dir first (canonical reference bundles), then
    falls back to ``$SPINE_HOME/bundles/<name>/v*/bundle.yaml`` (the directory
    layout used by ``shared.cost.router`` for installed bundles).
    """
    filename = _REPO_BUNDLE_FILES.get(bundle_name)
    if filename:
        p = _REPO_BUNDLES_DIR / filename
        if p.is_file():
            return p
    # Plain ``bundle-<name>.yaml`` match — allows ad-hoc bundles dropped into
    # ``shared/standards/`` without an entry in the friendly-name map.
    direct = _REPO_BUNDLES_DIR / f"bundle-{bundle_name}.yaml"
    if direct.is_file():
        return direct
    # Installed bundles under ``$SPINE_HOME``.
    base = _INSTALLED_BUNDLES_DIR / bundle_name
    if base.is_dir():
        vs = sorted(p for p in base.glob("v*") if p.is_dir())
        if vs:
            candidate = vs[-1] / "bundle.yaml"
            if candidate.is_file():
                return candidate
    return None


def _write_standards_audit(*, action: str, project_id: str, actor: str,
                           subject_id: str, metadata: dict[str, Any]) -> UUID:
    """Best-effort audit row; never blocks the lookup on a write failure."""
    audit_uuid = uuid4()
    try:
        from shared.audit.audit_record import (
            AuditRecord, chain_to_previous, write_via_psql,
        )
        rec = AuditRecord(role=actor, subsystem="shared", action=action,
                          actor=actor, subject_type="org_bundle",
                          subject_id=subject_id, metadata=metadata,
                          event_uuid=audit_uuid)
        rec = chain_to_previous(rec, None)
        write_via_psql(rec)
    except Exception as exc:  # noqa: BLE001 — audit is best-effort
        logger.warning("org_standards_audit_failed",
                       extra={"action": action, "err": str(exc)})
    return audit_uuid


@register_tool(
    name="org_standards_get",
    input_model=OrgStandardsGetInput,
    story="STORY-2.2.5",
    description="Fetch the active org-bundle (standards, security, cost caps, etc.) for a project.",
    tags=("standards",),
)
def org_standards_get(payload: OrgStandardsGetInput) -> ToolResponse:
    """Resolve the active bundle name, load + parse the YAML, return the
    full bundle dict so agents can make policy-aware decisions.

    Resolution order: explicit argument -> project's recorded ``org_bundle``
    (column then ``metadata.org_bundle`` key) -> ``"default"``. The returned
    payload includes ``source_path`` and ``content_sha256`` so downstream
    consumers can pin the exact bundle version they made decisions against.
    """
    _log("org_standards_get", payload.project_id, payload.actor)

    # 1. Resolve which bundle to load.
    if payload.bundle_name:
        bundle_name, resolved_from = payload.bundle_name, "argument"
    else:
        bundle_name, resolved_from = _resolve_project_bundle(payload.project_id)
        if not bundle_name:
            bundle_name = "default"

    # 2. Find it on disk.
    path = _bundle_path(bundle_name)
    if path is None:
        audit_id = _write_standards_audit(
            action="standards_get", project_id=payload.project_id,
            actor=payload.actor, subject_id=bundle_name,
            metadata={"result": "unknown_bundle", "bundle_name": bundle_name,
                      "resolved_from": resolved_from})
        return _error(
            "unknown_bundle",
            f"bundle {bundle_name!r} not found in shared/standards/ or "
            f"{_INSTALLED_BUNDLES_DIR}. Install it via "
            "shared/standards/install_bundle.sh or pass an explicit "
            "bundle_name that exists.",
            audit_id=audit_id)

    # 3. Read + parse.
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError) as exc:
        audit_id = _write_standards_audit(
            action="standards_get", project_id=payload.project_id,
            actor=payload.actor, subject_id=bundle_name,
            metadata={"result": "bundle_parse_failed", "path": str(path),
                      "err": str(exc)[:200]})
        return _error(
            "bundle_parse_failed",
            f"bundle at {path} failed to parse: {exc}",
            audit_id=audit_id)
    if not isinstance(parsed, dict):
        audit_id = _write_standards_audit(
            action="standards_get", project_id=payload.project_id,
            actor=payload.actor, subject_id=bundle_name,
            metadata={"result": "bundle_parse_failed", "path": str(path),
                      "err": "root not a mapping"})
        return _error(
            "bundle_parse_failed",
            f"bundle at {path} root is not a YAML mapping",
            audit_id=audit_id)

    # 4. Extract identity for the response envelope (best-effort — bundles
    #    without an identity section still parse and return).
    identity = parsed.get("identity") or {}
    bundle_id = identity.get("bundle_id")
    bundle_version_raw = identity.get("bundle_version")
    try:
        bundle_version = int(bundle_version_raw) if bundle_version_raw is not None else None
    except (TypeError, ValueError):
        bundle_version = None

    content_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    audit_id = _write_standards_audit(
        action="standards_get", project_id=payload.project_id,
        actor=payload.actor, subject_id=bundle_name,
        metadata={"result": "ok", "bundle_name": bundle_name,
                  "bundle_id": bundle_id, "bundle_version": bundle_version,
                  "resolved_from": resolved_from, "path": str(path),
                  "content_sha256": content_sha})

    result = OrgStandardsResponse(
        project_id=payload.project_id, bundle_name=bundle_name,
        bundle_version=bundle_version, bundle_id=bundle_id,
        source_path=str(path), content_sha256=content_sha,
        resolved_from=resolved_from, standards=parsed, audit_id=audit_id)
    return ToolResponse(status="ok", data=result.model_dump(mode="json"),
                        audit_id=audit_id)


__all__: list[str] = ["OrgStandardsGetInput", "OrgStandardsResponse",
                      "org_standards_get"]
