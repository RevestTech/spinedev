"""Tests for ``migration.spine_version`` (#33 D)."""

from __future__ import annotations

import pytest

from migration.spine_version import (
    DowngradeBlocked,
    StubExecutor,
    UnsupportedUpgradePath,
    plan,
    supported_paths,
    upgrade,
)
from migration.version_registry import (
    N_MINUS_K_DIRECT_UPGRADE_DISTANCE,
    SUPPORTED_SPINE_VERSIONS,
)


# ---------------------------------------------------------------------------
# supported_paths
# ---------------------------------------------------------------------------


def test_supported_paths_same_version_is_noop_signal() -> None:
    assert supported_paths("1.0", "1.0") == ["1.0"]


def test_supported_paths_within_n_minus_2_is_direct() -> None:
    # gap = 2 (within N-2 commitment) -> direct hop chain
    assert supported_paths("1.0", "1.2") == ["1.0", "1.2"]


def test_supported_paths_beyond_n_minus_2_requires_intermediate() -> None:
    # 1.0 -> 1.3 = gap 3, exceeds N-2 (=2).
    path = supported_paths("1.0", "1.3")
    assert path[0] == "1.0"
    assert path[-1] == "1.3"
    assert len(path) == 4  # 1.0, 1.1, 1.2, 1.3 — every intermediate.


def test_downgrade_blocked_per_33d_policy() -> None:
    with pytest.raises(DowngradeBlocked) as exc:
        supported_paths("1.2", "1.0")
    assert "recovery" in str(exc.value).lower()


def test_unknown_version_raises() -> None:
    with pytest.raises(UnsupportedUpgradePath):
        supported_paths("0.9", "1.0")
    with pytest.raises(UnsupportedUpgradePath):
        supported_paths("1.0", "2.0")


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def test_plan_noop_when_versions_equal() -> None:
    p = plan("1.0", "1.0")
    assert p.is_noop()
    assert p.requires_admin_approval is False


def test_plan_direct_emits_steps_for_every_subsystem() -> None:
    from migration.version_registry import SUBSYSTEM_VERSIONS
    p = plan("1.0", "1.2")
    # gap 2 = 1 hop in the loop, steps per hop = len(registry)
    assert len(p.steps) == len(SUBSYSTEM_VERSIONS)
    assert p.intermediate_stops == []
    assert p.requires_admin_approval is True


def test_plan_multi_hop_lists_intermediate_stops() -> None:
    from migration.version_registry import SUBSYSTEM_VERSIONS
    p = plan("1.0", "1.3")
    # 3 hops * len(registry) per hop.
    assert len(p.steps) == 3 * len(SUBSYSTEM_VERSIONS)
    assert p.intermediate_stops == ["1.1", "1.2"]


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def test_upgrade_noop_returns_all_ok_without_approval_required() -> None:
    rep = upgrade(from_version="1.0", to_version="1.0")
    assert rep.all_ok
    assert rep.plan.is_noop()


def test_upgrade_refuses_without_approval() -> None:
    """Per #16, no auto-push: must supply an approve callable."""
    with pytest.raises(PermissionError):
        upgrade(from_version="1.0", to_version="1.2")


def test_upgrade_dry_run_records_skipped_steps() -> None:
    executor = StubExecutor()
    rep = upgrade(
        from_version="1.0", to_version="1.2",
        executor=executor, approve=lambda _: True, dry_run=True,
    )
    assert rep.all_ok
    assert executor.calls == []  # executor not invoked in dry-run
    statuses = {s[1] for s in rep.step_outcomes}
    assert statuses == {"skipped"}


def test_upgrade_real_run_executes_every_step() -> None:
    executor = StubExecutor()
    rep = upgrade(
        from_version="1.0", to_version="1.2",
        executor=executor, approve=lambda _: True,
    )
    assert rep.all_ok
    assert len(executor.calls) == len(rep.plan.steps)
    assert all(s[1] == "ok" for s in rep.step_outcomes)


def test_upgrade_downgrade_propagates_block() -> None:
    with pytest.raises(DowngradeBlocked):
        upgrade(from_version="1.2", to_version="1.0",
                approve=lambda _: True)


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


def test_n_minus_k_is_two_per_33d() -> None:
    assert N_MINUS_K_DIRECT_UPGRADE_DISTANCE == 2


def test_supported_versions_in_ascending_order() -> None:
    """The whole upgrade math relies on registry order; regress on shuffles."""
    for a, b in zip(SUPPORTED_SPINE_VERSIONS, SUPPORTED_SPINE_VERSIONS[1:]):
        # Compare as version tuples.
        ta = tuple(int(p) for p in a.split("."))
        tb = tuple(int(p) for p in b.split("."))
        assert ta < tb, f"SUPPORTED_SPINE_VERSIONS not ascending at {a},{b}"
