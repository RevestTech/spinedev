"""
Unit tests for LLM client.

Tests:
  - LLMResponse dataclass (total_tokens property)
  - CircuitBreaker (state transitions)
  - LLMClient construction (key filtering)
  - _resolve_model (known and unknown models)
  - _calculate_cost (math correctness)
  - complete() missing key error
  - complete() circuit breaker open error
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from tron.infra.llm.client import (
    DEFAULT_ANTHROPIC_FAST_MODEL,
    CircuitBreaker,
    CircuitState,
    LLMClient,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    MODEL_REGISTRY,
    Provider,
)


@pytest.fixture(autouse=True)
def _no_http(monkeypatch):
    """Prevent LLMClient from creating a real httpx.AsyncClient."""
    monkeypatch.setattr(
        "tron.infra.llm.client.httpx.AsyncClient",
        lambda **kwargs: MagicMock(),
    )


# ── Request Building Tests ───────────────────────────────────────────


class TestAnthropicRequestBuilding:
    """Test Anthropic API request body construction."""

    async def test_anthropic_request_with_system_message(self):
        """Anthropic request should separate system message."""
        client = LLMClient(anthropic_key="test-key", openai_key=None)

        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content="You are helpful."),
                LLMMessage(role="user", content="Hello"),
            ],
            model=DEFAULT_ANTHROPIC_FAST_MODEL,
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "content": [{"type": "text", "text": "response"}],
                "usage": {"input_tokens": 10, "output_tokens": 20},
                "stop_reason": "end_turn",
            }
            mock_post.return_value = mock_response

            await client._call_anthropic(request)

            body = mock_post.call_args[1]["json"]
            assert body["system"] == "You are helpful."
            assert len(body["messages"]) == 1
            assert body["messages"][0]["role"] == "user"

    async def test_anthropic_request_with_stop_sequences(self):
        """Anthropic request should include stop_sequences."""
        client = LLMClient(anthropic_key="test-key", openai_key=None)

        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model=DEFAULT_ANTHROPIC_FAST_MODEL,
            stop_sequences=["END", "STOP"],
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "content": [{"type": "text", "text": "response"}],
                "usage": {"input_tokens": 10, "output_tokens": 20},
            }
            mock_post.return_value = mock_response

            await client._call_anthropic(request)

            body = mock_post.call_args[1]["json"]
            assert body["stop_sequences"] == ["END", "STOP"]


class TestOpenAIRequestBuilding:
    """Test OpenAI API request body construction."""

    async def test_openai_request_with_json_mode(self):
        """OpenAI request should include response_format for json_mode."""
        client = LLMClient(anthropic_key=None, openai_key="test-key")

        request = LLMRequest(
            messages=[LLMMessage(role="user", content="Generate JSON")],
            model="gpt-4o",
            json_mode=True,
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "model": "gpt-4o",
            }
            mock_post.return_value = mock_response

            await client._call_openai(request)

            body = mock_post.call_args[1]["json"]
            assert body["response_format"] == {"type": "json_object"}

    async def test_openai_request_with_stop_sequences(self):
        """OpenAI request should use 'stop' for stop_sequences."""
        client = LLMClient(anthropic_key=None, openai_key="test-key")

        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="gpt-4o",
            stop_sequences=["END", "EOF"],
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "choices": [{"message": {"content": "response"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
            mock_post.return_value = mock_response

            await client._call_openai(request)

            body = mock_post.call_args[1]["json"]
            assert body["stop"] == ["END", "EOF"]


# ── Tests: LLMResponse ───────────────────────────────────────────────


class TestLLMResponse:

    def test_total_tokens(self):
        resp = LLMResponse(
            content="hi", model="test", provider=Provider.ANTHROPIC,
            input_tokens=100, output_tokens=50,
        )
        assert resp.total_tokens == 150

    def test_total_tokens_zero(self):
        resp = LLMResponse(content="", model="test", provider=Provider.OPENAI)
        assert resp.total_tokens == 0

    def test_default_values(self):
        resp = LLMResponse(content="x", model="m", provider=Provider.ANTHROPIC)
        assert resp.cost_usd == 0.0
        assert resp.latency_ms == 0
        assert resp.finish_reason == ""
        assert resp.raw is None


# ── Tests: CircuitBreaker ─────────────────────────────────────────────


class TestCircuitBreaker:

    def test_initial_state_closed(self):
        cb = CircuitBreaker()
        assert cb._state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.allow_request() is True
        cb.record_failure()  # 3rd failure
        assert cb._state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_success_resets_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb._failure_count == 0
        assert cb._state == CircuitState.CLOSED

    def test_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        cb.record_failure()
        assert cb._state == CircuitState.OPEN
        # With recovery_timeout=0, should immediately transition to HALF_OPEN
        time.sleep(0.01)
        assert cb.allow_request() is True
        assert cb._state == CircuitState.HALF_OPEN

    def test_half_open_allows_one_request(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        cb.record_failure()
        time.sleep(0.01)
        assert cb.allow_request() is True  # Transitions to HALF_OPEN
        assert cb.allow_request() is True  # HALF_OPEN allows requests

    def test_success_after_half_open_closes(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        cb.record_failure()
        time.sleep(0.01)
        cb.allow_request()  # HALF_OPEN
        cb.record_success()
        assert cb._state == CircuitState.CLOSED


# ── Tests: LLMClient construction ─────────────────────────────────────


class TestLLMClientInit:

    def test_filters_placeholder_keys(self):
        client = LLMClient(
            anthropic_key="REPLACE_ME_IN_VAULT",
            openai_key="sk-real-key",
        )
        assert Provider.ANTHROPIC not in client._keys
        assert Provider.OPENAI in client._keys

    def test_both_keys(self):
        client = LLMClient(
            anthropic_key="sk-ant-123",
            openai_key="sk-oai-456",
        )
        assert Provider.ANTHROPIC in client._keys
        assert Provider.OPENAI in client._keys

    def test_no_keys(self):
        client = LLMClient()
        assert len(client._keys) == 0

    def test_empty_string_key_excluded(self):
        client = LLMClient(anthropic_key="", openai_key="")
        assert len(client._keys) == 0

    def test_initial_cost_tracking(self):
        client = LLMClient(anthropic_key="sk-test")
        assert client.total_cost_usd == 0.0
        assert client.total_requests == 0


# ── Tests: _resolve_model ─────────────────────────────────────────────


class TestResolveModel:

    def test_known_model(self):
        client = LLMClient(anthropic_key="sk-test")
        provider, in_cost, out_cost = client._resolve_model(DEFAULT_ANTHROPIC_FAST_MODEL)
        assert provider == Provider.ANTHROPIC
        assert in_cost > 0
        assert out_cost > 0

    def test_openai_model(self):
        client = LLMClient(openai_key="sk-test")
        provider, _, _ = client._resolve_model("gpt-4o")
        assert provider == Provider.OPENAI

    def test_unknown_model_raises(self):
        client = LLMClient(anthropic_key="sk-test")
        with pytest.raises(ValueError, match="Unknown model"):
            client._resolve_model("nonexistent-model-v99")


# ── Tests: _calculate_cost ────────────────────────────────────────────


class TestCalculateCost:

    def test_cost_calculation(self):
        # Haiku 4.5: input=0.001/1k, output=0.005/1k (per MTok pricing)
        cost = LLMClient._calculate_cost(DEFAULT_ANTHROPIC_FAST_MODEL, 1000, 1000)
        expected = (1000 / 1000 * 0.001) + (1000 / 1000 * 0.005)
        assert abs(cost - expected) < 1e-10

    def test_zero_tokens(self):
        cost = LLMClient._calculate_cost(DEFAULT_ANTHROPIC_FAST_MODEL, 0, 0)
        assert cost == 0.0

    def test_unknown_model_returns_zero(self):
        cost = LLMClient._calculate_cost("unknown-model", 1000, 1000)
        assert cost == 0.0

    def test_gpt4o_cost(self):
        # gpt-4o: input=0.005/1k, output=0.015/1k
        cost = LLMClient._calculate_cost("gpt-4o", 2000, 500)
        expected = (2000 / 1000 * 0.005) + (500 / 1000 * 0.015)
        assert abs(cost - expected) < 1e-10


# ── Tests: complete() error paths ─────────────────────────────────────


class TestCompleteErrors:

    async def test_missing_key_raises(self):
        """complete() with no key for the provider → ValueError."""
        client = LLMClient()  # No keys at all
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="hello")],
            model=DEFAULT_ANTHROPIC_FAST_MODEL,
        )
        with pytest.raises(ValueError, match="No API key"):
            await client.complete(request)

    async def test_circuit_open_raises(self):
        """complete() when circuit breaker is open → RuntimeError."""
        client = LLMClient(anthropic_key="sk-test")
        # Force breaker open
        breaker = client._breakers[Provider.ANTHROPIC]
        for _ in range(breaker.failure_threshold):
            breaker.record_failure()

        request = LLMRequest(
            messages=[LLMMessage(role="user", content="hello")],
            model=DEFAULT_ANTHROPIC_FAST_MODEL,
        )
        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            await client.complete(request)


# ── Tests: MODEL_REGISTRY ────────────────────────────────────────────


class TestModelRegistry:

    def test_all_entries_have_three_values(self):
        for model, entry in MODEL_REGISTRY.items():
            assert len(entry) == 3, f"{model} should have (provider, in_cost, out_cost)"
            provider, in_cost, out_cost = entry
            assert isinstance(provider, Provider)
            assert in_cost >= 0
            assert out_cost >= 0

    def test_anthropic_models_exist(self):
        assert DEFAULT_ANTHROPIC_FAST_MODEL in MODEL_REGISTRY
        assert "claude-3-sonnet-20240229" in MODEL_REGISTRY

    def test_openai_models_exist(self):
        assert "gpt-4o" in MODEL_REGISTRY
        assert "gpt-4o-mini" in MODEL_REGISTRY


# ── Tests: complete() happy path ─────────────────────────────────────


class TestCompleteHappyPath:

    async def test_anthropic_call_success(self):
        """complete() with Anthropic provider → returns LLMResponse."""
        client = LLMClient(anthropic_key="sk-ant-test")

        # Mock the HTTP response from Anthropic API
        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.raise_for_status = MagicMock()
        mock_api_response.json.return_value = {
            "content": [{"type": "text", "text": "Hello from Claude!"}],
            "model": DEFAULT_ANTHROPIC_FAST_MODEL,
            "usage": {"input_tokens": 50, "output_tokens": 20},
            "stop_reason": "end_turn",
        }

        client._http = AsyncMock()
        client._http.post = AsyncMock(return_value=mock_api_response)

        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content="You are helpful."),
                LLMMessage(role="user", content="Say hello"),
            ],
            model=DEFAULT_ANTHROPIC_FAST_MODEL,
        )
        response = await client.complete(request)

        assert response.content == "Hello from Claude!"
        assert response.provider == Provider.ANTHROPIC
        assert response.input_tokens == 50
        assert response.output_tokens == 20
        assert response.total_tokens == 70
        assert client.total_requests == 1
        assert client.total_cost_usd > 0

    async def test_openai_call_success(self):
        """complete() with OpenAI provider → returns LLMResponse."""
        client = LLMClient(openai_key="sk-oai-test")

        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.raise_for_status = MagicMock()
        mock_api_response.json.return_value = {
            "choices": [{"message": {"content": "Hello from GPT!"}, "finish_reason": "stop"}],
            "model": "gpt-4o",
            "usage": {"prompt_tokens": 30, "completion_tokens": 10},
        }

        client._http = AsyncMock()
        client._http.post = AsyncMock(return_value=mock_api_response)

        request = LLMRequest(
            messages=[LLMMessage(role="user", content="Hello")],
            model="gpt-4o",
        )
        response = await client.complete(request)

        assert response.content == "Hello from GPT!"
        assert response.provider == Provider.OPENAI
        assert response.input_tokens == 30
        assert response.output_tokens == 10

    async def test_anthropic_separates_system_message(self):
        """Anthropic call puts system message in separate field."""
        client = LLMClient(anthropic_key="sk-ant-test")

        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.raise_for_status = MagicMock()
        mock_api_response.json.return_value = {
            "content": [{"type": "text", "text": "ok"}],
            "model": DEFAULT_ANTHROPIC_FAST_MODEL,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        captured_body = {}
        async def capture_post(url, **kwargs):
            captured_body.update(kwargs.get("json", {}))
            return mock_api_response

        client._http = AsyncMock()
        client._http.post = capture_post

        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content="You are a security expert."),
                LLMMessage(role="user", content="Analyze this"),
            ],
            model=DEFAULT_ANTHROPIC_FAST_MODEL,
        )
        await client.complete(request)

        assert captured_body["system"] == "You are a security expert."
        assert len(captured_body["messages"]) == 1
        assert captured_body["messages"][0]["role"] == "user"

    async def test_openai_json_mode(self):
        """OpenAI call with json_mode sets response_format."""
        client = LLMClient(openai_key="sk-oai-test")

        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.raise_for_status = MagicMock()
        mock_api_response.json.return_value = {
            "choices": [{"message": {"content": '{"key":"val"}'}, "finish_reason": "stop"}],
            "model": "gpt-4o",
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        }

        captured_body = {}
        async def capture_post(url, **kwargs):
            captured_body.update(kwargs.get("json", {}))
            return mock_api_response

        client._http = AsyncMock()
        client._http.post = capture_post

        request = LLMRequest(
            messages=[LLMMessage(role="user", content="Generate JSON")],
            model="gpt-4o",
            json_mode=True,
        )
        await client.complete(request)

        assert captured_body["response_format"] == {"type": "json_object"}

    async def test_retry_on_timeout(self):
        """Retry logic: first call times out, second succeeds."""
        import httpx

        client = LLMClient(anthropic_key="sk-ant-test")

        good_response = MagicMock()
        good_response.status_code = 200
        good_response.raise_for_status = MagicMock()
        good_response.json.return_value = {
            "content": [{"type": "text", "text": "ok"}],
            "model": DEFAULT_ANTHROPIC_FAST_MODEL,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        call_count = 0
        async def flaky_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.TimeoutException("timeout")
            return good_response

        client._http = AsyncMock()
        client._http.post = flaky_post

        request = LLMRequest(
            messages=[LLMMessage(role="user", content="hi")],
            model=DEFAULT_ANTHROPIC_FAST_MODEL,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            response = await client.complete(request)

        assert response.content == "ok"
        assert call_count == 2

    async def test_all_retries_exhausted_raises(self):
        """All retries fail → RuntimeError."""
        import httpx

        client = LLMClient(anthropic_key="sk-ant-test")
        client._http = AsyncMock()
        client._http.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        request = LLMRequest(
            messages=[LLMMessage(role="user", content="hi")],
            model=DEFAULT_ANTHROPIC_FAST_MODEL,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="failed after"):
                await client.complete(request)


# ── Tests: close() ──────────────────────────────────────────────────


class TestLLMClientClose:

    async def test_close_calls_aclose(self):
        client = LLMClient(anthropic_key="sk-test")
        client._http = AsyncMock()
        await client.close()
        client._http.aclose.assert_called_once()
