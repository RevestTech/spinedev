"""Tests for the operate runner (D2 slate #5)."""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from devops.runtime.operate_runner import PLANE_NAMES, run_operate


def _project(**overrides: Any) -> dict[str, Any]:
    base = {
        "project_uuid": "11111111-1111-1111-1111-111111111111",
        "name": "test-project",
    }
    base.update(overrides)
    return base


def _all_active(project_uuid: str, names) -> list[dict[str, Any]]:
    return [
        {
            "plane": name,
            "status": "active",
            "metadata": {},
            "checked_at": "2026-05-30T00:00:00+00:00",
        }
        for name in names
    ]


def _mixed_errors(project_uuid: str, names) -> list[dict[str, Any]]:
    return [
        {
            "plane": name,
            "status": "error" if name in {"alerting"} else "active",
            "metadata": {},
            "checked_at": "2026-05-30T00:00:00+00:00",
            **({"error": "Plane stub error"} if name in {"alerting"} else {}),
        }
        for name in names
    ]


def test_eight_planes_in_canonical_order() -> None:
    assert PLANE_NAMES == (
        "infrastructure",
        "deployment",
        "monitoring",
        "alerting",
        "networking",
        "database",
        "secrets",
        "ci_cd",
    )


def test_missing_project_uuid_returns_error_envelope() -> None:
    response = run_operate(_project(project_uuid=""))
    assert response.status == "error"
    assert response.error is not None
    assert response.error.code == "missing_project_uuid"


def test_all_active_returns_ok_envelope() -> None:
    response = run_operate(_project(), status_runner=_all_active)
    assert response.status == "ok"
    assert "8/8 planes active" in response.summary
    assert "operate_started_at" in response.data
    assert response.data["operate_report"]["plane_count"] == 8
    assert response.next_actions


def test_plane_error_yields_warning_not_error() -> None:
    response = run_operate(_project(), status_runner=_mixed_errors)
    assert response.status == "warning"
    assert "alerting" in response.summary
    # Operate still records the start so the watcher rule fires.
    assert "operate_started_at" in response.data


def test_artifact_includes_run_id_with_project_label() -> None:
    response = run_operate(_project(name="alpha"), status_runner=_all_active)
    assert response.artifacts
    artifact = response.artifacts[0]
    assert artifact.type == "run_id"
    assert "alpha" in (artifact.label or "")


def test_plane_subset_honoured() -> None:
    response = run_operate(
        _project(),
        plane_names=("database", "monitoring"),
        status_runner=_all_active,
    )
    assert response.status == "ok"
    assert response.data["operate_report"]["plane_count"] == 2


@patch("devops.planes.database._probe_postgres_sync", return_value=("active", "SELECT 1 ok"))
@patch("devops.planes.monitoring._probe_hub_healthz_sync", return_value=(True, "http://localhost:8090/healthz"))
@patch("devops.planes.infrastructure._probe_hub_healthz_sync", return_value=(True, "http://localhost:8090/healthz"))
def test_probed_planes_active_when_checks_pass(
    _mock_infra: Any,
    _mock_monitoring: Any,
    _mock_pg: Any,
) -> None:
    response = run_operate(
        _project(),
        plane_names=("infrastructure", "monitoring", "database"),
    )
    assert response.status == "ok"
    planes = {p["plane"]: p for p in response.data["operate_report"]["planes"]}
    assert planes["infrastructure"]["status"] == "active"
    assert planes["monitoring"]["status"] == "active"
    assert planes["database"]["status"] == "active"
    assert planes["infrastructure"]["metadata"]["details"]["probe"] == "hub_healthz"
    assert planes["database"]["metadata"]["details"]["probe"] == "postgres"


@patch("devops.planes.database._probe_postgres_sync", return_value=("error", "Connection refused"))
@patch("devops.planes.monitoring._probe_hub_healthz_sync", return_value=(False, "URLError: refused"))
@patch("devops.planes.infrastructure._probe_hub_healthz_sync", return_value=(False, "URLError: refused"))
def test_probe_failures_yield_warning_fail_soft(
    _mock_infra: Any,
    _mock_monitoring: Any,
    _mock_pg: Any,
) -> None:
    response = run_operate(
        _project(),
        plane_names=("infrastructure", "monitoring", "database"),
    )
    assert response.status == "warning"
    assert "operate_started_at" in response.data
    planes = {p["plane"]: p for p in response.data["operate_report"]["planes"]}
    assert planes["infrastructure"]["status"] == "error"
    assert planes["monitoring"]["status"] == "error"
    assert planes["database"]["status"] == "error"


@patch("devops.planes.infrastructure._probe_hub_healthz_sync", return_value=(True, "http://localhost:8090/healthz"))
def test_stub_planes_remain_unknown_without_probes(_mock_hub: Any) -> None:
    response = run_operate(
        _project(),
        plane_names=("deployment", "alerting"),
    )
    assert response.status == "ok"
    planes = {p["plane"]: p for p in response.data["operate_report"]["planes"]}
    assert planes["deployment"]["status"] == "unknown"
    assert planes["alerting"]["status"] == "unknown"
