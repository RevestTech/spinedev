"""Tests for ``recovery.cross_region`` — the v1.0 STUB.

Per design decision #32 + Part 4.4: layer 7 ships seam-only with a
license-flag gate. These tests assert:

* When ``dr.cross_region`` is DISABLED → ``CrossRegionDisabled`` raised.
* When ``dr.cross_region`` is ENABLED  → ``NotImplementedError`` raised
  ("v1.1+ enterprise tier").
* When the license subsystem is missing entirely → ``CrossRegionDisabled``
  with a graceful message.
"""
from __future__ import annotations

import pytest

from recovery.cross_region import (
    IMPLEMENTATION_VERSION,
    LICENSE_FLAG,
    CrossRegionDisabled,
    CrossRegionReplicator,
    ReplicationTopology,
    promote_standby,
)


@pytest.fixture
def topology() -> ReplicationTopology:
    return ReplicationTopology(
        primary_region="us-east-1",
        standby_region="us-west-2",
        provider="aws",
    )


class TestLicenseGate:

    def test_disabled_flag_raises_cross_region_disabled(
        self, topology, monkeypatch,
    ) -> None:
        import recovery.cross_region as cr
        # Fake the license module's is_enabled to return False
        import sys
        import types
        fake = types.ModuleType("license")
        fake.is_enabled = lambda flag: False  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "license", fake)

        replicator = CrossRegionReplicator(topology)
        with pytest.raises(CrossRegionDisabled) as exc_info:
            replicator.start_replication()
        assert exc_info.value.message_for_ui  # populated for the UI

    def test_enabled_flag_raises_not_implemented(
        self, topology, monkeypatch,
    ) -> None:
        import sys
        import types
        fake = types.ModuleType("license")
        fake.is_enabled = lambda flag: True  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "license", fake)

        replicator = CrossRegionReplicator(topology)
        with pytest.raises(NotImplementedError) as exc_info:
            replicator.start_replication()
        assert IMPLEMENTATION_VERSION in str(exc_info.value)

    def test_unknown_flag_raises_cross_region_disabled(
        self, topology, monkeypatch,
    ) -> None:
        import sys
        import types
        fake = types.ModuleType("license")

        def raises(flag):
            raise KeyError(flag)

        fake.is_enabled = raises  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "license", fake)

        replicator = CrossRegionReplicator(topology)
        with pytest.raises(CrossRegionDisabled) as exc_info:
            replicator.start_replication()
        assert LICENSE_FLAG in str(exc_info.value)

    def test_license_module_missing_raises_cross_region_disabled(
        self, topology, monkeypatch,
    ) -> None:
        import sys
        # Make ``import license`` fail by installing a sabotaged module.
        sabotage = type("Sabotage", (), {})()
        monkeypatch.setitem(sys.modules, "license", None)  # type: ignore[arg-type]
        # ``import license`` with sys.modules[X]=None raises ImportError
        replicator = CrossRegionReplicator(topology)
        with pytest.raises(CrossRegionDisabled):
            replicator.start_replication()


class TestAllOperationsGate:

    def test_all_ops_gated(self, topology, monkeypatch) -> None:
        import sys, types
        fake = types.ModuleType("license")
        fake.is_enabled = lambda flag: False  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "license", fake)
        replicator = CrossRegionReplicator(topology)
        for op in (replicator.start_replication,
                   replicator.stop_replication,
                   replicator.status,
                   replicator.promote):
            with pytest.raises(CrossRegionDisabled):
                op()

    def test_module_level_promote_standby(self, topology, monkeypatch) -> None:
        import sys, types
        fake = types.ModuleType("license")
        fake.is_enabled = lambda flag: False  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "license", fake)
        with pytest.raises(CrossRegionDisabled):
            promote_standby(topology)


class TestTopologyDefaults:

    def test_rpo_rto_match_decision_32(self, topology) -> None:
        # Per #32: RPO ≤ 5 min, RTO ≤ 10 min for active-passive.
        assert topology.rpo_seconds_target == 300
        assert topology.rto_seconds_target == 600
        assert topology.replication_mode == "active-passive"
