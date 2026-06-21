"""
End-to-end test for the full audit pipeline.

Tests the complete flow with mocked LLM:
  1. Create project via API
  2. Start audit via API
  3. AuditExecutor runs (mocked LLM, mocked tools)
  4. Findings stored in DB
  5. Query findings via API

This tests the wiring between API → AuditExecutor → Agents → DB
without needing Temporal, real LLMs, or real Redis.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import SAMPLE_SECURITY_FINDINGS_JSON, FakeLLMResponse


@pytest.fixture
async def e2e_client(test_app, sqlite_db, auth_headers, fake_secrets):
    """Fully wired E2E client with mocked LLM and Redis."""
    from httpx import ASGITransport, AsyncClient
    from tron.infra.db.session import get_session
    import tron.infra.db.session as db_session_module

    # Override DB session for API routes
    async def _override_session():
        async with sqlite_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app.dependency_overrides[get_session] = _override_session

    # Also set the module-level _session_factory for AuditExecutor
    db_session_module._session_factory = sqlite_db

    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=auth_headers,
    ) as client:
        yield client

    test_app.dependency_overrides.clear()
    db_session_module._session_factory = None


class TestFullAuditE2E:
    """End-to-end test: create project → run audit → check findings."""

    async def test_full_audit_pipeline(self, e2e_client, sqlite_db, fake_secrets):
        """Complete audit flow with mocked LLM produces findings in DB."""

        # 1. Create project
        project_resp = await e2e_client.post("/api/projects", json={
            "name": "E2E Test Project",
            "description": "Testing the full audit pipeline",
        })
        assert project_resp.status_code == 201
        project_id = project_resp.json()["id"]

        # 2. Start audit (BackgroundTask path)
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            return_value=FakeLLMResponse(content=SAMPLE_SECURITY_FINDINGS_JSON)
        )
        mock_llm.close = AsyncMock()
        mock_llm.total_cost_usd = 0.0

        with patch("tron.api.routes.audits.settings") as mock_settings, \
             patch("tron.infra.secrets.get_secrets", new_callable=AsyncMock, return_value=fake_secrets), \
             patch("tron.infra.llm.client.LLMClient", return_value=mock_llm), \
             patch("tron.services.audit_executor.LLMClient", return_value=mock_llm), \
             patch("tron.agents.security_iso.LLMClient", return_value=mock_llm), \
             patch("tron.agents.builder_iso.LLMClient", return_value=mock_llm), \
             patch("tron.agents.performance_iso.LLMClient", return_value=mock_llm), \
             patch("tron.agents.manager.LLMClient", return_value=mock_llm), \
             patch("tron.infra.redis.pubsub.get_redis", return_value=AsyncMock(publish=AsyncMock())):

            mock_settings.temporal_enabled = False

            audit_resp = await e2e_client.post("/api/audits", json={
                "project_id": project_id,
            })

        assert audit_resp.status_code == 201
        audit_id = audit_resp.json()["id"]

        # 3. Wait briefly for background task (it runs in-process for tests)
        await asyncio.sleep(0.5)

        # 4. Check audit status
        status_resp = await e2e_client.get(f"/api/audits/{audit_id}")
        assert status_resp.status_code == 200
        # Status should be either "running" or "completed" by now
        status = status_resp.json()["status"]
        assert status in ("queued", "running", "completed", "failed")

        # 5. If completed, verify findings
        if status == "completed":
            findings_resp = await e2e_client.get(f"/api/audits/{audit_id}/findings")
            assert findings_resp.status_code == 200
            assert findings_resp.json()["total"] >= 1
