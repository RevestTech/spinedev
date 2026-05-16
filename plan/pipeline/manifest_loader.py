"""manifest_loader.py — resolve the effective SDLC pipeline manifest.

Implements `STORY-1.7.3` (override hierarchy: org bundle → team → project, each
level only editing what it's authorized to edit) from `docs/BACKLOG.md`. Backs
PRD REQ-INIT-1 FR-7 in `docs/PRD.md`. The default manifest ships at
`plan/artifacts/sdlc-pipeline-default.yaml`; org bundles overlay surgical edits
via their `pipeline_overrides` section (see `shared/standards/bundle-schema.yaml`).
Team + project overlays sit on disk under `~/.spine/active/team|project/<id>/`.

Merge semantics (FR-7):
  - `phases`: append by id, modify by id, remove by id (order preserved).
  - `project_types`: append + modify by type id.
  - `tier_routing`: shallow merge per-section (per_phase_defaults / budget_caps).
  - `gates`: per-phase override (deep-merge into the matching phase's gate).
  - `capabilities`: org bundle is authoritative — sub-bundles MAY narrow grants,
    NEVER widen (no new principals, no new capability keys).

A `resolved_version` (sha256 of canonical JSON) + `inheritance_chain` are stamped
onto the returned manifest so callers can pin to + audit the exact composition.
"""
from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_PIPELINE_PATH = (
    Path(__file__).resolve().parent.parent / "artifacts" / "sdlc-pipeline-default.yaml"
)


class PipelineManifest(BaseModel):
    """Resolved pipeline after applying the override hierarchy."""

    model_config = ConfigDict(extra="allow")

    version: int
    org_bundle: str
    phases: list[dict[str, Any]]
    project_types: dict[str, Any] = Field(default_factory=dict)
    tier_routing: dict[str, Any] = Field(default_factory=dict)
    overrides: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    audit: dict[str, Any] = Field(default_factory=dict)
    resolved_version: str = ""
    inheritance_chain: list[str] = Field(default_factory=list)


def _spine_home() -> Path:
    return Path(os.environ.get("SPINE_HOME", str(Path.home() / ".spine")))


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _canonical(obj: Any) -> str:
    """Sort-keyed, comma-tight JSON — deterministic across hosts."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _phases_apply(base: list[dict[str, Any]], po: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply append/modify/remove to the ordered phase list (by `id`)."""
    out = [deepcopy(p) for p in base]
    out = [p for p in out if p.get("id") not in set((po or {}).get("remove") or [])]
    for pid, patch in ((po or {}).get("modify") or {}).items():
        for p in out:
            if p.get("id") == pid: _deep_merge(p, patch)
    for new in (po or {}).get("append") or []:
        if not any(p.get("id") == new.get("id") for p in out): out.append(deepcopy(new))
    return out


def _gates_apply(phases: list[dict[str, Any]], gates: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-phase gate override — deep-merge into phase.gate."""
    for pid, gate_patch in (gates or {}).items():
        for p in phases:
            if p.get("id") == pid:
                p.setdefault("gate", {}); _deep_merge(p["gate"], gate_patch)
    return phases


def _project_types_apply(base: dict[str, Any], po: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base or {})
    for new in (po or {}).get("append") or []:
        tid = new.get("id") if isinstance(new, dict) and "id" in new else None
        if tid and tid not in out: out[tid] = {k: v for k, v in new.items() if k != "id"}
    for tid, patch in ((po or {}).get("modify") or {}).items():
        out.setdefault(tid, {}); _deep_merge(out[tid], patch)
    return out


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """Recursive in-place dict merge; src wins on scalar/list collisions."""
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = deepcopy(v)


def _capabilities_narrow(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Sub-bundles may only NARROW — drop principals, keep capability shape."""
    if not overlay:
        return deepcopy(base or {})
    out = deepcopy(base or {})
    base_grants = (base or {}).get("grants") or {}
    ov_grants = (overlay or {}).get("grants") or {}
    narrowed: dict[str, list[str]] = {}
    for cap, base_principals in base_grants.items():
        if cap not in ov_grants:
            narrowed[cap] = list(base_principals or [])
            continue
        ov_set = set(ov_grants[cap] or [])
        narrowed[cap] = [p for p in (base_principals or []) if p in ov_set]
    out["grants"] = narrowed
    return out


def _apply_overlay(merged: dict[str, Any], overlay: dict[str, Any], chain_tag: str,
                   chain: list[str]) -> dict[str, Any]:
    """Apply one bundle-shaped overlay (`pipeline_overrides`) onto the manifest."""
    if not overlay:
        return merged
    po = overlay.get("pipeline_overrides") or overlay  # also accept partial<manifest>
    if po.get("phases"):
        merged["phases"] = _phases_apply(merged.get("phases") or [], po["phases"])
    if po.get("project_types"):
        merged["project_types"] = _project_types_apply(merged.get("project_types") or {}, po["project_types"])
    if po.get("tier_routing"):
        merged.setdefault("tier_routing", {})
        _deep_merge(merged["tier_routing"], po["tier_routing"])
    if po.get("gates"):
        merged["phases"] = _gates_apply(merged.get("phases") or [], po["gates"])
    if "capabilities" in overlay:
        merged["capabilities"] = _capabilities_narrow(merged.get("capabilities") or {}, overlay["capabilities"])
    chain.append(chain_tag)
    return merged


def _active_bundle(bundle_id: Optional[str]) -> dict[str, Any]:
    home = _spine_home()
    if bundle_id:
        path = home / "bundles" / bundle_id / "bundle.yaml"
        return _read_yaml(path)
    active_link = home / "active" / "bundle.yaml"
    return _read_yaml(active_link)


def _team_overrides(project_id: Optional[str]) -> dict[str, Any]:
    if not project_id:
        return {}
    home = _spine_home()
    proj_meta = _read_yaml(home / "active" / "project" / project_id / "meta.yaml")
    team_id = proj_meta.get("team_id") if isinstance(proj_meta, dict) else None
    if not team_id:
        return {}
    return _read_yaml(home / "active" / "team" / team_id / "pipeline_overrides.yaml")


def load_pipeline(*, project_id: Optional[str] = None, bundle_id: Optional[str] = None,
                  project_overrides: Optional[dict[str, Any]] = None) -> PipelineManifest:
    """Resolve the effective pipeline manifest for a project + bundle.

    Returns a `PipelineManifest` carrying `resolved_version` (sha256 over the
    canonical JSON of the merged manifest, excluding the chain itself) and
    `inheritance_chain` listing the overlays applied in order.
    """
    merged = deepcopy(_read_yaml(DEFAULT_PIPELINE_PATH))
    chain: list[str] = ["default:sdlc-pipeline-default.yaml"]
    bundle = _active_bundle(bundle_id)
    if bundle:
        bid = (bundle.get("identity") or {}).get("bundle_id") or bundle_id or "active"
        _apply_overlay(merged, bundle, f"org-bundle:{bid}", chain)
    team_ov = _team_overrides(project_id)
    if team_ov:
        _apply_overlay(merged, team_ov, f"team:{project_id}", chain)
    if project_overrides:
        _apply_overlay(merged, project_overrides, f"project:{project_id or 'inline'}", chain)
    canonical = _canonical({k: v for k, v in merged.items()
                            if k not in {"resolved_version", "inheritance_chain"}})
    merged["resolved_version"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    merged["inheritance_chain"] = chain
    return PipelineManifest(**merged)


__all__ = ["DEFAULT_PIPELINE_PATH", "PipelineManifest", "load_pipeline"]
