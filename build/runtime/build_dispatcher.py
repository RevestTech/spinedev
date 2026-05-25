"""Spine build-phase dispatcher.

Replaces the `build_dispatch` / `build_completed` stubs (STORY-7.2.2 /
STORY-7.2.3) for the first user-facing slice past plan_approved:

* ``dispatch_build(project_id)`` — synthesizes a Build Brief from the
  project's already-validated PRD draft, persists it to
  ``project.metadata.build_brief``, and returns a typed result the MCP
  wrapper can render.
* ``ingest_build_artifact(project_id, artifact)`` — validates a typed
  ``BuildArtifact``, persists it under ``project.metadata.build_artifact``
  and appends a ``build_history[]`` entry, and reports
  ``ready_for_verify=True``.

Both functions mirror the pattern in ``plan/runtime/intake_runner.py``:
project lookup via psql, jsonb merge of a single top-level metadata key,
audit rows written through ``shared.audit.audit_record`` with failures
swallowed at the boundary (the metadata row IS the source of truth).

We are NOT spawning Claude Code or running engineer daemons here. Spine
plans, an external party (human or LLM) builds, Spine ingests + verifies
— that handoff is the BuildArtifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from plan.artifacts.prd_v1 import PRDv1
from shared.schemas.build.build_artifact import BuildArtifact
from shared.schemas.build.work_item import WORK_ITEM_TYPES, WorkItemType

# ── Constants & paths ──────────────────────────────────────────────────

BUILD_BRIEF_VERSION = "build-brief-v1"

# Metadata keys this module owns. Kept at module scope so smoke + tests
# can reference them by symbol instead of stringly-typed paths.
METADATA_PRD_KEY = "prd_draft"
METADATA_TRD_KEY = "trd_draft"
METADATA_ROADMAP_KEY = "roadmap_draft"
METADATA_BRIEF_KEY = "build_brief"
METADATA_ARTIFACT_KEY = "build_artifact"
METADATA_HISTORY_KEY = "build_history"
METADATA_INTAKE_KEY = "intake"

# Audit action names. The plan side writes intake_*; build mirrors with
# build_* so a `SELECT action, COUNT(*) ...` per-project rolls up cleanly.
AUDIT_DISPATCHED = "build_dispatched"
AUDIT_BRIEF_PERSISTED = "build_brief_persisted"
AUDIT_COMPLETED_RECEIVED = "build_completed_received"
AUDIT_ARTIFACT_PERSISTED = "build_artifact_persisted"

# Default squad composition when the intake template didn't specify one.
# Conservative: every project gets at least engineer+qa. Bundle authors
# extend by setting metadata.intake.swarm_composition on the project.
_DEFAULT_SQUAD = ("engineer", "qa")

# ── Work-item-type routing fallback (mirrors V28 seed) ────────────────
#
# `_TYPE_PIPELINE_FALLBACK` + `_TYPE_ROLE_FALLBACK` are the in-process
# fallback when the DB lookup against `spine_workitem.type_registry`
# fails (offline / mid-migration / unit test). They MUST stay in lock-step
# with the seed in ``db/flyway/sql/V28__work_item_types.sql`` — any drift
# becomes a hard divergence between bash CLI and Python dispatcher.

_TYPE_PIPELINE_FALLBACK: dict[str, str] = {
    "feature":    "default_feature_pipeline",
    "bug":        "default_bug_pipeline",
    "incident":   "default_incident_pipeline",
    "support":    "default_support_pipeline",
    "refactor":   "default_refactor_pipeline",
    "infra":      "default_infra_pipeline",
    "compliance": "default_compliance_pipeline",
}

_TYPE_ROLE_FALLBACK: dict[str, tuple[str, ...]] = {
    "feature":    ("product", "planner", "architect", "engineer", "qa"),
    "bug":        ("engineer", "qa"),
    "incident":   ("operator", "devops", "engineer", "conductor"),
    "support":    ("customer_support", "engineer"),
    "refactor":   ("architect", "engineer", "qa"),
    "infra":      ("devops", "architect", "security_engineer"),
    "compliance": ("compliance_officer", "security_engineer", "tech_writer"),
}

# Per #13 — engineer = hybrid by tier; thin wrapper over external coding
# agents. Defaults are conservative (claude_code + low autonomy); bundle
# policy can widen via metadata.intake.swarm_composition.
ImplementerKind = Literal["claude_code", "cursor", "aider", "openhands", "human"]
AutonomyTier = Literal["low", "medium", "high"]

DEFAULT_IMPLEMENTER_KIND: ImplementerKind = "claude_code"
DEFAULT_AUTONOMY_TIER: AutonomyTier = "low"


# ── Pydantic BuildBrief (typed mirror of the brief dict) ──────────────


class BuildBrief(BaseModel):
    """Typed mirror of the brief dict persisted to ``project.metadata.build_brief``.

    Wave-2 addition: carries ``work_item_type`` + ``implementer_kind`` +
    ``autonomy_tier`` so per-type pipeline routing + #13 hybrid-engineer
    dispatch can read off a single typed surface instead of stringly-typed
    metadata.
    """

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    version: str = BUILD_BRIEF_VERSION
    brief_id: str
    project_id: str
    project_name: str
    pipeline_version: str
    work_item_type: WorkItemType = Field(
        default="feature",
        description="One of 7 canonical work-item types per #19; drives pipeline_id + role_set.",
    )
    pipeline_id: str = Field(
        default=_TYPE_PIPELINE_FALLBACK["feature"],
        description="Resolved pipeline identifier; matches V28 type_registry.pipeline_id.",
    )
    role_set: list[str] = Field(
        default_factory=lambda: list(_TYPE_ROLE_FALLBACK["feature"]),
        description="Per-type default role set; matches V28 type_registry.default_role_set.",
    )
    implementer_kind: ImplementerKind = Field(
        default=DEFAULT_IMPLEMENTER_KIND,
        description="External coding agent Spine wraps (#13 hybrid by tier).",
    )
    autonomy_tier: AutonomyTier = Field(
        default=DEFAULT_AUTONOMY_TIER,
        description="Autonomy tier; per-bundle opt-in to higher tiers (#13).",
    )


def _lookup_type_registry(work_item_type: str) -> Optional[tuple[str, list[str]]]:
    """Fetch (pipeline_id, role_set) from ``spine_workitem.type_registry``.

    Returns ``None`` if the DB lookup fails for any reason — callers must
    then fall back to the in-process constants. We never raise so a missing
    DB doesn't block routing decisions.
    """
    try:
        out = _psql(
            "SELECT pipeline_id || '|' || default_role_set::text "
            "FROM spine_workitem.type_registry "
            f"WHERE type = '{_esc(work_item_type)}' LIMIT 1;"
        )
    except Exception:
        return None
    if not out or "|" not in out:
        return None
    pipeline_id, role_json = out.split("|", 1)
    try:
        roles = json.loads(role_json or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(roles, list):
        return None
    return pipeline_id.strip(), [str(r) for r in roles]


def route_for_work_item_type(
    work_item_type: str,
    *,
    use_db: bool = True,
) -> tuple[str, list[str]]:
    """Resolve (pipeline_id, role_set) for a work-item type.

    Order: DB lookup against V28 `spine_workitem.type_registry` →
    in-process fallback. Raises ``ValueError`` if the type is unknown.
    """
    if work_item_type not in WORK_ITEM_TYPES:
        raise ValueError(
            f"unknown work_item_type={work_item_type!r}; "
            f"expected one of {list(WORK_ITEM_TYPES)}"
        )
    if use_db:
        hit = _lookup_type_registry(work_item_type)
        if hit is not None:
            return hit
    return _TYPE_PIPELINE_FALLBACK[work_item_type], list(_TYPE_ROLE_FALLBACK[work_item_type])


# ── Errors surfaced to the MCP wrapper ─────────────────────────────────


class BuildDispatchError(RuntimeError):
    """Base class for refuse-to-dispatch errors. Carries a stable reason code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class BuildCompletionError(RuntimeError):
    """Base class for refuse-to-ingest errors on the completion side."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


# ── Result types ───────────────────────────────────────────────────────


@dataclass
class DispatchResult:
    """What `dispatch_build()` produced. Mirrors the shape of metadata.build_brief."""

    project_id: int
    brief_id: str
    engineering_goals_count: int
    warnings: list[str] = field(default_factory=list)
    audit_event_count: int = 0


@dataclass
class IngestResult:
    """What `ingest_build_artifact()` produced."""

    project_id: int
    artifact_uuid: str
    artifact_hash: str
    code_changes_count: int
    ready_for_verify: bool
    history_length: int
    audit_event_count: int = 0


# ── DB helpers (psql shell-outs; mirrors intake_runner.py) ─────────────


# `db/.env` lives two levels up from this file (build/runtime/ → repo root).
# Composed lazily so a missing file doesn't blow up at import time.
_REPO_ROOT_FROM_HERE = Path(__file__).resolve().parents[2]
_DB_ENV_KEYS = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST_PORT",
                "POSTGRES_DB", "POSTGRES_BIND_HOST")
# Fallback constants mirror orchestrator/lib/_env_loader.sh + hub dev compose.
_DB_ENV_HUB_DEFAULTS = {
    "POSTGRES_USER": "spine",
    "POSTGRES_PASSWORD": "smoke-test-db-pw",
    "POSTGRES_HOST_PORT": "33099",
    "POSTGRES_DB": "spine",
    "POSTGRES_BIND_HOST": "127.0.0.1",
}
_DB_ENV_LEGACY_DEFAULTS = {
    "POSTGRES_USER": "spine",
    "POSTGRES_PASSWORD": "spine",
    "POSTGRES_HOST_PORT": "33001",
    "POSTGRES_DB": "spine",
    "POSTGRES_BIND_HOST": "127.0.0.1",
}


def _hub_postgres_running() -> bool:
    """True when v3 hub/docker-compose.yml owns Postgres (spine-hub-postgres)."""
    try:
        proc = subprocess.run(
            [
                "docker", "ps",
                "--filter", "name=^/spine-hub-postgres$",
                "--format", "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "spine-hub-postgres"


def _load_db_env_file(path: Path) -> dict[str, str]:
    """Read POSTGRES_* keys from a db/.env without sourcing arbitrary shell."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key not in _DB_ENV_KEYS:
            continue
        # Strip a single layer of surrounding quotes; do NOT unescape.
        v = val.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        out[key] = v
    return out


def _db_url() -> str:
    """SPINE_DB_URL precedence: env > POSTGRES_* env > db/.env > hardcoded.

    The MCP server and bare-python invocations don't run through bash's
    _env_loader.sh, so we mirror its rules here. Operators who already
    exported SPINE_DB_URL pay nothing.
    """
    url = os.environ.get("SPINE_DB_URL")
    if url:
        return url
    parts: dict[str, str] = {}
    for key in _DB_ENV_KEYS:
        ev = os.environ.get(key)
        if ev:
            parts[key] = ev
    hub_mode = _hub_postgres_running()
    if not hub_mode:
        file_path = Path(os.environ.get("SPINE_ENV_FILE") or (_REPO_ROOT_FROM_HERE / "db/.env"))
        from_file = _load_db_env_file(file_path)
        for k, v in from_file.items():
            parts.setdefault(k, v)
    defaults = _DB_ENV_HUB_DEFAULTS if hub_mode else _DB_ENV_LEGACY_DEFAULTS
    for k, v in defaults.items():
        parts.setdefault(k, v)
    composed = (
        f"postgresql://{parts['POSTGRES_USER']}:{parts['POSTGRES_PASSWORD']}"
        f"@{parts['POSTGRES_BIND_HOST']}:{parts['POSTGRES_HOST_PORT']}"
        f"/{parts['POSTGRES_DB']}"
    )
    # Cache for repeat callers in the same process; cheap belt-and-braces.
    os.environ["SPINE_DB_URL"] = composed
    return composed


def _psql(sql: str, *, timeout: int = 15) -> str:
    cmd = ["psql", _db_url(), "-At", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"psql rc={proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _esc(value: str) -> str:
    return value.replace("'", "''")


# ── Project lookup ─────────────────────────────────────────────────────


def _load_project(project_id: int | str) -> dict[str, Any]:
    """Resolve `project_id` (BIGINT id, project_uuid, or name) to the row we need.

    Accepts the same three identifier shapes as
    ``shared.mcp.tools.orchestrator._resolve_project`` — BIGINT, UUID, or
    name — so callers can pass whichever they have without first
    translating. Returns id, project_uuid, name, current_phase,
    pipeline_version, metadata. Raises RuntimeError if no active project
    matches.
    """
    pid_str = str(project_id)
    candidates: list[str] = []
    if isinstance(project_id, int) or pid_str.isdigit():
        candidates.append(f"id = {int(pid_str)}")
    # UUID is 36 chars w/ dashes; let Python validate via try/except.
    try:
        UUID(pid_str)
        candidates.append(f"project_uuid = '{_esc(pid_str)}'::uuid")
    except (ValueError, AttributeError):
        pass
    candidates.append(f"name = '{_esc(pid_str)}'")
    where = " OR ".join(candidates)
    sql = (
        "SELECT id::text || '|' || project_uuid::text || '|' || name || '|' || "
        "current_phase || '|' || pipeline_version || '|' || "
        "COALESCE(work_item_type,'feature') || '|' || "
        "COALESCE(metadata::text,'{}') "
        f"FROM spine_lifecycle.project WHERE ({where}) AND status='active' "
        "ORDER BY id ASC LIMIT 1;"
    )
    try:
        out = _psql(sql)
    except RuntimeError:
        # work_item_type column may not exist on pre-V28 deployments — retry
        # without it so build dispatcher still works during migration.
        legacy_sql = (
            "SELECT id::text || '|' || project_uuid::text || '|' || name || '|' || "
            "current_phase || '|' || pipeline_version || '|' || "
            "'feature' || '|' || "
            "COALESCE(metadata::text,'{}') "
            f"FROM spine_lifecycle.project WHERE ({where}) AND status='active' "
            "ORDER BY id ASC LIMIT 1;"
        )
        out = _psql(legacy_sql)
    if not out:
        raise RuntimeError(f"no active project for id/uuid/name={project_id!r}")
    parts = out.split("|", 6)
    return {
        "id": int(parts[0]),
        "project_uuid": parts[1],
        "name": parts[2],
        "current_phase": parts[3],
        "pipeline_version": parts[4],
        "work_item_type": parts[5],
        "metadata": json.loads(parts[6] or "{}"),
    }


def _merge_metadata(pid: int, patch: dict[str, Any]) -> None:
    """Shallow jsonb merge of `patch` into project.metadata (top-level keys)."""
    payload = json.dumps(patch).replace("'", "''")
    sql = (
        "UPDATE spine_lifecycle.project "
        f"SET metadata = metadata || '{payload}'::jsonb "
        f"WHERE id = {pid};"
    )
    _psql(sql)


# ── Audit helper (best-effort; mirrors intake_runner._write_audit) ─────


def _write_audit(*, action: str, project_id: int, actor: str,
                 metadata: dict[str, Any], rationale: str | None = None,
                 subject_id: str | None = None,
                 subject_type: str = "build",
                 phase: str = "build_in_progress") -> bool:
    try:
        from shared.audit.audit_record import (
            AuditRecord, chain_to_previous, write_via_psql,
        )
    except Exception:
        return False
    try:
        try:
            tip = _psql("SELECT content_hash FROM spine_audit.audit_event "
                        "ORDER BY event_id DESC LIMIT 1;")
        except Exception:
            tip = ""
        rec = AuditRecord(
            project_id=project_id, phase=phase,
            role="engineer", subsystem="build", action=action, actor=actor,
            subject_type=subject_type,
            subject_id=subject_id or f"build:{project_id}",
            rationale=rationale, metadata=metadata,
        )
        rec = chain_to_previous(rec, tip or None)
        write_via_psql(rec)
        return True
    except Exception:
        # Audit-write failure must not kill the dispatch/ingest call; the
        # project metadata IS the source of truth.
        return False


# ── PRD → Build Brief synthesis ────────────────────────────────────────


def _canonical_json(obj: Any) -> str:
    """Stable JSON encoding (sorted keys, compact) — used for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_prd(prd_dump: dict[str, Any] | None) -> PRDv1:
    """Round-trip the stored PRD draft through ``PRDv1.model_validate``.

    Raises BuildDispatchError(reason='no_validated_prd') when missing,
    error-tagged, or non-conforming.
    """
    if not isinstance(prd_dump, dict) or not prd_dump:
        raise BuildDispatchError(
            "no_validated_prd",
            "project.metadata.prd_draft is missing; run `spine intake <id>` first",
        )
    if "_error" in prd_dump:
        raise BuildDispatchError(
            "no_validated_prd",
            f"prd_draft is tagged with synthesis error: {prd_dump['_error']}",
        )
    try:
        return PRDv1.model_validate(prd_dump)
    except Exception as exc:  # noqa: BLE001 — surface schema reason to caller
        raise BuildDispatchError(
            "no_validated_prd",
            f"prd_draft failed PRDv1.model_validate(): {exc}",
        ) from exc


def _engineering_goals_from_prd(prd: PRDv1) -> list[dict[str, Any]]:
    """Build the engineering_goals list: one entry per MUST + any SHOULD with a clear delivery.

    Acceptance criteria refs are matched by id-prefix on the AC list — the
    intake_runner stamps `AC-MUST-<n>` for MUST-tied ACs, so an EG referencing
    `G-M-1` gets all AC ids whose statement mentions that goal text.
    """
    egs: list[dict[str, Any]] = []
    must = prd.goals.must or []
    should = prd.goals.should or []
    # Index ACs by their `then` text so we can do a substring match for goal
    # statements; the intake_runner uses "MUST item delivered: <statement>".
    ac_index: list[tuple[str, str]] = [(ac.id, ac.then or "") for ac in prd.acceptance_criteria]

    def _ac_refs_for(goal_statement: str) -> list[str]:
        refs: list[str] = []
        for ac_id, ac_then in ac_index:
            if not ac_then:
                continue
            if goal_statement.strip() and goal_statement.strip().lower() in ac_then.lower():
                refs.append(ac_id)
        return refs

    for i, g in enumerate(must, start=1):
        egs.append({
            "id": f"EG-{len(egs) + 1}",
            "from_goal": g.id,
            "tier": "MUST",
            "statement": g.statement,
            "acceptance_criteria_refs": _ac_refs_for(g.statement),
        })
    # SHOULD goals: only include when the statement is non-trivial. The intake
    # runner sometimes leaves the SHOULD list empty; if a statement is present
    # we treat it as "clear delivery" enough for an EG entry.
    for g in should:
        if not g.statement or not g.statement.strip():
            continue
        egs.append({
            "id": f"EG-{len(egs) + 1}",
            "from_goal": g.id,
            "tier": "SHOULD",
            "statement": g.statement,
            "acceptance_criteria_refs": _ac_refs_for(g.statement),
        })
    return egs


def _squad_from_metadata(meta: dict[str, Any]) -> list[str]:
    """Lift the squad composition from the intake's swarm hint when present."""
    intake = meta.get(METADATA_INTAKE_KEY) or {}
    answers = intake.get("answers") or {}
    sw = answers.get("swarm_composition")
    if isinstance(sw, list) and sw:
        return [str(x) for x in sw if str(x).strip()]
    return list(_DEFAULT_SQUAD)


def _work_item_type_from_project(project: dict[str, Any]) -> str:
    """Resolve a project's work_item_type.

    V28 added ``spine_lifecycle.project.work_item_type`` (backfilled
    'feature'). Older readers that loaded the row before this column
    existed will have no key — fall back to 'feature' to match the V28
    DEFAULT.
    """
    wit = project.get("work_item_type")
    if isinstance(wit, str) and wit in WORK_ITEM_TYPES:
        return wit
    # Also accept it being tucked under metadata (e.g. set by intake before
    # the column was populated).
    meta_wit = (project.get("metadata") or {}).get("work_item_type")
    if isinstance(meta_wit, str) and meta_wit in WORK_ITEM_TYPES:
        return meta_wit
    return "feature"


def _implementer_kind_from_metadata(meta: dict[str, Any]) -> ImplementerKind:
    intake = meta.get(METADATA_INTAKE_KEY) or {}
    answers = intake.get("answers") or {}
    candidate = answers.get("implementer_kind")
    if isinstance(candidate, str) and candidate in {"claude_code", "cursor", "aider", "openhands", "human"}:
        return candidate  # type: ignore[return-value]
    return DEFAULT_IMPLEMENTER_KIND


def _autonomy_tier_from_metadata(meta: dict[str, Any]) -> AutonomyTier:
    intake = meta.get(METADATA_INTAKE_KEY) or {}
    answers = intake.get("answers") or {}
    candidate = answers.get("autonomy_tier")
    if isinstance(candidate, str) and candidate in {"low", "medium", "high"}:
        return candidate  # type: ignore[return-value]
    return DEFAULT_AUTONOMY_TIER


def synthesize_build_brief(
    *,
    project: dict[str, Any],
    prd: PRDv1,
    actor: str,
    use_db_routing: bool = True,
) -> dict[str, Any]:
    """Build the Build Brief dict (build-brief-v1) from a validated PRD."""
    prd_dump = prd.model_dump(mode="json")
    prd_hash = _sha256(_canonical_json(prd_dump))
    egs = _engineering_goals_from_prd(prd)

    # Cross-cutting constraints lifted from intake answers when present.
    intake = project["metadata"].get(METADATA_INTAKE_KEY) or {}
    answers = intake.get("answers") or {}
    constraints: dict[str, list[str]] = {}
    for key in ("cross_platform", "output_formats", "install_method"):
        vals = answers.get(key)
        if isinstance(vals, list) and vals:
            constraints[key] = [str(v) for v in vals]
        elif isinstance(vals, str) and vals.strip():
            constraints[key] = [vals.strip()]

    # Wave-2: per-type pipeline + role-set routing + #13 implementer fields.
    work_item_type = _work_item_type_from_project(project)
    pipeline_id, type_role_set = route_for_work_item_type(work_item_type, use_db=use_db_routing)
    intake_role_set = _squad_from_metadata(project["metadata"])
    # Prefer the intake-declared squad when it diverges from the type
    # default (the user knows their project better than the registry).
    role_set = intake_role_set if intake_role_set != list(_DEFAULT_SQUAD) else type_role_set

    brief_id = f"brief_{project['project_uuid'][:8]}_{int(datetime.now(timezone.utc).timestamp())}"
    return {
        "version": BUILD_BRIEF_VERSION,
        "brief_id": brief_id,
        "project_id": project["project_uuid"],
        "project_name": project["name"],
        "pipeline_version": project["pipeline_version"],
        "work_item_type": work_item_type,
        "pipeline_id": pipeline_id,
        "role_set": role_set,
        "implementer_kind": _implementer_kind_from_metadata(project["metadata"]),
        "autonomy_tier": _autonomy_tier_from_metadata(project["metadata"]),
        "derived_from": {
            "prd_version": prd.version,
            "prd_hash": prd_hash,
        },
        "engineering_goals": egs,
        "scope_summary": {
            "in": list(prd.in_scope),
            "out": list(prd.out_of_scope),
        },
        "stakeholder_context": [
            {"name": s.name, "needs": s.needs} for s in prd.users_stakeholders
        ],
        "open_questions": [
            {"id": oq.id, "question": oq.question,
             "recommendation": oq.recommendation}
            for oq in prd.open_questions
        ],
        "constraints": constraints,
        "recommended_squad_composition": role_set,
        "next_steps_for_implementer": [
            "Pick up engineering_goals in priority order (MUST then SHOULD).",
            "Each commit should reference an EG-id in the message.",
            f"When done, run: spine build report {project['id']} --artifact <path>",
        ],
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": actor or "product",
            "status": "ready_for_implementer",
        },
    }


# ── Public entry points ────────────────────────────────────────────────


def dispatch_build(
    project_id: int | str,
    *,
    actor: str = "orchestrator",
) -> DispatchResult:
    """Synthesize + persist a Build Brief for ``project_id``.

    Refuses (raises BuildDispatchError(reason='no_validated_prd')) when
    the project lacks a validated PRD draft. Warns (in result.warnings)
    when TRD / Roadmap drafts are missing — those stories are deferred.
    """
    proj = _load_project(project_id)
    pid = proj["id"]

    prd = _validate_prd(proj["metadata"].get(METADATA_PRD_KEY))

    audit_count = 0
    audit_count += int(_write_audit(
        action=AUDIT_DISPATCHED, project_id=pid, actor=actor,
        metadata={"project_uuid": proj["project_uuid"],
                  "pipeline_version": proj["pipeline_version"]},
        subject_id=f"build:{pid}",
        rationale="orchestrator handing PRD off to Build via Build Brief",
    ))

    brief = synthesize_build_brief(project=proj, prd=prd, actor=actor)

    warnings: list[str] = []
    if not proj["metadata"].get(METADATA_TRD_KEY):
        warnings.append("no_trd_draft: TRD synthesis is deferred (next epic). "
                        "Engineering goals derive from PRD only.")
    if not proj["metadata"].get(METADATA_ROADMAP_KEY):
        warnings.append("no_roadmap_draft: roadmap decomposition is deferred. "
                        "Sequence engineering_goals manually.")

    # Clean overwrite of build_brief only — preserves intake/prd_draft/etc.
    _merge_metadata(pid, {METADATA_BRIEF_KEY: brief})

    audit_count += int(_write_audit(
        action=AUDIT_BRIEF_PERSISTED, project_id=pid, actor=actor,
        metadata={
            "brief_id": brief["brief_id"],
            "engineering_goals_count": len(brief["engineering_goals"]),
            "prd_hash": brief["derived_from"]["prd_hash"],
            "warnings": warnings,
        },
        subject_id=brief["brief_id"],
    ))

    return DispatchResult(
        project_id=pid,
        brief_id=brief["brief_id"],
        engineering_goals_count=len(brief["engineering_goals"]),
        warnings=warnings,
        audit_event_count=audit_count,
    )


def ingest_build_artifact(
    project_id: int | str,
    artifact: dict[str, Any] | BuildArtifact,
    *,
    actor: str = "build",
) -> IngestResult:
    """Validate + persist a BuildArtifact for ``project_id``.

    Refuses with BuildCompletionError(reason=...) when:
      * the project lacks a build_brief (`no_build_brief`)
      * the artifact's project_id doesn't match (`project_id_mismatch`)
      * an EG id referenced by the artifact isn't in the brief (`unknown_engineering_goal_ref`)
    """
    proj = _load_project(project_id)
    pid = proj["id"]

    brief = proj["metadata"].get(METADATA_BRIEF_KEY)
    if not isinstance(brief, dict) or not brief:
        raise BuildCompletionError(
            "no_build_brief",
            f"project {project_id!r} has no metadata.build_brief; "
            "run `build_dispatch` (or `spine build brief <id>` to inspect) first",
        )

    # Validate via the schema's own validator — refuse-to-seal etc fire here.
    if isinstance(artifact, BuildArtifact):
        validated = artifact
    else:
        try:
            validated = BuildArtifact.model_validate(artifact)
        except Exception as exc:  # noqa: BLE001 — schema is the authority
            raise BuildCompletionError(
                "invalid_artifact",
                f"BuildArtifact.model_validate failed: {exc}",
            ) from exc

    # Cross-check project_id. The brief stores the project UUID; an inbound
    # artifact may carry either the UUID or the BIGINT — accept both, reject
    # everything else so a copy/paste mistake doesn't silently land in the
    # wrong project.
    allowed_pids = {proj["project_uuid"], str(pid), proj["name"]}
    if validated.project_id not in allowed_pids:
        raise BuildCompletionError(
            "project_id_mismatch",
            f"artifact.project_id={validated.project_id!r} does not match "
            f"project (id={pid}, uuid={proj['project_uuid']}, name={proj['name']!r})",
        )

    # Reject unknown engineering_goal refs. The artifact references EGs via
    # metadata or via rationale; for v1 we look in two places: top-level
    # `metadata.engineering_goal_refs` on ArtifactMetadata (treated as a list
    # if present) AND each test_record / code_change can hint via path.
    known_eg_ids: set[str] = {eg["id"] for eg in (brief.get("engineering_goals") or [])}
    referenced: list[str] = []
    meta_extra = getattr(validated.metadata, "model_extra", None) or {}
    eg_refs = meta_extra.get("engineering_goal_refs")
    if isinstance(eg_refs, list):
        referenced.extend(str(x) for x in eg_refs)
    unknown = [r for r in referenced if r not in known_eg_ids]
    if unknown:
        raise BuildCompletionError(
            "unknown_engineering_goal_ref",
            f"artifact references engineering_goals not in brief: {sorted(set(unknown))}; "
            f"brief has: {sorted(known_eg_ids)}",
        )

    audit_count = 0
    audit_count += int(_write_audit(
        action=AUDIT_COMPLETED_RECEIVED, project_id=pid, actor=actor,
        metadata={
            **validated.to_audit_metadata(),
            "brief_id": brief.get("brief_id"),
        },
        subject_id=str(validated.artifact_uuid),
        rationale=validated.rationale[:500] if validated.rationale else None,
    ))

    artifact_dump = validated.model_dump(mode="json")
    artifact_hash = _sha256(_canonical_json(artifact_dump))

    # Append-to-history pattern: read current history, push the new entry,
    # write back. Done inside one psql update so we don't race ourselves.
    # We re-fetch metadata to pick up any other concurrent merges (defensive;
    # in practice this runs single-threaded under the MCP server).
    proj_refresh = _load_project(pid)
    history = list(proj_refresh["metadata"].get(METADATA_HISTORY_KEY) or [])
    history.append({
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "artifact_uuid": str(validated.artifact_uuid),
        "artifact_hash": artifact_hash,
        "directive_id": validated.directive_id,
        "status": validated.status,
        "summary": validated.compute_diff_summary(),
    })

    _merge_metadata(pid, {
        METADATA_ARTIFACT_KEY: artifact_dump,
        METADATA_HISTORY_KEY: history,
    })

    audit_count += int(_write_audit(
        action=AUDIT_ARTIFACT_PERSISTED, project_id=pid, actor=actor,
        metadata={
            "artifact_uuid": str(validated.artifact_uuid),
            "artifact_hash": artifact_hash,
            "history_length": len(history),
            "code_changes_count": len(validated.code_changes),
            "tests_added": len(validated.tests_added),
            "tests_run": len(validated.tests_run),
            "ready_for_verify": True,
        },
        subject_id=str(validated.artifact_uuid),
    ))

    return IngestResult(
        project_id=pid,
        artifact_uuid=str(validated.artifact_uuid),
        artifact_hash=artifact_hash,
        code_changes_count=len(validated.code_changes),
        ready_for_verify=True,
        history_length=len(history),
        audit_event_count=audit_count,
    )


__all__ = [
    "AUDIT_ARTIFACT_PERSISTED",
    "AUDIT_BRIEF_PERSISTED",
    "AUDIT_COMPLETED_RECEIVED",
    "AUDIT_DISPATCHED",
    "BUILD_BRIEF_VERSION",
    "DEFAULT_AUTONOMY_TIER",
    "DEFAULT_IMPLEMENTER_KIND",
    "AutonomyTier",
    "BuildBrief",
    "BuildCompletionError",
    "BuildDispatchError",
    "DispatchResult",
    "ImplementerKind",
    "IngestResult",
    "METADATA_ARTIFACT_KEY",
    "METADATA_BRIEF_KEY",
    "METADATA_HISTORY_KEY",
    "METADATA_PRD_KEY",
    "METADATA_ROADMAP_KEY",
    "METADATA_TRD_KEY",
    "dispatch_build",
    "ingest_build_artifact",
    "route_for_work_item_type",
    "synthesize_build_brief",
]
