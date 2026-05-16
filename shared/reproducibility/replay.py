"""Replay engine (STORY-3.2.2).

Take a RunManifest captured by `capture_manifest` and recreate the run.
Replay is intentionally "best-effort against current code": we warn (or
fail under `force_drift=False`) when any input has changed since capture.

Replay path:
    1. Format-version check.
    2. Drift detection: pipeline_version, role_prompt_sha, skills, git HEAD.
    3. Build dispatch payload from captured inputs (+ optional model override).
    4. Dispatch via `orchestrator/lib/router.sh dispatch` subprocess
       (the FR-5 chokepoint), or short-circuit when dry_run=True.
    5. Compare new output hash vs original (when present) and return
       a ReplayResult.

Stack: stdlib + Pydantic v2. No new deps. Side effects via subprocess so
unit tests can monkeypatch `_dispatch`.
"""
from __future__ import annotations
import os, subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from shared.reproducibility.manifest import (RunManifest, _esc, _git, _psql,
                                             _sha256_file)

ROUTER_SH = Path(__file__).resolve().parents[2] / "orchestrator" / "lib" / "router.sh"
SUPPORTED_FORMATS = {"1"}
CRITICAL_DRIFT = {"role_prompt_drifted", "pipeline_manifest_drifted",
                  "pipeline_version_drifted"}
_PYD = ConfigDict(extra="forbid", protected_namespaces=())
_now = lambda: datetime.now(timezone.utc)


class ReplayPlan(BaseModel):
    """Dry-run output: what `replay()` would do without doing it."""
    model_config = _PYD
    manifest_uuid: UUID
    drift_summary: list[str] = Field(default_factory=list)
    payload_preview: dict[str, Any]
    would_dispatch: bool


class ReplayResult(BaseModel):
    """Outcome of an actual replay attempt."""
    model_config = _PYD
    manifest_uuid: UUID
    replayed_at: datetime = Field(default_factory=_now)
    success: bool
    new_directive_id: Optional[str] = None
    original_output_hash: Optional[str] = None
    new_output_hash: Optional[str] = None
    output_drift: bool = False
    drift_summary: list[str] = Field(default_factory=list)
    error: Optional[str] = None


# ─── Drift detection ────────────────────────────────────────────────────────

def detect_drift(manifest: RunManifest) -> list[str]:
    """Compare manifest vs current repo/DB. Tags: role_prompt_drifted,
    pipeline_manifest_drifted, pipeline_version_drifted, git_head_drifted,
    skills_drifted, git_dirty."""
    drift: list[str] = []
    cur_role = _sha256_file(Path(manifest.role.role_prompt_path)) or ""
    if cur_role and cur_role != manifest.role.role_prompt_sha256:
        drift.append("role_prompt_drifted")
    cur_pipe = _sha256_file(Path(manifest.pipeline.pipeline_manifest_path)) or ""
    if cur_pipe and cur_pipe != manifest.pipeline.pipeline_sha256:
        drift.append("pipeline_manifest_drifted")
    cur_ver = _psql("SELECT pipeline_version FROM spine_lifecycle.project "
                    f"WHERE id::text = '{_esc(manifest.project_id)}' LIMIT 1;")
    if cur_ver and cur_ver != manifest.pipeline.pipeline_version:
        drift.append("pipeline_version_drifted")
    cur_head = _git("rev-parse", "HEAD")
    if cur_head and cur_head != manifest.git_state.commit_sha:
        drift.append("git_head_drifted")
    if (_git("status", "--porcelain") or "").strip():
        drift.append("git_dirty")
    try:
        from shared.skills.registry import discover_skills
        live = {s: str(sk.version) for s, sk in discover_skills().items()}
    except ImportError:
        live = {}
    if live and live != manifest.role.skills_versions:
        drift.append("skills_drifted")
    return drift


# ─── Dispatch ───────────────────────────────────────────────────────────────

def _phase_to_subsystem(phase: str) -> str:
    """Cheap fallback; canonical map is router.sh route_decide_subsystem."""
    if phase.startswith(("plan", "intake", "prd", "trd")): return "plan"
    if phase.startswith(("verify", "qa", "audit")): return "verify"
    return "build"

def _build_payload(manifest: RunManifest,
                   override_model: Optional[str] = None) -> dict[str, Any]:
    """Compose router.sh CLI args + captured directive text."""
    return {"subsystem": _phase_to_subsystem(manifest.phase),
            "role": manifest.role.role_name,
            "directive": manifest.inputs.directive_text,
            "project_id": manifest.project_id,
            "model_override": override_model or manifest.runtime.model_id,
            "pipeline_version": manifest.pipeline.pipeline_version}

def _dispatch(payload: dict[str, Any]) -> tuple[bool, Optional[str], Optional[str]]:
    """Invoke `router.sh dispatch ...`. Returns (success, directive_id, error)."""
    if not ROUTER_SH.exists():
        return False, None, f"router.sh missing at {ROUTER_SH}"
    try:
        r = subprocess.run(
            [str(ROUTER_SH), "dispatch", payload["subsystem"], payload["role"],
             payload["directive"], payload["project_id"]],
            capture_output=True, text=True, timeout=120, check=False,
            env={**os.environ, "SPINE_MODEL_OVERRIDE": payload["model_override"]})
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, None, f"dispatch failed: {e}"
    if r.returncode != 0:
        return False, None, r.stderr.strip() or f"router.sh exit {r.returncode}"
    out, did = r.stdout.strip(), None
    for tok in ('"directive_id":"', "'directive_id':'"):
        if tok in out:
            did = out.split(tok, 1)[1].split('"', 1)[0].split("'", 1)[0]
            break
    return True, did, None

def _fetch_output_hash(directive_id: str) -> Optional[str]:
    """Most recent audit_event.output_hash for a directive (post-completion)."""
    return _psql("SELECT output_hash FROM spine_audit.audit_event "
                 f"WHERE subject_id = '{_esc(directive_id)}' "
                 "AND output_hash IS NOT NULL ORDER BY ts DESC LIMIT 1;")


# ─── Public entry point ─────────────────────────────────────────────────────

def replay(manifest: RunManifest, *, dry_run: bool = False,
           force_drift: bool = False,
           override_model: Optional[str] = None) -> ReplayResult | ReplayPlan:
    """Recreate the run captured in `manifest`. See module docstring."""
    if manifest.format_version not in SUPPORTED_FORMATS:
        return ReplayResult(manifest_uuid=manifest.manifest_uuid, success=False,
                            error=f"unsupported format_version "
                                  f"{manifest.format_version!r}")

    drift = detect_drift(manifest)
    has_critical = bool(set(drift) & CRITICAL_DRIFT)
    payload = _build_payload(manifest, override_model=override_model)

    if dry_run:
        return ReplayPlan(manifest_uuid=manifest.manifest_uuid,
                          drift_summary=drift, payload_preview=payload,
                          would_dispatch=(force_drift or not has_critical))

    if has_critical and not force_drift:
        return ReplayResult(manifest_uuid=manifest.manifest_uuid, success=False,
                            drift_summary=drift, output_drift=True,
                            error=f"critical drift blocks replay: "
                                  f"{sorted(set(drift) & CRITICAL_DRIFT)}; "
                                  f"rerun with force_drift=True to override")

    original_hash = manifest.metadata.get("output_hash") \
        or _fetch_output_hash(manifest.directive_id)
    ok, new_did, err = _dispatch(payload)
    if not ok:
        return ReplayResult(manifest_uuid=manifest.manifest_uuid, success=False,
                            drift_summary=drift, error=err)

    new_hash = _fetch_output_hash(new_did) if new_did else None
    return ReplayResult(
        manifest_uuid=manifest.manifest_uuid, success=True,
        new_directive_id=new_did,
        original_output_hash=original_hash, new_output_hash=new_hash,
        output_drift=bool(original_hash and new_hash and original_hash != new_hash),
        drift_summary=drift)


def validate_against_current(manifest: RunManifest) -> tuple[bool, list[str]]:
    """No-op replay: just report drift. (True, []) iff reproducible now."""
    drift = detect_drift(manifest)
    return (not bool(set(drift) & CRITICAL_DRIFT), drift)


__all__ = ["ReplayPlan", "ReplayResult", "replay", "detect_drift",
           "validate_against_current", "CRITICAL_DRIFT"]
