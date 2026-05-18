"""Versioned-subsystem registry for migration / upgrade orchestration.

Every Spine subsystem that owns persistent state declares its current
schema/format version here. ``migration.spine_version.upgrade`` reads
this registry to compute the steps required to move a deployment from
``from_version`` to ``to_version``.

This module is intentionally **data-only** — no I/O, no DB calls — so
the registry can be imported by both runtime gates and one-shot CLI
upgraders without bootstrapping a Hub.

Conventions:

* ``schema_kind`` indicates the kind of artifact whose version is being
  tracked (Flyway DB migration / Pydantic bundle / role-charter spec /
  vault namespace layout / KG schema). The upgrader uses this to pick
  the right migration handler.
* ``flyway_baseline_version`` for ``schema_kind == "db"`` rows is the
  Flyway ``V``-prefixed version that defines the *baseline* for the
  named Spine version. e.g. Spine v1.0 baselines at Flyway V32; Spine
  v1.1 baselines at the next Flyway batch.
* ``min_supported_version`` is the **N-2 commitment** anchor. Per #33
  D, the latest Spine version commits to direct upgrades from versions
  no older than two minor releases prior; older deployments must hop
  through an intermediate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#: Literal of every Spine release this version of the migrator knows
#: how to handle. The order matters — ``upgrade`` uses this order to
#: compute path direction (downgrade detection) and intermediate stops.
SUPPORTED_SPINE_VERSIONS: tuple[str, ...] = ("1.0", "1.1", "1.2", "1.3")

#: Current release this Spine build is. Updated per release; the
#: migrator refuses upgrades whose ``to_version`` exceeds this value.
CURRENT_SPINE_VERSION: str = "1.0"

#: N-2 cross-version commitment: how far back direct upgrades may
#: source from. v1.2 may directly upgrade a v1.0 deployment; v1.3
#: requires an intermediate stop. Per #33 D.
N_MINUS_K_DIRECT_UPGRADE_DISTANCE: int = 2

SchemaKind = Literal["db", "bundle", "charter", "vault_namespace", "kg_schema"]
"""Categories of versioned subsystems tracked in the registry."""


@dataclass(frozen=True)
class SubsystemVersion:
    """One row in the versioned-subsystem registry.

    Attributes:
        subsystem: Short name (``"db"``, ``"bundle"``, ``"role_charters"``,
            ``"vault_namespace"``, ``"spine_kg"``).
        schema_kind: The migration handler class to dispatch to.
        current_version: Latest known schema version for this subsystem
            shipped with ``CURRENT_SPINE_VERSION``.
        min_supported_version: Oldest schema version the current Spine
            release can *read* (i.e. import-from) without an intermediate
            upgrade step.
        owner_module: Dotted path to the module that defines the schema
            (e.g. ``"db.flyway.sql"`` or ``"shared.schemas.license"``).
        notes: Operator-facing notes for the release log.
    """

    subsystem: str
    schema_kind: SchemaKind
    current_version: str
    min_supported_version: str
    owner_module: str
    notes: str = ""


#: The frozen registry. Adding a new subsystem schema requires a code
#: change here AND a matching upgrade handler in
#: :mod:`migration.spine_version`.
SUBSYSTEM_VERSIONS: tuple[SubsystemVersion, ...] = (
    SubsystemVersion(
        subsystem="db",
        schema_kind="db",
        current_version="V35",  # latest Flyway shipped with v1.0 (V35__audit_subsystem_devops.sql)
        min_supported_version="V32",  # N-2 commitment anchor
        owner_module="db.flyway.sql",
        notes="Flyway-managed PostgreSQL schemas (spine_lifecycle, spine_audit, "
              "spine_kg, spine_memory, spine_license, spine_federation, "
              "spine_evidence, spine_learning, spine_devops, spine_workitem, "
              "spine_hub, spine_identity).",
    ),
    SubsystemVersion(
        subsystem="bundle",
        schema_kind="bundle",
        current_version="1",
        min_supported_version="1",
        owner_module="shared.standards.bundle_schema",
        notes="Org-policy bundle YAML (federation pipeline, feature flags, "
              "comm prefs, learning scope, devops planes).",
    ),
    SubsystemVersion(
        subsystem="license_bundle",
        schema_kind="bundle",
        current_version="1",  # BUNDLE_PAYLOAD_VERSION
        min_supported_version="1",
        owner_module="shared.schemas.license.bundle_v1",
        notes="Signed Ed25519 license bundle (feature flags + quotas + tier).",
    ),
    SubsystemVersion(
        subsystem="role_charters",
        schema_kind="charter",
        current_version="v3",
        min_supported_version="v2",
        owner_module="shared.charters",
        notes="Industry-anchored role charters (PMBOK/ITIL/NIST/SRE).",
    ),
    SubsystemVersion(
        subsystem="vault_namespace",
        schema_kind="vault_namespace",
        current_version="v3",
        min_supported_version="v3",
        owner_module="shared.secrets",
        notes="Reserved vault path prefixes (license/, federation/, hub/, "
              "keycloak/, integration/<name>/, project/<id>/).",
    ),
    SubsystemVersion(
        subsystem="spine_kg",
        schema_kind="kg_schema",
        current_version="V2",  # V2__spine_kg_schema.sql
        min_supported_version="V2",
        owner_module="build.kg",
        notes="Knowledge graph node/edge schema + extractor contracts.",
    ),
)


def get(subsystem: str) -> SubsystemVersion:
    """Return the registry row for ``subsystem`` or raise ``KeyError``.

    Args:
        subsystem: e.g. ``"db"``, ``"bundle"``, ``"license_bundle"``.

    Raises:
        KeyError: Subsystem not in the registry.
    """
    for row in SUBSYSTEM_VERSIONS:
        if row.subsystem == subsystem:
            return row
    raise KeyError(
        f"unknown subsystem {subsystem!r}; known: "
        f"{sorted(r.subsystem for r in SUBSYSTEM_VERSIONS)}",
    )


def all_subsystems() -> tuple[str, ...]:
    """Return the tuple of registered subsystem names (in registry order)."""
    return tuple(r.subsystem for r in SUBSYSTEM_VERSIONS)


__all__ = [
    "CURRENT_SPINE_VERSION",
    "N_MINUS_K_DIRECT_UPGRADE_DISTANCE",
    "SUBSYSTEM_VERSIONS",
    "SUPPORTED_SPINE_VERSIONS",
    "SchemaKind",
    "SubsystemVersion",
    "all_subsystems",
    "get",
]
