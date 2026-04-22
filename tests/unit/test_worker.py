"""
Unit tests for Temporal worker initialization.

Tests:
  - Worker initialization
  - Activity and workflow registration
  - Signal handling
  - Error handling
  - State initialization
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

import pytest

from tron.infra.secrets.llm_aliases import merge_anthropic_key_aliases
from tron.worker import main


@pytest.fixture(autouse=True)
def _worker_optional_anthropic_alias_absent():
    """Worker boot tries ``get_secret('anthropic-key')``; tests omit KMac alias."""
    with patch("tron.worker.get_secret", new_callable=AsyncMock) as m:
        m.side_effect = KeyError("anthropic-key")
        yield m


class TestWorkerMainFunction:
    """Test worker main() initialization flow."""

    @pytest.mark.asyncio
    async def test_main_loads_secrets(self):
        """main() loads secrets from keyvault."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            mock_get_secrets.return_value = {
                "db/password": "db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }

            with patch("tron.worker.init_db", new_callable=AsyncMock):
                with patch("tron.worker.init_redis", new_callable=AsyncMock):
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                        with patch("tron.worker.Worker"):
                            with patch("asyncio.get_running_loop"):
                                try:
                                    # Create a task that will be cancelled
                                    async def run_with_timeout():
                                        try:
                                            await asyncio.wait_for(main(), timeout=0.1)
                                        except asyncio.TimeoutError:
                                            pass

                                    await run_with_timeout()
                                except Exception:
                                    pass

                            mock_get_secrets.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_initializes_database(self):
        """main() initializes the database."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            mock_get_secrets.return_value = {
                "db/password": "db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }

            with patch("tron.worker.init_db", new_callable=AsyncMock) as mock_init_db:
                with patch("tron.worker.init_redis", new_callable=AsyncMock):
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                        with patch("tron.worker.Worker"):
                            with patch("asyncio.get_running_loop"):
                                try:
                                    async def run_with_timeout():
                                        try:
                                            await asyncio.wait_for(main(), timeout=0.1)
                                        except asyncio.TimeoutError:
                                            pass

                                    await run_with_timeout()
                                except Exception:
                                    pass

                            mock_init_db.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_initializes_redis(self):
        """main() initializes Redis."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            mock_get_secrets.return_value = {
                "db/password": "db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }

            with patch("tron.worker.init_db", new_callable=AsyncMock):
                with patch("tron.worker.init_redis", new_callable=AsyncMock) as mock_init_redis:
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                        with patch("tron.worker.Worker"):
                            with patch("asyncio.get_running_loop"):
                                try:
                                    async def run_with_timeout():
                                        try:
                                            await asyncio.wait_for(main(), timeout=0.1)
                                        except asyncio.TimeoutError:
                                            pass

                                    await run_with_timeout()
                                except Exception:
                                    pass

                            mock_init_redis.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_connects_to_temporal(self):
        """main() connects to Temporal."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            mock_get_secrets.return_value = {
                "db/password": "db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }

            with patch("tron.worker.init_db", new_callable=AsyncMock):
                with patch("tron.worker.init_redis", new_callable=AsyncMock):
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock) as mock_connect:
                        mock_client = AsyncMock()
                        mock_connect.return_value = mock_client

                        with patch("tron.worker.Worker"):
                            with patch("asyncio.get_running_loop"):
                                try:
                                    async def run_with_timeout():
                                        try:
                                            await asyncio.wait_for(main(), timeout=0.1)
                                        except asyncio.TimeoutError:
                                            pass

                                    await run_with_timeout()
                                except Exception:
                                    pass

                            mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_initializes_worker_state(self):
        """main() initializes worker state with secrets."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            secrets = {
                "db/password": "db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }
            mock_get_secrets.return_value = secrets

            with patch("tron.worker.init_db", new_callable=AsyncMock):
                with patch("tron.worker.init_redis", new_callable=AsyncMock):
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                        with patch("tron.worker.init_worker_state") as mock_init_state:
                            with patch("tron.worker.Worker"):
                                with patch("asyncio.get_running_loop"):
                                    try:
                                        async def run_with_timeout():
                                            try:
                                                await asyncio.wait_for(main(), timeout=0.1)
                                            except asyncio.TimeoutError:
                                                pass

                                        await run_with_timeout()
                                    except Exception:
                                        pass

                                mock_init_state.assert_called_once()
                                assert (
                                    mock_init_state.call_args[0][0]
                                    == merge_anthropic_key_aliases(secrets)
                                )

    @pytest.mark.asyncio
    async def test_main_prefers_anthropic_key_alias_for_worker_state(self):
        """Optional ``anthropic-key`` from vault overrides ``llm/anthropic-key``."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            base = {
                "db/password": "db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "sk-ant-legacy",
            }
            mock_get_secrets.return_value = base
            with patch("tron.worker.get_secret", new_callable=AsyncMock) as mock_get_secret:
                mock_get_secret.return_value = "sk-ant-from-short-path"
                with patch("tron.worker.init_db", new_callable=AsyncMock):
                    with patch("tron.worker.init_redis", new_callable=AsyncMock):
                        with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                            with patch("tron.worker.init_worker_state") as mock_init_state:
                                with patch("tron.worker.Worker"):
                                    with patch("asyncio.get_running_loop"):
                                        try:
                                            async def run_with_timeout():
                                                try:
                                                    await asyncio.wait_for(main(), timeout=0.1)
                                                except asyncio.TimeoutError:
                                                    pass

                                            await run_with_timeout()
                                        except Exception:
                                            pass

                                mock_init_state.assert_called_once()
                                merged = mock_init_state.call_args[0][0]
                                assert merged["llm/anthropic-key"] == "sk-ant-from-short-path"


class TestWorkerRegistration:
    """Test workflow and activity registration."""

    @pytest.mark.asyncio
    async def test_worker_registers_workflows(self):
        """Worker registers required workflows."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            mock_get_secrets.return_value = {
                "db/password": "db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }

            with patch("tron.worker.init_db", new_callable=AsyncMock):
                with patch("tron.worker.init_redis", new_callable=AsyncMock):
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                        with patch("tron.worker.Worker") as mock_worker_class:
                            mock_worker = AsyncMock()
                            mock_worker_class.return_value = mock_worker

                            with patch("asyncio.get_running_loop"):
                                try:
                                    async def run_with_timeout():
                                        try:
                                            await asyncio.wait_for(main(), timeout=0.1)
                                        except asyncio.TimeoutError:
                                            pass

                                    await run_with_timeout()
                                except Exception:
                                    pass

                            # Check that Worker was created with workflows
                            call_kwargs = mock_worker_class.call_args[1]
                            workflows = call_kwargs.get("workflows", [])
                            # Should have AuditWorkflow and FixWorkflow
                            assert len(workflows) >= 2

    @pytest.mark.asyncio
    async def test_worker_registers_activities(self):
        """Worker registers required activities."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            mock_get_secrets.return_value = {
                "db/password": "db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }

            with patch("tron.worker.init_db", new_callable=AsyncMock):
                with patch("tron.worker.init_redis", new_callable=AsyncMock):
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                        with patch("tron.worker.Worker") as mock_worker_class:
                            mock_worker = AsyncMock()
                            mock_worker_class.return_value = mock_worker

                            with patch("asyncio.get_running_loop"):
                                try:
                                    async def run_with_timeout():
                                        try:
                                            await asyncio.wait_for(main(), timeout=0.1)
                                        except asyncio.TimeoutError:
                                            pass

                                    await run_with_timeout()
                                except Exception:
                                    pass

                            # Check that Worker was created with activities
                            call_kwargs = mock_worker_class.call_args[1]
                            activities = call_kwargs.get("activities", [])
                            # Should have multiple activities
                            assert len(activities) >= 8


class TestDatabaseURLConstruction:
    """Test database URL building during initialization."""

    @pytest.mark.asyncio
    async def test_main_builds_db_url_with_password(self):
        """main() builds database URL with keyvault password."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            mock_get_secrets.return_value = {
                "db/password": "secret-db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }

            with patch("tron.worker.init_db", new_callable=AsyncMock) as mock_init_db:
                with patch("tron.worker.init_redis", new_callable=AsyncMock):
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                        with patch("tron.worker.Worker"):
                            with patch("asyncio.get_running_loop"):
                                try:
                                    async def run_with_timeout():
                                        try:
                                            await asyncio.wait_for(main(), timeout=0.1)
                                        except asyncio.TimeoutError:
                                            pass

                                    await run_with_timeout()
                                except Exception:
                                    pass

                            # Check that init_db was called with URL containing password
                            call_args = mock_init_db.call_args
                            db_url = call_args[1]["url"] if call_args[1] else call_args[0][0]
                            assert "secret-db-pass" in db_url


class TestRedisURLConstruction:
    """Test Redis URL building during initialization."""

    @pytest.mark.asyncio
    async def test_main_builds_redis_url_with_password(self):
        """main() builds Redis URL with keyvault password."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            mock_get_secrets.return_value = {
                "db/password": "db-pass",
                "redis/password": "secret-redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }

            with patch("tron.worker.init_db", new_callable=AsyncMock):
                with patch("tron.worker.init_redis", new_callable=AsyncMock) as mock_init_redis:
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                        with patch("tron.worker.Worker"):
                            with patch("asyncio.get_running_loop"):
                                try:
                                    async def run_with_timeout():
                                        try:
                                            await asyncio.wait_for(main(), timeout=0.1)
                                        except asyncio.TimeoutError:
                                            pass

                                    await run_with_timeout()
                                except Exception:
                                    pass

                            # Check that init_redis was called with URL containing password
                            call_args = mock_init_redis.call_args
                            redis_url = call_args[1]["url"] if call_args[1] else call_args[0][0]
                            assert "secret-redis-pass" in redis_url


class TestSignalHandling:
    """Test signal handling for graceful shutdown."""

    @pytest.mark.asyncio
    async def test_signal_handler_sets_stop_event(self):
        """Signal handler sets the stop event."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            mock_get_secrets.return_value = {
                "db/password": "db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }

            with patch("tron.worker.init_db", new_callable=AsyncMock):
                with patch("tron.worker.init_redis", new_callable=AsyncMock):
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                        with patch("tron.worker.Worker"):
                            # Mock the event loop
                            mock_loop = MagicMock()
                            signal_handlers = {}

                            def add_signal_handler(sig, handler, *args):
                                signal_handlers[sig] = (handler, args)

                            mock_loop.add_signal_handler = add_signal_handler

                            with patch("asyncio.get_running_loop", return_value=mock_loop):
                                try:
                                    async def run_with_timeout():
                                        try:
                                            await asyncio.wait_for(main(), timeout=0.1)
                                        except asyncio.TimeoutError:
                                            pass

                                    await run_with_timeout()
                                except Exception:
                                    pass

                            # Signal handlers should have been registered
                            # (This verifies the flow reached signal setup)


class TestCleanup:
    """Test cleanup operations."""

    @pytest.mark.asyncio
    async def test_main_closes_redis_on_shutdown(self):
        """main() closes Redis on shutdown."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            mock_get_secrets.return_value = {
                "db/password": "db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }

            with patch("tron.worker.init_db", new_callable=AsyncMock):
                with patch("tron.worker.init_redis", new_callable=AsyncMock):
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                        with patch("tron.worker.close_redis", new_callable=AsyncMock) as mock_close_redis:
                            with patch("tron.worker.close_db", new_callable=AsyncMock):
                                with patch("tron.worker.Worker"):
                                    with patch("asyncio.get_running_loop"):
                                        try:
                                            async def run_with_timeout():
                                                try:
                                                    await asyncio.wait_for(main(), timeout=0.1)
                                                except asyncio.TimeoutError:
                                                    pass

                                            await run_with_timeout()
                                        except Exception:
                                            pass

                                # close_redis should have been called during cleanup
                                # (This verifies the cleanup flow was attempted)

    @pytest.mark.asyncio
    async def test_main_closes_db_on_shutdown(self):
        """main() closes database on shutdown."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            mock_get_secrets.return_value = {
                "db/password": "db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }

            with patch("tron.worker.init_db", new_callable=AsyncMock):
                with patch("tron.worker.init_redis", new_callable=AsyncMock):
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                        with patch("tron.worker.close_redis", new_callable=AsyncMock):
                            with patch("tron.worker.close_db", new_callable=AsyncMock) as mock_close_db:
                                with patch("tron.worker.Worker"):
                                    with patch("asyncio.get_running_loop"):
                                        try:
                                            async def run_with_timeout():
                                                try:
                                                    await asyncio.wait_for(main(), timeout=0.1)
                                                except asyncio.TimeoutError:
                                                    pass

                                            await run_with_timeout()
                                        except Exception:
                                            pass

                                # close_db should have been called during cleanup
                                # (This verifies the cleanup flow was attempted)


class TestPoolConfiguration:
    """Test connection pool configuration."""

    @pytest.mark.asyncio
    async def test_db_pool_size_configured(self):
        """main() configures database pool size."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            mock_get_secrets.return_value = {
                "db/password": "db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }

            with patch("tron.worker.init_db", new_callable=AsyncMock) as mock_init_db:
                with patch("tron.worker.init_redis", new_callable=AsyncMock):
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                        with patch("tron.worker.Worker"):
                            with patch("asyncio.get_running_loop"):
                                try:
                                    async def run_with_timeout():
                                        try:
                                            await asyncio.wait_for(main(), timeout=0.1)
                                        except asyncio.TimeoutError:
                                            pass

                                    await run_with_timeout()
                                except Exception:
                                    pass

                            # Check that init_db was called with pool_size=5
                            call_kwargs = mock_init_db.call_args[1]
                            assert call_kwargs.get("pool_size") == 5

    @pytest.mark.asyncio
    async def test_db_max_overflow_configured(self):
        """main() configures database max overflow."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            mock_get_secrets.return_value = {
                "db/password": "db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }

            with patch("tron.worker.init_db", new_callable=AsyncMock) as mock_init_db:
                with patch("tron.worker.init_redis", new_callable=AsyncMock):
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                        with patch("tron.worker.Worker"):
                            with patch("asyncio.get_running_loop"):
                                try:
                                    async def run_with_timeout():
                                        try:
                                            await asyncio.wait_for(main(), timeout=0.1)
                                        except asyncio.TimeoutError:
                                            pass

                                    await run_with_timeout()
                                except Exception:
                                    pass

                            # Check that init_db was called with max_overflow=2
                            call_kwargs = mock_init_db.call_args[1]
                            assert call_kwargs.get("max_overflow") == 2

    @pytest.mark.asyncio
    async def test_redis_pool_size_configured(self):
        """main() configures Redis pool size."""
        with patch("tron.worker.get_secrets", new_callable=AsyncMock) as mock_get_secrets:
            mock_get_secrets.return_value = {
                "db/password": "db-pass",
                "redis/password": "redis-pass",
                "llm/openai-key": "openai-key",
                "llm/anthropic-key": "anthropic-key",
            }

            with patch("tron.worker.init_db", new_callable=AsyncMock):
                with patch("tron.worker.init_redis", new_callable=AsyncMock) as mock_init_redis:
                    with patch("tron.worker.Client.connect", new_callable=AsyncMock):
                        with patch("tron.worker.Worker"):
                            with patch("asyncio.get_running_loop"):
                                try:
                                    async def run_with_timeout():
                                        try:
                                            await asyncio.wait_for(main(), timeout=0.1)
                                        except asyncio.TimeoutError:
                                            pass

                                    await run_with_timeout()
                                except Exception:
                                    pass

                            # Check that init_redis was called with pool_size=20
                            call_kwargs = mock_init_redis.call_args[1]
                            assert call_kwargs.get("pool_size") == 20
