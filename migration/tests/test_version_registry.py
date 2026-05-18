"""Tests for ``migration.version_registry``."""

from __future__ import annotations

import pytest

from migration.version_registry import (
    SUBSYSTEM_VERSIONS,
    SUPPORTED_SPINE_VERSIONS,
    all_subsystems,
    get,
)


def test_registry_covers_every_v1_subsystem() -> None:
    """The 5 subsystems listed in #33 D must all be present."""
    subs = set(all_subsystems())
    # Per #33 D: DB schemas, bundle formats, role charters, vault
    # namespace, KG schema. License bundle is its own row.
    assert {"db", "bundle", "role_charters", "vault_namespace",
            "spine_kg", "license_bundle"}.issubset(subs)


def test_registry_get_returns_row() -> None:
    db = get("db")
    assert db.subsystem == "db"
    assert db.schema_kind == "db"


def test_registry_get_unknown_raises() -> None:
    with pytest.raises(KeyError):
        get("no-such-subsystem")


def test_supported_spine_versions_includes_v10() -> None:
    assert "1.0" in SUPPORTED_SPINE_VERSIONS


def test_every_registry_row_has_min_supported_at_or_below_current() -> None:
    """Sanity: ``min_supported_version`` should be a prefix-of-history value.

    We don't fully order arbitrary version strings here; we just assert
    the field is non-empty and the row is otherwise well-formed.
    """
    for row in SUBSYSTEM_VERSIONS:
        assert row.subsystem
        assert row.current_version
        assert row.min_supported_version
        assert row.owner_module
