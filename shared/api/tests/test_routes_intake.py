"""Tests for intake transcript persistence."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from shared.api.routes.intake import (
    IntakeChatRequest,
    TranscriptTurn,
    _persist_intake_state,
    intake_chat,
)
from shared.identity.models import TokenClaims, User


def _user() -> User:
    claims = TokenClaims(sub="dev-user", exp=9_999_999_999, iat=1)
    return User(id="dev-user", username="dev-user", roles=["hub-user"], raw_claims=claims)


def test_persist_intake_state_writes_metadata_patch() -> None:
    captured: dict[str, object] = {}

    async def _fake_execute(sql: str, payload: str, pk: int) -> None:
        captured["sql"] = sql
        captured["payload"] = json.loads(payload)
        captured["pk"] = pk

    conn = AsyncMock()
    conn.execute = AsyncMock(side_effect=_fake_execute)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = conn

    async def _run() -> None:
        with patch("shared.api.routes.intake._resolve_project_pk", AsyncMock(return_value=42)), patch(
            "shared.api.dependencies.get_db_pool_raw", return_value=pool
        ):
            await _persist_intake_state(
                "00000000-0000-0000-0000-00000000abcd",
                [
                    TranscriptTurn(role="user", content="hello"),
                    TranscriptTurn(role="assistant", content="hi there"),
                ],
                False,
            )

    asyncio.run(_run())
    assert captured["pk"] == 42
    assert captured["payload"] == {
        "intake_transcript": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ],
        "intake_done": False,
    }


def test_intake_chat_persists_transcript_after_llm_reply() -> None:
    body = IntakeChatRequest(
        message="We need a todo app",
        transcript=[],
        project_name="Todos",
        project_type="feature",
        greenfield=True,
    )

    llm_resp = MagicMock()
    llm_resp.content = "Who is the primary user?"

    async def _run():
        with patch("shared.api.routes.intake._load_charter", return_value="# product"), patch(
            "shared.api.routes.intake.call_async", AsyncMock(return_value=llm_resp)
        ), patch(
            "shared.api.routes.intake._persist_intake_state", AsyncMock()
        ) as persist_mock:
            resp = await intake_chat("proj-uuid", body, _user())
            persist_mock.assert_awaited_once()
            args = persist_mock.await_args.args
            assert args[0] == "proj-uuid"
            assert len(args[1]) == 2
            assert args[1][0].content == "We need a todo app"
            assert args[1][1].content == "Who is the primary user?"
            assert args[2] is False
            return resp

    resp = asyncio.run(_run())
    assert resp.reply == "Who is the primary user?"
    assert len(resp.transcript) == 2
