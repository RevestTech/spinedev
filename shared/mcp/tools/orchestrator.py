"""Orchestrator MCP tools — project lifecycle primitives (EPIC-9.9).

Four tools that make up the orchestrator's MCP API surface:

* ``project_create``  — STORY-9.9.1: create a new project in phase ``intake``.
* ``project_status``  — STORY-9.9.1: read current phase, last transition, pending gates.
* ``phase_advance``   — STORY-9.2.1: transition to a target phase (HMAC token).
* ``approval_grant``  — STORY-9.3.2: sign an HMAC token, persist the approval row.

These wrap the bash + Python machinery that already exists under
``orchestrator/lib/`` (``transition.sh``, ``approval.py``) plus direct psql
writes against ``spine_lifecycle.*``. Audit rows go through
``shared.audit.audit_record`` so the hash chain stays intact.
"""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolError, ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)

_FORBID = ConfigDict(extra="forbid")

# Wave-2 (Design Decision #19): the project_type is now one of the 7
# canonical work-item types (feature/bug/incident/support/refactor/infra/
# compliance). Order matches the V28 ENUM seed in
# ``db/flyway/sql/V28__work_item_types.sql``. The previous 4-value set
# (greenfield/evolve/audit_only/operate) was per pre-#19 PRD; with all 7
# work-item types Day 1, the lifecycle template IS the work-item type.
ProjectType = Literal[
    "feature", "bug", "incident", "support", "refactor", "infra", "compliance",
]

# Defaults for the unprovided fields on project_create. The manifest path is
# the canonical pipeline shipped with stock Spine; bundles override it via
# the pipeline-loader (EPIC-1.7) which the orchestrator consults at lock time
# — but for the MCP surface we just record where it came from.
_DEFAULT_PIPELINE_VERSION = "1.0.0"
_DEFAULT_PIPELINE_MANIFEST = "plan/artifacts/sdlc-pipeline-default.yaml"
_INITIAL_PHASE = "intake"

# transition.sh lives next to this module's repo. Allow override for tests.
_REPO_ROOT = Path(__file__).resolve().parents[3]
TRANSITION_SH = Path(os.environ.get("SPINE_TRANSITION_SH",
                                    _REPO_ROOT / "orchestrator/lib/transition.sh"))
PHASES_YAML = Path(os.environ.get("SPINE_PHASES_YAML",
                                  _REPO_ROOT / "orchestrator/state/phases.yaml"))


def _log(tool: str, project_id: str, actor: str) -> None:
    logger.info("mcp_tool_call", extra={"tool": tool, "project_id": project_id, "actor": actor})


# ── DB helpers ──────────────────────────────────────────────────────────


def _db_url() -> str:
    """Read SPINE_DB_URL; raise if absent. Matches kg.py's contract."""
    url = os.environ.get("SPINE_DB_URL")
    if not url:
        raise RuntimeError("SPINE_DB_URL not set; orchestrator tools require an explicit DB URL")
    return url


def _psql(sql: str, *, timeout: int = 15) -> str:
    """Run ``sql`` via psql -At and return trimmed stdout. Raises on non-zero rc."""
    cmd = ["psql", _db_url(), "-At", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"psql rc={proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _esc(value: str) -> str:
    """Single-quote escape for inline SQL literals."""
    return value.replace("'", "''")


def _error(code: str, message: str, *, retryable: bool = False) -> ToolResponse:
    err = ToolError(code=code, message=message, retryable=retryable)
    return ToolResponse(status="error", data={}, error=err)


# ── Audit helper ────────────────────────────────────────────────────────


def _write_audit(*, action: str, project_id: int | None, phase: str | None,
                 actor: str, subject_type: str, subject_id: str,
                 metadata: dict[str, Any], rationale: str | None = None) -> UUID | None:
    """Best-effort audit row write. Returns event_uuid or None on failure.

    Audit writes never block the primary operation — the underlying DB row IS
    the source of truth; the audit chain is a parallel hash-linked ledger.
    """
    try:
        from shared.audit.audit_record import AuditRecord, chain_to_previous, write_via_psql
    except Exception:
        logger.warning("orchestrator_audit_import_failed", extra={"action": action})
        return None
    try:
        # Pull the chain tip so the new row's prev_event_hash is correct.
        try:
            tip = _psql("SELECT content_hash FROM spine_audit.audit_event "
                        "ORDER BY event_id DESC LIMIT 1;")
        except Exception:
            tip = ""
        rec = AuditRecord(
            project_id=project_id, phase=phase, role="orchestrator",
            subsystem="orchestrator", action=action, actor=actor,
            subject_type=subject_type, subject_id=subject_id,
            rationale=rationale, metadata=metadata,
        )
        rec = chain_to_previous(rec, tip or None)
        write_via_psql(rec)
        return rec.event_uuid
    except Exception as exc:  # noqa: BLE001 — audit failure must not crash the tool
        logger.warning("orchestrator_audit_write_failed",
                       extra={"action": action, "err": str(exc)},
                       exc_info=True)
        return None


# ── project_id resolution ───────────────────────────────────────────────


def _resolve_project(project_id: str) -> dict[str, Any] | None:
    """Look up a project by BIGINT id, UUID, or (last resort) name.

    Returns dict with id (int), project_uuid (str), name, current_phase,
    pipeline_version, owner_user; or None if not found.
    """
    # Probe-style WHERE: only one branch matches on a normal call.
    candidates: list[str] = []
    if project_id.isdigit():
        candidates.append(f"id = {int(project_id)}")
    # UUID is 36 chars w/ dashes; let psql do the validation via try/except.
    try:
        UUID(project_id)
        candidates.append(f"project_uuid = '{_esc(project_id)}'::uuid")
    except (ValueError, AttributeError):
        pass
    # Fall back to name match (exact).
    candidates.append(f"name = '{_esc(project_id)}'")
    where = " OR ".join(candidates)
    sql = (
        "SELECT id::text || '|' || project_uuid::text || '|' || name || '|' || "
        "current_phase || '|' || pipeline_version || '|' || owner_user "
        f"FROM spine_lifecycle.project WHERE ({where}) AND status = 'active' "
        "ORDER BY id ASC LIMIT 1;"
    )
    try:
        out = _psql(sql)
    except RuntimeError:
        return None
    if not out:
        return None
    parts = out.split("|", 5)
    if len(parts) != 6:
        return None
    return {
        "id": int(parts[0]), "project_uuid": parts[1], "name": parts[2],
        "current_phase": parts[3], "pipeline_version": parts[4],
        "owner_user": parts[5],
    }


# ── HMAC key bootstrap ──────────────────────────────────────────────────


def _approval_vault_path() -> str:
    """Canonical vault path for the HMAC approval key. Per #9 vault-only.

    Honours SPINE_APPROVAL_VAULT_PATH override (e.g. for namespaced multi-tenant
    Hubs); otherwise returns the approval.py default. SPINE_APPROVAL_KEY_PATH
    (legacy on-disk path) is intentionally NOT honoured — its presence in env
    would be a configuration error and is silently ignored.
    """
    override = os.environ.get("SPINE_APPROVAL_VAULT_PATH")
    if override:
        return override
    from orchestrator.lib.approval import HMAC_KEY_VAULT_PATH
    return HMAC_KEY_VAULT_PATH


def _ensure_approval_key(vault_path: str) -> None:
    """Ensure an HMAC key exists at the given vault path; create if missing.

    Reads from shared.secrets (vault adapter); writes a freshly generated
    256-bit hex key if not present. Idempotent. Raises on vault errors so
    the caller surfaces them as key_init_failed via _error().
    """
    import asyncio
    import secrets as _stdlib_secrets

    from shared.secrets import (
        SecretBackendError,
        SecretNotFound,
        get_secret,
        put_secret,
    )

    async def _check_and_create() -> None:
        try:
            await get_secret(vault_path)
            return  # already present
        except SecretNotFound:
            pass
        # Generate 32 bytes (256 bits), store as hex string (approval.py decodes)
        await put_secret(vault_path, _stdlib_secrets.token_hex(32))

    try:
        asyncio.run(_check_and_create())
    except SecretBackendError:
        raise
    except Exception as e:  # pragma: no cover — bubble up
        raise SecretBackendError(f"_ensure_approval_key failed: {e}") from e


# ── Phase-gate lookup from phases.yaml ──────────────────────────────────


def _phase_requires_gate(target_phase: str) -> bool:
    """True iff phases.yaml marks the target phase with a `gate:` field.

    Plain awk scan — keeps the tool importable without yq. We only need a
    boolean ("is there a gate for this phase?"), not the full structure.
    """
    try:
        text = PHASES_YAML.read_text(encoding="utf-8")
    except OSError:
        return False
    in_block = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if stripped.startswith("- id:"):
            in_block = stripped.split(":", 1)[1].strip() == target_phase
            continue
        if in_block and stripped.startswith("gate:"):
            val = stripped.split(":", 1)[1].split("#", 1)[0].strip()
            return bool(val) and val.lower() != "null"
    return False


# ── Schemas ─────────────────────────────────────────────────────────────


class ProjectCreateInput(BaseModel):
    """Inputs for ``project_create``."""

    model_config = _FORBID
    name: str = Field(..., min_length=1, max_length=200, description="Human-readable project name.")
    project_type: ProjectType = Field(..., description="Lifecycle template to apply.")
    owner: str = Field(..., min_length=1, description="Email or username of the responsible owner.")
    pipeline_version: str = Field(default=_DEFAULT_PIPELINE_VERSION,
                                  description="Locked pipeline manifest version (EPIC-1.7).")
    pipeline_manifest_path: str = Field(default=_DEFAULT_PIPELINE_MANIFEST,
                                        description="Path/content-hash of the locked manifest.")


class ProjectCreatedResponse(BaseModel):
    """``ToolResponse.data`` payload for ``project_create``."""

    model_config = _FORBID
    id: int                        # BIGSERIAL surrogate used by child tables
    project_uuid: str              # external-facing UUID
    project_id: str                # alias = project_uuid (kept for back-compat)
    name: str
    project_type: ProjectType
    owner: str
    initial_phase: str
    pipeline_version: str
    pipeline_manifest_path: str
    created_at: datetime


class ProjectStatusInput(BaseModel):
    """Inputs for ``project_status``."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1,
                            description="Spine project id (BIGINT), project_uuid, or name.")


class PendingApproval(BaseModel):
    """One pending gated transition."""

    model_config = _FORBID
    phase: str
    required_approver: str | None = None
    granted: bool = False


class ProjectStatusResponse(BaseModel):
    """``ToolResponse.data`` payload for ``project_status``."""

    model_config = _FORBID
    id: int
    project_uuid: str
    project_id: str                # alias = project_uuid
    name: str
    current_phase: str
    pipeline_version: str
    pending_approvals: list[PendingApproval]
    last_transition_at: datetime | None


class PhaseAdvanceInput(BaseModel):
    """Inputs for ``phase_advance``."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    target_phase: str = Field(..., min_length=1, description="Phase to advance to per sdlc-pipeline.yaml.")
    actor: str = Field(default="orchestrator", min_length=1)
    rationale: str | None = Field(default=None, max_length=4_000)
    approval_token: str | None = Field(
        default=None, description="HMAC-signed token for gated phases (FR-4); None for system transitions."
    )


class PhaseAdvanceResponse(BaseModel):
    """``ToolResponse.data`` payload for ``phase_advance``."""

    model_config = _FORBID
    project_id: str                # = project_uuid
    id: int                        # = BIGINT project.id
    from_phase: str
    to_phase: str
    transition_id: int
    accepted: bool


class ApprovalGrantInput(BaseModel):
    """Inputs for ``approval_grant``."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    phase: str = Field(..., min_length=1, description="Phase being approved (e.g. 'plan_approved').")
    approver: str = Field(..., min_length=1, description="Username/email of the approver.")
    notes: str | None = Field(default=None, max_length=4_000,
                              description="Optional rationale recorded with the approval.")
    ttl_hours: int = Field(default=168, ge=1, le=24 * 365,
                           description="Token expiry; 7 days matches gate_policy default.")


class ApprovalGrantedResponse(BaseModel):
    """``ToolResponse.data`` payload for ``approval_grant``."""

    model_config = _FORBID
    project_id: str                # = project_uuid
    id: int                        # = BIGINT project.id
    phase: str
    approver: str
    approval_id: int
    token: str
    granted_at: datetime
    expires_at: datetime


# ── project_create ─────────────────────────────────────────────────────


@register_tool(
    name="project_create",
    input_model=ProjectCreateInput,
    story="STORY-9.9.1",
    description="Create a new Spine project in the initial 'intake' phase.",
    tags=("orchestrator", "lifecycle"),
)
def project_create(payload: ProjectCreateInput) -> ToolResponse:
    """Insert project + initial phase_history row + audit event. Idempotent
    on (name, owner, status='active'): a duplicate returns status='error'."""
    _log("project_create", payload.name, payload.owner)

    # Idempotency: refuse to create a second active row with the same (name, owner).
    try:
        existing = _psql(
            "SELECT id::text FROM spine_lifecycle.project "
            f"WHERE name = '{_esc(payload.name)}' "
            f"AND owner_user = '{_esc(payload.owner)}' "
            "AND status = 'active' LIMIT 1;"
        )
    except RuntimeError as exc:
        return _error("db_error", f"idempotency check failed: {exc}", retryable=True)
    if existing:
        return _error("project_already_exists",
                      f"active project name={payload.name!r} owner={payload.owner!r} "
                      f"already exists (id={existing})")

    # Insert project + initial phase_history row in one statement (atomic per
    # psql's implicit transaction around `-c`). CTE chain: project insert first,
    # phase_history derives from it, final SELECT surfaces the new ids.
    sql = (
        "WITH ins AS ("
        "  INSERT INTO spine_lifecycle.project "
        "    (name, project_type, pipeline_version, pipeline_manifest_path, "
        "     owner_user, current_phase) "
        f"   VALUES ('{_esc(payload.name)}', '{_esc(payload.project_type)}', "
        f"           '{_esc(payload.pipeline_version)}', "
        f"           '{_esc(payload.pipeline_manifest_path)}', "
        f"           '{_esc(payload.owner)}', '{_INITIAL_PHASE}') "
        "  RETURNING id, project_uuid, created_at"
        "), "
        "hist AS ("
        f"  INSERT INTO spine_lifecycle.phase_history (project_id, phase) "
        f"  SELECT id, '{_INITIAL_PHASE}' FROM ins "
        "  RETURNING 1"
        ") "
        "SELECT id::text || '|' || project_uuid::text || '|' || created_at::text "
        "FROM ins, hist;"
    )
    try:
        out = _psql(sql)
    except RuntimeError as exc:
        return _error("db_error", f"project insert failed: {exc}", retryable=False)
    if not out:
        return _error("db_error", "project insert returned no row", retryable=True)
    pid_s, uuid_s, created_s = out.split("|", 2)
    pid = int(pid_s)
    created = datetime.fromisoformat(created_s.replace(" ", "T"))

    _write_audit(
        action="project_created", project_id=pid, phase=_INITIAL_PHASE,
        actor=payload.owner, subject_type="project", subject_id=uuid_s,
        metadata={"name": payload.name, "project_type": payload.project_type,
                  "owner": payload.owner,
                  "pipeline_version": payload.pipeline_version,
                  "pipeline_manifest_path": payload.pipeline_manifest_path},
    )

    return ToolResponse(status="ok", data=ProjectCreatedResponse(
        id=pid, project_uuid=uuid_s, project_id=uuid_s,
        name=payload.name, project_type=payload.project_type, owner=payload.owner,
        initial_phase=_INITIAL_PHASE,
        pipeline_version=payload.pipeline_version,
        pipeline_manifest_path=payload.pipeline_manifest_path,
        created_at=created,
    ).model_dump(mode="json"))


# ── project_status ─────────────────────────────────────────────────────


@register_tool(
    name="project_status",
    input_model=ProjectStatusInput,
    story="STORY-9.9.1",
    description="Return the current phase, pending approvals, and pipeline version for a project.",
    tags=("orchestrator", "lifecycle"),
)
def project_status(payload: ProjectStatusInput) -> ToolResponse:
    """Read current phase + last transition + pending gates."""
    _log("project_status", payload.project_id, "system")
    proj = _resolve_project(payload.project_id)
    if proj is None:
        return _error("project_not_found",
                      f"no active project for id/uuid/name={payload.project_id!r}")

    # Most recent transition timestamp.
    last_at: datetime | None = None
    try:
        out = _psql("SELECT to_char(MAX(at), 'YYYY-MM-DD\"T\"HH24:MI:SS.USOF') "
                    f"FROM spine_lifecycle.transition WHERE project_id = {proj['id']};")
        if out:
            last_at = datetime.fromisoformat(out.replace(" ", "T"))
    except (RuntimeError, ValueError):
        last_at = None

    # Pending approvals = gated `next:` phases lacking a valid approved token.
    # We list one entry per gated next-phase; granted=True means an unexpired
    # `approved` row exists. Matches gate.sh's semantics (see transition_gate_check).
    pending: list[PendingApproval] = []
    next_phases = _next_phases_from_yaml(proj["current_phase"])
    for nxt in next_phases:
        if not _phase_requires_gate(nxt):
            continue
        try:
            approver_row = _psql(
                "SELECT approver FROM spine_lifecycle.approval "
                f"WHERE project_id = {proj['id']} AND phase = '{_esc(nxt)}' "
                "AND decision = 'approved' "
                "AND (expires_at IS NULL OR expires_at > NOW()) "
                "ORDER BY granted_at DESC LIMIT 1;"
            )
        except RuntimeError:
            approver_row = ""
        pending.append(PendingApproval(
            phase=nxt,
            required_approver=approver_row or None,
            granted=bool(approver_row),
        ))

    return ToolResponse(status="ok", data=ProjectStatusResponse(
        id=proj["id"], project_uuid=proj["project_uuid"], project_id=proj["project_uuid"],
        name=proj["name"], current_phase=proj["current_phase"],
        pipeline_version=proj["pipeline_version"],
        pending_approvals=pending, last_transition_at=last_at,
    ).model_dump(mode="json"))


def _next_phases_from_yaml(current_phase: str) -> list[str]:
    """Parse `next:` array from phases.yaml for a given phase. awk-style, no yq."""
    try:
        text = PHASES_YAML.read_text(encoding="utf-8")
    except OSError:
        return []
    in_block = False
    in_next = False
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if stripped.startswith("- id:"):
            if in_block:
                # We just left the target phase's block; stop scanning.
                break
            in_block = stripped.split(":", 1)[1].strip() == current_phase
            in_next = False
            continue
        if not in_block:
            continue
        if stripped.startswith("next:"):
            rest = stripped.split(":", 1)[1].split("#", 1)[0].strip()
            if rest.startswith("["):
                # inline array
                items = rest.strip("[]").split(",")
                for it in items:
                    val = it.strip().strip("'\"")
                    if val:
                        out.append(val)
                in_next = False
            elif not rest:
                in_next = True
            continue
        if in_next:
            if stripped.startswith("- "):
                val = stripped[2:].split("#", 1)[0].strip().strip("'\"")
                if val:
                    out.append(val)
            elif stripped and not stripped.startswith("#"):
                in_next = False
    return out


# ── phase_advance ──────────────────────────────────────────────────────


@register_tool(
    name="phase_advance",
    input_model=PhaseAdvanceInput,
    story="STORY-9.2.1",
    description="Advance a project to a target lifecycle phase; verifies HMAC approval token if required.",
    tags=("orchestrator", "lifecycle", "gate"),
)
def phase_advance(payload: PhaseAdvanceInput) -> ToolResponse:
    """Verify token (if the target phase has a gate) and shell out to
    ``transition.sh execute``. On success, parse the new transition row id
    from the DB and write an audit event."""
    _log("phase_advance", payload.project_id, payload.actor)
    proj = _resolve_project(payload.project_id)
    if proj is None:
        return _error("project_not_found",
                      f"no active project for id/uuid/name={payload.project_id!r}")

    # If the target phase carries a gate, validate the supplied token.
    if _phase_requires_gate(payload.target_phase):
        if not payload.approval_token:
            return _error("invalid_approval_token",
                          f"target phase {payload.target_phase!r} requires an approval token; none supplied")
        try:
            from orchestrator.lib.approval import verify_token
            result = verify_token(
                payload.approval_token,
                vault_path=_approval_vault_path(),
                expected_project_id=str(proj["id"]),
                expected_phase=payload.target_phase,
            )
        except Exception as exc:
            return _error("invalid_approval_token", f"verify_token raised: {exc}")
        if not result.get("valid"):
            return _error("invalid_approval_token",
                          f"token rejected: {','.join(result.get('errors', []))}")

    # Shell out to transition.sh execute. Signature: execute <pid> <target> <actor> [rationale]
    cmd = ["bash", str(TRANSITION_SH), "execute", str(proj["id"]),
           payload.target_phase, payload.actor]
    if payload.rationale:
        cmd.append(payload.rationale)
    env = os.environ.copy()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
    except subprocess.TimeoutExpired:
        return _error("transition_timeout",
                      f"transition.sh execute timed out after 30s for pid={proj['id']}",
                      retryable=True)
    if proc.returncode != 0:
        return ToolResponse(status="error", data=PhaseAdvanceResponse(
            project_id=proj["project_uuid"], id=proj["id"],
            from_phase=proj["current_phase"], to_phase=payload.target_phase,
            transition_id=0, accepted=False,
        ).model_dump(mode="json"), error=ToolError(
            code="transition_rejected",
            message=(proc.stderr.strip() or proc.stdout.strip()
                     or f"transition.sh rc={proc.returncode}"),
            retryable=False,
        ))

    # transition.sh writes a fresh row in spine_lifecycle.transition with our
    # exact (project_id, from, to) tuple — grab its id.
    try:
        tid = _psql(
            "SELECT id::text FROM spine_lifecycle.transition "
            f"WHERE project_id = {proj['id']} "
            f"AND from_phase = '{_esc(proj['current_phase'])}' "
            f"AND to_phase = '{_esc(payload.target_phase)}' "
            "ORDER BY id DESC LIMIT 1;"
        )
        transition_id = int(tid) if tid else 0
    except (RuntimeError, ValueError):
        transition_id = 0

    _write_audit(
        action="phase_advanced", project_id=proj["id"], phase=payload.target_phase,
        actor=payload.actor, subject_type="transition", subject_id=str(transition_id),
        rationale=payload.rationale,
        metadata={"from_phase": proj["current_phase"], "to_phase": payload.target_phase,
                  "project_uuid": proj["project_uuid"]},
    )

    return ToolResponse(status="ok", data=PhaseAdvanceResponse(
        project_id=proj["project_uuid"], id=proj["id"],
        from_phase=proj["current_phase"], to_phase=payload.target_phase,
        transition_id=transition_id, accepted=True,
    ).model_dump(mode="json"))


# ── approval_grant ─────────────────────────────────────────────────────


@register_tool(
    name="approval_grant",
    input_model=ApprovalGrantInput,
    story="STORY-9.3.2",
    description="Record an approval for a phase gate; returns an HMAC-signed token consumable by phase_advance.",
    tags=("orchestrator", "lifecycle", "gate"),
)
def approval_grant(payload: ApprovalGrantInput) -> ToolResponse:
    """Sign an HMAC token, INSERT a row into spine_lifecycle.approval,
    and write an audit event. The token's `project_id` field is the BIGINT
    project.id so verify_token matches what gate.sh produces from the CLI."""
    _log("approval_grant", payload.project_id, payload.approver)
    proj = _resolve_project(payload.project_id)
    if proj is None:
        return _error("project_not_found",
                      f"no active project for id/uuid/name={payload.project_id!r}")

    vault_path = _approval_vault_path()
    try:
        _ensure_approval_key(vault_path)
    except Exception as exc:
        return _error("key_init_failed", f"could not initialize HMAC key at vault:{vault_path}: {exc}")

    try:
        from orchestrator.lib.approval import sign_token
        token, token_payload = sign_token(
            project_id=str(proj["id"]), phase=payload.phase,
            approver=payload.approver, ttl_hours=payload.ttl_hours,
            vault_path=vault_path,
        )
    except Exception as exc:
        return _error("sign_failed", f"sign_token raised: {exc}")

    notes_sql = f"'{_esc(payload.notes)}'" if payload.notes else "NULL"
    sql = (
        "INSERT INTO spine_lifecycle.approval "
        "(project_id, phase, artifact_ref, approver, decision, notes, token, expires_at) "
        f"VALUES ({proj['id']}, '{_esc(payload.phase)}', "
        f"'phase:{_esc(payload.phase)}', '{_esc(payload.approver)}', 'approved', "
        f"{notes_sql}, '{_esc(token)}', '{_esc(token_payload['expires_at'])}'::timestamptz) "
        "RETURNING id::text || '|' || granted_at::text;"
    )
    try:
        out = _psql(sql)
    except RuntimeError as exc:
        return _error("db_error", f"approval insert failed: {exc}", retryable=False)
    if not out:
        return _error("db_error", "approval insert returned no row", retryable=True)
    approval_id_s, granted_s = out.split("|", 1)
    approval_id = int(approval_id_s)
    granted_at = datetime.fromisoformat(granted_s.replace(" ", "T"))
    expires_at = datetime.fromisoformat(token_payload["expires_at"].replace("Z", "+00:00"))

    _write_audit(
        action="approval_granted", project_id=proj["id"], phase=payload.phase,
        actor=payload.approver, subject_type="approval", subject_id=str(approval_id),
        rationale=payload.notes,
        metadata={"approver": payload.approver, "ttl_hours": payload.ttl_hours,
                  "expires_at": token_payload["expires_at"],
                  "project_uuid": proj["project_uuid"]},
    )

    return ToolResponse(status="ok", data=ApprovalGrantedResponse(
        project_id=proj["project_uuid"], id=proj["id"], phase=payload.phase,
        approver=payload.approver, approval_id=approval_id,
        token=token, granted_at=granted_at, expires_at=expires_at,
    ).model_dump(mode="json"))


__all__: list[str] = [
    "ApprovalGrantInput", "ApprovalGrantedResponse", "PendingApproval",
    "PhaseAdvanceInput", "PhaseAdvanceResponse",
    "ProjectCreateInput", "ProjectCreatedResponse",
    "ProjectStatusInput", "ProjectStatusResponse",
    "approval_grant", "phase_advance", "project_create", "project_status",
]
