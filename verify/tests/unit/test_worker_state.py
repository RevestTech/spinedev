"""
Unit tests for Temporal worker state module.

Tests:
  - init_worker_state stores secrets
  - get_worker_secrets retrieves stored secrets
  - get_worker_secrets raises before init
  - Defensive copy (mutation protection)
"""

from __future__ import annotations

import pytest

from tron.workflows._worker_state import init_worker_state, get_worker_secrets
import tron.workflows._worker_state as ws_module


@pytest.fixture(autouse=True)
def reset_worker_state():
    """Reset module-level state between tests."""
    ws_module._secrets = None
    yield
    ws_module._secrets = None


class TestWorkerState:

    def test_get_before_init_raises(self):
        """get_worker_secrets() before init → RuntimeError."""
        with pytest.raises(RuntimeError, match="Worker state not initialized"):
            get_worker_secrets()

    def test_init_and_get(self):
        """Init + get returns the same secrets."""
        secrets = {"llm/openai-key": "sk-test", "db/password": "pw"}
        init_worker_state(secrets)

        result = get_worker_secrets()
        assert result["llm/openai-key"] == "sk-test"
        assert result["db/password"] == "pw"

    def test_defensive_copy(self):
        """Original dict mutation doesn't affect stored secrets."""
        secrets = {"key": "value"}
        init_worker_state(secrets)

        secrets["key"] = "mutated"

        result = get_worker_secrets()
        assert result["key"] == "value"

    def test_overwrite_on_reinit(self):
        """Calling init again replaces secrets."""
        init_worker_state({"a": "1"})
        init_worker_state({"b": "2"})

        result = get_worker_secrets()
        assert "b" in result
        assert "a" not in result
