"""RunManifest schema + capture/load (STORY-3.2.1).

A RunManifest is the YAML/JSON record of EVERY input that fed a Spine
directive: directive text, PRD/TRD refs, pipeline version, role prompt,
active skills, model selection, git state, dependency lockfile shas. Hand
it to `replay()` to recreate the run, the way a Dockerfile + base image
recreates a container image.

Storage layout: one manifest per directive completion at
`~/.spine/manifests/<project_uuid>/<directive_id>.yaml`. Append-only.

Stack: stdlib + Pydantic v2 + PyYAML. psql + git via subprocess so this
file has zero runtime deps beyond the SDK.
"""
from __future__ import annotations
import hashlib, json, os, subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_DB_URL = os.environ.get("SPINE_DB_URL", "postgresql://spine:spine@localhost:33000/spine")
SPINE_HOME = Path(os.environ.get("SPINE_HOME", str(Path.home() / ".spine")))
MANIFESTS_ROOT = SPINE_HOME / "manifests"
_PYD = ConfigDict(extra="forbid", str_strip_whitespace=True, protected_namespaces=())
_now = lambda: datetime.now(timezone.utc)
_esc = lambda s: s.replace("'", "''")


_SUBPROC_EX = (subprocess.CalledProcessError, subprocess.TimeoutExpired,
               FileNotFoundError)

def _sha256_text(text: str) -> str:
    """Hex SHA-256 of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _sha256_file(path: Path) -> Optional[str]:
    """Hex SHA-256 of a file's bytes, or None if missing/unreadable."""
    try: return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError: return None

def _psql(sql: str, db_url: Optional[str] = None) -> Optional[str]:
    """Single-row psql query; None on any failure (DB optional for capture)."""
    try:
        r = subprocess.run(["psql", db_url or DEFAULT_DB_URL, "-At", "-F", "|",
                            "-v", "ON_ERROR_STOP=1", "-c", sql],
                           capture_output=True, text=True, timeout=10, check=True)
    except _SUBPROC_EX: return None
    return r.stdout.strip() or None

def _git(*args: str) -> Optional[str]:
    """git subcommand from cwd; None on failure (not a repo, no git, etc.)."""
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True,
                           timeout=10, check=True)
    except _SUBPROC_EX: return None
    return r.stdout.strip()


class InputsRef(BaseModel):
    """Textual inputs to the directive, with content shas for verification."""
    model_config = _PYD
    directive_text: str
    directive_sha256: str
    prd_ref: Optional[str] = None;       prd_sha256: Optional[str] = None
    trd_ref: Optional[str] = None;       trd_sha256: Optional[str] = None
    roadmap_ref: Optional[str] = None;   roadmap_sha256: Optional[str] = None
    org_bundle_id: Optional[str] = None; org_bundle_sha256: Optional[str] = None
    intake_template_ref: Optional[str] = None

class PipelineRef(BaseModel):
    """Locked pipeline manifest the project was started against (EPIC-1.7.5)."""
    model_config = _PYD
    pipeline_manifest_path: str
    pipeline_version: str
    pipeline_sha256: str

class RoleRef(BaseModel):
    """Role prompt + skill set fired at directive time (STORY-4.1.x)."""
    model_config = _PYD
    role_name: str
    role_prompt_path: str
    role_prompt_sha256: str
    skills_active: list[str] = Field(default_factory=list)
    skills_versions: dict[str, str] = Field(default_factory=dict)

class RuntimeRef(BaseModel):
    """Model + sampling params chosen by the cost router (REQ-INIT-1 FR-6)."""
    model_config = _PYD
    model_id: str
    model_provider: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

class GitState(BaseModel):
    """git HEAD + working-tree cleanliness at capture time."""
    model_config = _PYD
    commit_sha: str
    branch: str
    dirty: bool = False
    dirty_files: list[str] = Field(default_factory=list)

class DependencyState(BaseModel):
    """Lockfile shas — python (uv/poetry/pip-tools) + node (pnpm/yarn/npm)."""
    model_config = _PYD
    python_packages_lockfile_sha: Optional[str] = None
    node_packages_lockfile_sha: Optional[str] = None

class RunManifest(BaseModel):
    """One reproducible-build record for a single Spine directive run."""
    model_config = _PYD
    manifest_uuid: UUID = Field(default_factory=uuid4)
    format_version: Literal["1"] = "1"
    created_at: datetime = Field(default_factory=_now)
    project_id: str
    phase: str
    directive_id: str
    inputs: InputsRef
    pipeline: PipelineRef
    role: RoleRef
    runtime: RuntimeRef
    git_state: GitState
    dependencies: DependencyState = Field(default_factory=DependencyState)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ─── Capture ────────────────────────────────────────────────────────────────

def _git_state() -> GitState:
    """git HEAD + branch + porcelain dirty list; ('unknown', 'unknown') on miss."""
    head = _git("rev-parse", "HEAD") or "unknown"
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    dirty_files = [ln[3:] for ln in (_git("status", "--porcelain") or "").splitlines() if ln]
    return GitState(commit_sha=head, branch=branch,
                    dirty=bool(dirty_files), dirty_files=dirty_files)


def _first_lock_sha(names: tuple[str, ...]) -> Optional[str]:
    """sha of the first present file in `names`; None if none exist."""
    return next((s for s in (_sha256_file(Path(n)) for n in names) if s), None)

_CTX_KEYS = ("project_id", "phase", "role", "pipeline_version",
             "pipeline_manifest_path", "org_bundle")

def _query_directive_context(directive_id: str, db_url: Optional[str]
                             ) -> dict[str, Optional[str]]:
    """project_id, phase, role, pipeline_version+path, org_bundle for a directive."""
    raw = _psql("SELECT rh.project_id::text, rh.phase, rh.role, "
                "p.pipeline_version, p.pipeline_manifest_path, p.org_bundle "
                "FROM spine_lifecycle.route_history rh "
                "JOIN spine_lifecycle.project p ON p.id = rh.project_id "
                f"WHERE rh.directive_ref = '{_esc(directive_id)}' LIMIT 1;", db_url)
    if not raw: return {}
    return dict(zip(_CTX_KEYS, (raw.split("|") + [None] * 6)[:6]))

def _query_model_decision(directive_id: str, db_url: Optional[str]
                          ) -> tuple[Optional[str], Optional[str]]:
    """(model_id, provider) from the most recent llm_call audit_event."""
    raw = _psql("SELECT metadata->>'model', metadata->>'provider' "
                "FROM spine_audit.audit_event "
                f"WHERE subject_id = '{_esc(directive_id)}' "
                "AND action = 'llm_call' ORDER BY ts DESC LIMIT 1;", db_url)
    if not raw: return None, None
    parts = (raw.split("|") + [None, None])[:2]
    return parts[0], parts[1]

def _active_skills() -> tuple[list[str], dict[str, str]]:
    """Scan shared/skills registry. Empty (no error) if registry unavailable."""
    try: from shared.skills.registry import discover_skills
    except ImportError: return [], {}
    reg = discover_skills()
    return sorted(reg.keys()), {s: str(sk.version) for s, sk in reg.items()}


def capture_manifest(directive_id: str, *, directive_text: str = "",
                     role_prompt_path: Optional[str] = None,
                     db_url: Optional[str] = None,
                     extra_metadata: Optional[dict[str, Any]] = None
                     ) -> RunManifest:
    """Build a RunManifest from live DB + filesystem + git state.

    Best-effort: missing DB rows produce 'unknown' refs (still a valid
    manifest). Caller may pass `directive_text` when not in the audit log.
    """
    ctx = _query_directive_context(directive_id, db_url)
    model_id, provider = _query_model_decision(directive_id, db_url)
    pipe_path = ctx.get("pipeline_manifest_path") or ""
    role_name = ctx.get("role") or "unknown"
    rprompt = role_prompt_path or f"shared/charters/{role_name}.md"
    skills, sk_versions = _active_skills()

    return RunManifest(
        project_id=ctx.get("project_id") or "unknown",
        phase=ctx.get("phase") or "unknown",
        directive_id=directive_id,
        inputs=InputsRef(directive_text=directive_text,
                         directive_sha256=_sha256_text(directive_text),
                         org_bundle_id=ctx.get("org_bundle")),
        pipeline=PipelineRef(
            pipeline_manifest_path=pipe_path or "unknown",
            pipeline_version=ctx.get("pipeline_version") or "unknown",
            pipeline_sha256=(_sha256_file(Path(pipe_path)) if pipe_path else "") or ""),
        role=RoleRef(role_name=role_name, role_prompt_path=rprompt,
                     role_prompt_sha256=_sha256_file(Path(rprompt)) or "",
                     skills_active=skills, skills_versions=sk_versions),
        runtime=RuntimeRef(model_id=model_id or "unknown",
                           model_provider=provider or "unknown"),
        git_state=_git_state(),
        dependencies=DependencyState(
            python_packages_lockfile_sha=_first_lock_sha(
                ("uv.lock", "poetry.lock", "requirements.lock", "requirements.txt")),
            node_packages_lockfile_sha=_first_lock_sha(
                ("pnpm-lock.yaml", "yarn.lock", "package-lock.json"))),
        metadata=extra_metadata or {})


# ─── Persist ────────────────────────────────────────────────────────────────

def save_manifest(manifest: RunManifest, output_path: Path) -> Path:
    """Write a manifest as YAML (.yaml/.yml) or JSON; default YAML by ext."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(manifest.model_dump_json())
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    else:
        output_path.write_text(yaml.safe_dump(payload, sort_keys=True,
                                              default_flow_style=False))
    return output_path


def load_manifest(path: Path) -> RunManifest:
    """Parse a manifest file (YAML or JSON) back into a RunManifest."""
    text = path.read_text(encoding="utf-8")
    raw = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: manifest root must be a mapping")
    return RunManifest.model_validate(raw)


def default_manifest_path(project_uuid: str, directive_id: str) -> Path:
    """`~/.spine/manifests/<project>/<directive>.yaml` — capture default."""
    return MANIFESTS_ROOT / project_uuid / f"{directive_id}.yaml"
