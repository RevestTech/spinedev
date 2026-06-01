"""Hub deploy runner schedules on the Hub event loop when available."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from devops.runtime.hub_deploy_runner import HubDeployResult, _run_local_deploy_on_hub_loop


def test_run_local_deploy_uses_hub_loop_when_running() -> None:
    loop = asyncio.new_event_loop()
    loop.__enter__ = lambda: loop  # type: ignore[attr-defined]
    try:
        loop.run_until_complete(asyncio.sleep(0))

        async def _fake_deploy(project: dict) -> HubDeployResult:
            _ = project
            return HubDeployResult(ok=True, directive_id="dir_test")

        with patch(
            "shared.api.dependencies.get_hub_event_loop",
            return_value=loop,
        ):
            with patch(
                "devops.runtime.hub_deploy_runner.run_local_deploy_async",
                side_effect=_fake_deploy,
            ):
                with patch.object(loop, "is_running", return_value=True):
                    with patch(
                        "devops.runtime.hub_deploy_runner.asyncio.run_coroutine_threadsafe",
                    ) as rcts:
                        fut = MagicMock()
                        fut.result.return_value = HubDeployResult(
                            ok=True, directive_id="dir_scheduled",
                        )
                        rcts.return_value = fut
                        out = _run_local_deploy_on_hub_loop({"project_uuid": "p1"})
        assert out.ok is True
        assert out.directive_id == "dir_scheduled"
        rcts.assert_called_once()
    finally:
        loop.close()
