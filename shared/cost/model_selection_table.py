"""Model selection table (STORY-3.3.2; REQ-INIT-1 FR-6 EPIC-3.3).

A (role, complexity-bucket) → preferred-tier lookup that sits between the
complexity scorer and the cost router. The default table ships in
`default_model_selection.yaml`; org bundles may override individual
entries via `bundle.cost.model_selection_table`.

Composition contract (most-specific wins):

    default_model_selection.yaml
        ⊕ bundle.cost.model_selection_table          (per-entry override)
        ⊕ team_router request user_override_tier     (skip table entirely)

Cross-refs: `STORY-3.3.2`, `shared/cost/complexity_scorer.py`,
`shared/cost/router.py`, `shared/standards/bundle-schema.yaml`.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.cost.router import Tier, _load_active_bundle

_PYD_CONFIG = ConfigDict(protected_namespaces=())

ComplexityName = Literal["trivial", "simple", "moderate", "complex",
                         "very_complex"]
_ALL_COMPLEXITIES: tuple[ComplexityName, ...] = (
    "trivial", "simple", "moderate", "complex", "very_complex")
_TIER_RANK = {"low": 0, "medium": 1, "high": 2, "premium": 3}

_DEFAULT_TABLE_PATH = Path(__file__).parent / "default_model_selection.yaml"


# ── Models ───────────────────────────────────────────────────────────────────
class SelectionEntry(BaseModel):
    model_config = _PYD_CONFIG
    role: str
    complexity: ComplexityName
    preferred_tier: Tier
    fallback_tier: Tier | None = None
    cost_ceiling_usd: float = Field(default=0.0, ge=0.0)
    rationale: str = ""

    @field_validator("role")
    @classmethod
    def _normalise_role(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if not v:
            raise ValueError("role must be non-empty")
        return v


class SelectionTable(BaseModel):
    """Indexed (role, complexity) → SelectionEntry table.

    Internally stores entries flat (list) so YAML round-trips cleanly;
    `_index()` builds the dict on demand. Lookup falls back to a
    role-wide default when the exact bucket is missing, then to a global
    default if the role itself is absent — see `lookup()` for the
    fallback chain.
    """
    model_config = _PYD_CONFIG
    version: int = 1
    entries: list[SelectionEntry] = Field(default_factory=list)

    def _index(self) -> dict[tuple[str, str], SelectionEntry]:
        return {(e.role, e.complexity): e for e in self.entries}

    def lookup(self, role: str, complexity: str) -> SelectionEntry:
        """Look up the (role, complexity) entry with graceful fallback.

        Fallback chain (first hit wins):
          1. exact (role, complexity)
          2. nearest filled complexity for that role — for very_complex
             walk *down*; for trivial walk *up*; for middle buckets walk
             outward in both directions
          3. wildcard role '*' with same fallback chain
          4. hard-coded safe default: medium / fallback=low
        """
        r = (role or "").strip().lower()
        idx = self._index()
        if (hit := idx.get((r, complexity))) is not None:
            return hit
        # Walk neighbouring complexities for this role.
        if (hit := _nearest_for_role(idx, r, complexity)) is not None:
            return hit
        # Try wildcard role.
        if (hit := idx.get(("*", complexity))) is not None:
            return hit
        if (hit := _nearest_for_role(idx, "*", complexity)) is not None:
            return hit
        return SelectionEntry(role=r or "unknown", complexity=complexity,  # type: ignore[arg-type]
                              preferred_tier="medium", fallback_tier="low",
                              cost_ceiling_usd=0.50,
                              rationale="no entry found — safe default (medium → low)")


def _nearest_for_role(idx: dict[tuple[str, str], SelectionEntry],
                      role: str, complexity: str) -> SelectionEntry | None:
    """Walk outward from `complexity` looking for any entry on the same
    role. Returns the closest hit (by bucket-distance) or None."""
    try:
        center = _ALL_COMPLEXITIES.index(complexity)  # type: ignore[arg-type]
    except ValueError:
        return None
    for dist in range(1, len(_ALL_COMPLEXITIES)):
        for sign in (-1, 1):
            j = center + sign * dist
            if 0 <= j < len(_ALL_COMPLEXITIES):
                hit = idx.get((role, _ALL_COMPLEXITIES[j]))
                if hit is not None:
                    return hit
    return None


# ── Loaders ──────────────────────────────────────────────────────────────────
def _parse_table(data: dict[str, Any] | None) -> SelectionTable:
    """Accept the YAML shape `{version, entries: [...]}`. Empty → empty
    table (caller decides whether that's an error)."""
    data = data or {}
    entries_raw = data.get("entries") or []
    return SelectionTable(version=int(data.get("version", 1)),
                          entries=[SelectionEntry(**e) for e in entries_raw])


def load_default_table(path: Path | None = None) -> SelectionTable:
    """Load the bundled default table from disk."""
    p = path or _DEFAULT_TABLE_PATH
    return _parse_table(yaml.safe_load(p.read_text()) if p.is_file() else None)


def load_org_table(bundle: dict[str, Any] | None = None,
                   bundle_id: str | None = None) -> SelectionTable | None:
    """Pull the override table from a bundle dict (or from the active
    bundle on disk if neither argument is given).

    Returns None when the bundle has no `cost.model_selection_table`
    section — caller should treat that as "no override; use default
    only" rather than as an empty override.

    `bundle_id` is accepted for API symmetry with future per-id loaders
    (e.g. `~/.spine/bundles/<id>/...`); when set we just pass it to
    `_load_active_bundle()` via env contract (unused today).
    """
    _ = bundle_id  # reserved for future per-id sourcing
    if bundle is None:
        bundle = _load_active_bundle()
    section = (((bundle or {}).get("cost") or {})
               .get("model_selection_table"))
    if not section:
        return None
    return _parse_table(section)


def merge_tables(default: SelectionTable,
                 override: SelectionTable | None) -> SelectionTable:
    """Per-(role, complexity) merge — override wins.

    Override entries fully REPLACE the matching default entry; entries
    in default that the override does not touch are preserved as-is.
    Version is taken from override if present, else default.
    """
    if override is None or not override.entries:
        return default
    merged: dict[tuple[str, str], SelectionEntry] = default._index().copy()
    for e in override.entries:
        merged[(e.role, e.complexity)] = e
    return SelectionTable(version=override.version or default.version,
                          entries=list(merged.values()))


def build_active_table(bundle: dict[str, Any] | None = None) -> SelectionTable:
    """One-call helper: default ⊕ org override → final table."""
    return merge_tables(load_default_table(), load_org_table(bundle=bundle))


def tier_higher(a: Tier, b: Tier) -> Tier:
    """Return whichever of the two tiers ranks higher."""
    return a if _TIER_RANK[a] >= _TIER_RANK[b] else b


__all__ = ["ComplexityName", "SelectionEntry", "SelectionTable",
           "load_default_table", "load_org_table", "merge_tables",
           "build_active_table", "tier_higher"]
