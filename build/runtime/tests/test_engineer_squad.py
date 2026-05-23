"""Tests for engineer squad-lead subagent merge."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from build.runtime.engineer_squad import run_engineer_squad, squad_enabled


def test_run_engineer_squad_merges_specialties() -> None:
    async def fake_call_async(_req):  # noqa: ANN001
        class Resp:
            content = (
                "===== FILE: src/app.py =====\nprint('ok')\n===== END FILE =====\n"
            )

        return Resp()

    async def run() -> None:
        with patch("build.runtime.engineer_squad.call_async", new=AsyncMock(side_effect=fake_call_async)):
            result = await run_engineer_squad(
                system_base="base system",
                user_msg="build it",
                project_name="Demo",
            )
        assert result.raw_combined
        assert len(result.specialties_run) == 3
        assert "Engineer squad summary" in result.intro_md

    asyncio.run(run())


def test_squad_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPINE_ENGINEER_SQUAD", "0")
    assert squad_enabled() is False
