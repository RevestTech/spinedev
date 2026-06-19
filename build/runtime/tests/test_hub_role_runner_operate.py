"""OPERATE_KICKOFF must route to hub_deploy_runner, not devops install."""

from unittest.mock import patch

from build.runtime.hub_role_runner import run_build_hub_role
from devops.runtime.hub_deploy_runner import HubDeployResult


def test_operate_kickoff_uses_hub_deploy_runner() -> None:
    project = {
        "id": 1,
        "project_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "name": "operate-routing",
        "current_phase": "released",
        "metadata": {},
    }
    dep = HubDeployResult(
        ok=True,
        directive_id="dir_test",
        role="devops",
        extra={"operate_started_at": "2026-06-19T10:00:00Z"},
    )
    with patch("build.runtime.hub_role_runner._load_project", return_value=project):
        with patch(
            "devops.runtime.hub_deploy_runner.run_devops_hub_role",
            return_value=dep,
        ) as mock_run:
            with patch("build.runtime.hub_role_runner.asyncio.run") as mock_install:
                result = run_build_hub_role(
                    project_id=project["project_uuid"],
                    role="devops",
                    directive="OPERATE_KICKOFF",
                    actor="test",
                )
    mock_run.assert_called_once()
    mock_install.assert_not_called()
    assert result.ok is True
    assert result.extra.get("operate_started_at") == "2026-06-19T10:00:00Z"
