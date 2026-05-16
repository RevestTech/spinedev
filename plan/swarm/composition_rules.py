"""
Per-project-type swarm composition rules.

Implements `STORY-1.2.2` (composition rules in `sdlc-pipeline.yaml`) by
reading `plan/artifacts/sdlc-pipeline-default.yaml` and applying the
override hierarchy (org bundle → team → project) per PRD §FR-7.

Defaults from REQ-INIT-1 FR-3:
  - web-app        → researcher + engineer + operator + qa
  - internal-tool  → researcher + engineer + qa
  - data-pipeline  → researcher + engineer + datawright + operator
  - mobile         → researcher + engineer + qa + operator (distribution)
  - api-service    → researcher + engineer + qa + operator
  - cli-tool       → researcher + engineer + qa
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml  # type: ignore[import-untyped]

from .scout_contribution import ScoutRole

DEFAULT_PIPELINE_PATH = (
    Path(__file__).resolve().parent.parent / "artifacts" / "sdlc-pipeline-default.yaml"
)

# Fallback when YAML is missing (e.g. inside a unit test). Both _ and -
# spellings accepted so callers can pass either ProjectType.value or the
# pipeline-YAML key. Keeps the swarm resolvable in any environment.
_BASE_FB: dict[str, list[str]] = {
    "web-app":       ["researcher", "engineer", "operator", "qa"],
    "internal-tool": ["researcher", "engineer", "qa"],
    "data-pipeline": ["researcher", "engineer", "datawright", "operator"],
    "mobile":        ["researcher", "engineer", "qa", "operator"],
    "api-service":   ["researcher", "engineer", "qa", "operator"],
    "cli-tool":      ["researcher", "engineer", "qa"],
    "custom":        ["researcher", "engineer", "qa"],
}
_FALLBACK_COMPOSITION: dict[str, list[str]] = {
    **_BASE_FB, **{k.replace("-", "_"): v for k, v in _BASE_FB.items()},
}


@lru_cache(maxsize=4)
def load_pipeline(path: Optional[str] = None) -> dict[str, Any]:
    """Load + cache the SDLC pipeline YAML. Pass `path=''` to bypass cache."""
    p = Path(path) if path else DEFAULT_PIPELINE_PATH
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _normalize(roles: Iterable[str]) -> list[ScoutRole]:
    """Coerce string role names into ScoutRole; drop unknowns."""
    out: list[ScoutRole] = []
    for r in roles:
        try:
            out.append(ScoutRole(r.lower()))
        except ValueError:
            continue
    return out


def get_swarm_for(
    project_type: str,
    pipeline: Optional[dict[str, Any]] = None,
    org_overrides: Optional[dict[str, list[str]]] = None,
) -> list[ScoutRole]:
    """Resolve the scout roster for `project_type`.

    Override precedence (most specific wins):
      1. `org_overrides[project_type]` (caller-supplied, e.g. team bundle)
      2. `pipeline.project_types[project_type].swarm_override`
      3. `_FALLBACK_COMPOSITION[project_type]`
    """
    key = (project_type or "custom").strip()
    if org_overrides and key in org_overrides:
        return _normalize(org_overrides[key])

    pipe = pipeline if pipeline is not None else load_pipeline()
    project_types = (pipe.get("project_types") or {}) if pipe else {}
    entry = project_types.get(key) or project_types.get(key.replace("_", "-"))
    if entry and isinstance(entry, dict):
        override = entry.get("swarm_override")
        if override:
            return _normalize(override)

    fallback = _FALLBACK_COMPOSITION.get(key) or _FALLBACK_COMPOSITION.get(
        key.replace("_", "-")
    ) or _FALLBACK_COMPOSITION["custom"]
    return _normalize(fallback)


__all__ = ["DEFAULT_PIPELINE_PATH", "get_swarm_for", "load_pipeline"]
