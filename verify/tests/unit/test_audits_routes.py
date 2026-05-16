"""
Unit tests for audit routes, particularly Temporal dispatch.

Tests:
  - _dispatch_temporal_audit workflow dispatching
  - Temporal client connection and workflow submission
  - Error handling in dispatch
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


class TestDispatchTemporalAudit:
    """Test Temporal workflow dispatch for audits."""

    async def test_dispatch_temporal_connects_and_starts_workflow(self):
        """_dispatch_temporal_audit should connect to Temporal and start workflow."""
        from tron.api.routes.audits import _dispatch_temporal_audit

        audit_id = uuid4()
        project_id = uuid4()

        mock_client = AsyncMock()
        mock_client.start_workflow = AsyncMock()

        with patch("temporalio.client.Client.connect", new_callable=AsyncMock, return_value=mock_client), \
             patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_host = "localhost:7233"
            mock_settings.temporal_task_queue = "audit-queue"

            await _dispatch_temporal_audit(audit_id, project_id, "manual")

            mock_client.start_workflow.assert_called_once()
            call_args = mock_client.start_workflow.call_args
            assert call_args[0][0] == "AuditWorkflow"
            assert call_args[1]["id"] == f"audit-{audit_id}"
            assert call_args[1]["task_queue"] == "audit-queue"

    async def test_dispatch_temporal_passes_audit_input(self):
        """_dispatch_temporal_audit should pass correct AuditInput."""
        from tron.api.routes.audits import _dispatch_temporal_audit

        audit_id = uuid4()
        project_id = uuid4()

        mock_client = AsyncMock()
        mock_client.start_workflow = AsyncMock()

        with patch("temporalio.client.Client.connect", new_callable=AsyncMock, return_value=mock_client), \
             patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_host = "localhost:7233"
            mock_settings.temporal_task_queue = "audit-queue"

            await _dispatch_temporal_audit(audit_id, project_id, "webhook")

            call_args = mock_client.start_workflow.call_args
            audit_input = call_args[0][1]
            # AuditInput object contains these fields
            assert audit_input.audit_run_id == str(audit_id)
            assert audit_input.project_id == str(project_id)
            assert audit_input.triggered_by == "webhook"

    async def test_dispatch_temporal_connection_error(self):
        """_dispatch_temporal_audit should raise if Temporal connection fails."""
        from tron.api.routes.audits import _dispatch_temporal_audit

        audit_id = uuid4()
        project_id = uuid4()

        with patch("temporalio.client.Client.connect", new_callable=AsyncMock,
                   side_effect=RuntimeError("Cannot connect to Temporal")):
            with pytest.raises(RuntimeError):
                await _dispatch_temporal_audit(audit_id, project_id, "manual")


class TestDispatchTemporalSettings:
    """Test Temporal dispatch respects configuration."""

    async def test_dispatch_uses_temporal_host_from_settings(self):
        """_dispatch_temporal_audit should use temporal_host from settings."""
        from tron.api.routes.audits import _dispatch_temporal_audit

        audit_id = uuid4()
        project_id = uuid4()

        mock_client = AsyncMock()
        mock_client.start_workflow = AsyncMock()

        with patch("temporalio.client.Client.connect", new_callable=AsyncMock, return_value=mock_client) as mock_connect, \
             patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_host = "temporal.example.com:7233"
            mock_settings.temporal_task_queue = "custom-queue"

            await _dispatch_temporal_audit(audit_id, project_id, "manual")

            # Verify Client.connect was called with correct host
            mock_connect.assert_called_once_with("temporal.example.com:7233")

    async def test_dispatch_uses_task_queue_from_settings(self):
        """_dispatch_temporal_audit should use task_queue from settings."""
        from tron.api.routes.audits import _dispatch_temporal_audit

        audit_id = uuid4()
        project_id = uuid4()

        mock_client = AsyncMock()
        mock_client.start_workflow = AsyncMock()

        with patch("temporalio.client.Client.connect", new_callable=AsyncMock, return_value=mock_client), \
             patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_host = "localhost:7233"
            mock_settings.temporal_task_queue = "my-custom-queue"

            await _dispatch_temporal_audit(audit_id, project_id, "manual")

            call_args = mock_client.start_workflow.call_args
            assert call_args[1]["task_queue"] == "my-custom-queue"


class TestAuditInputCreation:
    """Test AuditInput object creation for Temporal."""

    async def test_audit_input_contains_all_fields(self):
        """AuditInput should include all required fields."""
        from tron.api.routes.audits import _dispatch_temporal_audit

        audit_id = uuid4()
        project_id = uuid4()

        mock_client = AsyncMock()
        mock_client.start_workflow = AsyncMock()

        with patch("temporalio.client.Client.connect", new_callable=AsyncMock, return_value=mock_client), \
             patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_host = "localhost:7233"
            mock_settings.temporal_task_queue = "queue"

            await _dispatch_temporal_audit(audit_id, project_id, "api")

            call_args = mock_client.start_workflow.call_args
            audit_input = call_args[0][1]
            assert hasattr(audit_input, "audit_run_id")
            assert hasattr(audit_input, "project_id")
            assert hasattr(audit_input, "triggered_by")
            assert hasattr(audit_input, "scope")
            assert audit_input.scope == "full"
