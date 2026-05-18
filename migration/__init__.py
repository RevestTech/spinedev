"""
migration
=========

Spine v3 migration subsystem (Wave 5 Squad F).

Implements design decision **#33** in ``docs/V3_DESIGN_DECISIONS.md`` — four
distinct migration concerns, three of which are v1.0 deliverables:

* **A. Onboarding migration.** Import an existing customer's data into a
  fresh Spine Hub. v1.0 ships connectors for **GitHub + Linear** (the
  "Linear OR Jira" choice in #33 — see ``ADR-F-001`` below). Other
  connectors (Confluence / Notion / Asana / Jira / GitLab) are scaffolded
  via :class:`migration.onboarding.Connector` but built v1.1+ on customer
  demand.
* **B. Spine portability.** ``migration.export`` + ``migration.import_``
  produce / consume a signed tarball containing the full Spine state
  (lifecycle, audit, KG, memory, federation, evidence, learning, devops,
  license, work-item, hub, identity-link, vault refs, bundle config, role
  charters). The export is **round-trippable**: ``export A -> import B ->
  export B`` produces a byte-identical tarball, which is the architectural
  realisation of the "no lock-in" promise.
* **D. Spine version migrations.** ``migration.spine_version`` upgrades a
  running Spine deployment across vendor releases — DB schemas, bundle
  formats, role charters, vault namespaces, KG schemas. **N-2 cross-version
  compatibility** is committed (v1.0 → v1.2 direct; v1.0 → v1.3 requires
  intermediate stop at v1.1 or v1.2). **Downgrades are BLOCKED** with a
  clear error pointing the admin at restoring from a recovery/ snapshot.

* **C. Software-migration-as-work-type** (Python 3.8 → 3.12, monolith →
  microservices, etc.) is captured by work-item-type design (#19). The
  v1.1 intake template + pipeline variant are out of scope for this squad.

Hard constraints enforced (per task brief):

* Signing key sourced via :mod:`shared.secrets` only — see #9 + ``ADR-F-002``.
  This squad reuses the license signing key (vendor vault path
  ``license/vendor_signing_key``) rather than minting a distinct migration
  key; rationale recorded in ``README.md``.
* ``migration_import`` and ``migration_version_upgrade`` MCP tools are
  tagged ``requires_citation=True`` per #12 (high-impact destructive ops
  must cite the source manifest hash and the upgrade plan rationale).
* Per-table integrity verification on import + audit-chain replay.

Public surface (locked for Wave 5):

    export.export_state(out_path, *, signer, scope, when=None) -> ExportManifest
    import_.import_state(in_path, *, verifier, dest_pool, dry_run=False) -> ImportReport
    onboarding.OnboardingDispatcher                — connector orchestrator
    onboarding.GitHubConnector / LinearConnector   — Day-1 connectors
    spine_version.upgrade(from_v, to_v, *, plan, executor) -> UpgradeReport
    version_registry.SUBSYSTEM_VERSIONS            — frozen registry

Sibling artifacts (NOT in this dir but part of this squad):

* ``shared/mcp/tools/migration.py`` — four MCP tools.
* ``migration/tests/`` — unit tests against mocks.
* ``migration/_v1_v2_migrator_legacy.py`` — historical v1 → v2 migrator,
  preserved per #33 as canonical example. Not imported by the v3 surface.
"""

from __future__ import annotations

from migration.export import (
    ExportManifest,
    ExportSchemaSlice,
    SCHEMA_SLICES,
    export_state,
)
from migration.import_ import (
    ImportError as MigrationImportError,
    ImportReport,
    import_state,
)
from migration.onboarding import (
    Connector,
    ConnectorRunReport,
    GitHubConnector,
    LinearConnector,
    OnboardingDispatcher,
    WorkItemMapping,
)
from migration.spine_version import (
    DowngradeBlocked,
    UnsupportedUpgradePath,
    UpgradePlan,
    UpgradeReport,
    UpgradeStep,
    supported_paths,
    upgrade,
)
from migration.version_registry import (
    SUBSYSTEM_VERSIONS,
    SUPPORTED_SPINE_VERSIONS,
    SubsystemVersion,
)

__all__ = [
    # B. portability
    "ExportManifest",
    "ExportSchemaSlice",
    "SCHEMA_SLICES",
    "export_state",
    "MigrationImportError",
    "ImportReport",
    "import_state",
    # A. onboarding
    "Connector",
    "ConnectorRunReport",
    "GitHubConnector",
    "LinearConnector",
    "OnboardingDispatcher",
    "WorkItemMapping",
    # D. spine version
    "DowngradeBlocked",
    "UnsupportedUpgradePath",
    "UpgradePlan",
    "UpgradeReport",
    "UpgradeStep",
    "supported_paths",
    "upgrade",
    # registry
    "SUBSYSTEM_VERSIONS",
    "SUPPORTED_SPINE_VERSIONS",
    "SubsystemVersion",
]
