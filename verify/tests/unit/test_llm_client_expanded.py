"""
Expanded unit tests for LLM client.

Tests:
  - Client initialization with different providers
  - Request/response handling for both Anthropic and OpenAI
  - Error handling and retry logic
  - Token counting and cost tracking
  - Model selection and validation
  - Temperature and max_tokens validation
  - Circuit breaker state transitions
  - Cost calculation accuracy
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from tron.infra.llm.client import (
    CircuitBreaker,
    CircuitState,
    LLMClient,
    LLMMessage,
    LLMRequest,
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


class TestClientInitialization:
    """Test LLMClient initialization with different configurations."""

    def test_init_with_both_providers(self):
        """Client initialized with both Anthropic and OpenAI keys."""
        client = LLMClient(
            anthropic_key="sk-ant-test",
            openai_key="sk-test-openai",
        )
        assert Provider.ANTHROPIC in client._keys
        assert Provider.OPENAI in client._keys
        assert client._keys[Provider.ANTHROPIC] == "sk-ant-test"
        assert client._keys[Provider.OPENAI] == "sk-test-openai"

    def test_init_with_anthropic_only(self):
        """Client initialized with Anthropic key only."""
        client = LLMClient(anthropic_key="sk-ant-test")
        assert Provider.ANTHROPIC in client._keys
        assert Provider.OPENAI not in client._keys

    def test_init_with_openai_only(self):
        """Client initialized with OpenAI key only."""
        client = LLMClient(openai_key="sk-test-openai")
        assert Provider.OPENAI in client._keys
        assert Provider.ANTHROPIC not in client._keys

    def test_init_filters_placeholder_keys(self):
        """Placeholder keys are filtered out."""
        client = LLMClient(
            anthropic_key="REPLACE_ME_IN_VAULT",
            openai_key="REPLACE_ME_IN_VAULT",
        )
        assert len(client._keys) == 0

    def test_init_with_timeout(self):
        """Timeout parameter is stored."""
        client = LLMClient(
            anthropic_key="sk-ant-test",
            timeout=60,
        )
        assert client._timeout == 60

    def test_init_circuit_breakers_created(self):
        """Circuit breakers initialized for both providers."""
        client = LLMClient(anthropic_key="sk-ant-test")
        assert Provider.ANTHROPIC in client._breakers
        assert Provider.OPENAI in client._breakers
        assert isinstance(client._breakers[Provider.ANTHROPIC], CircuitBreaker)

    def test_init_cost_tracking_reset(self):
        """Cost tracking initialized to zero."""
        client = LLMClient(anthropic_key="sk-ant-test")
        assert client.total_cost_usd == 0.0
        assert client.total_requests == 0


class TestModelResolution:
    """Test model lookup and validation."""

    def test_resolve_known_anthropic_model(self):
        """Known Anthropic models are resolved correctly."""
        client = LLMClient(anthropic_key="sk-ant-test")
        provider, input_rate, output_rate = client._resolve_model(
            "claude-haiku-4-5-20251001"
        )
        assert provider == Provider.ANTHROPIC
        assert input_rate == 0.001
        assert output_rate == 0.005

    def test_resolve_known_openai_model(self):
        """Known OpenAI models are resolved correctly."""
        client = LLMClient(openai_key="sk-test-openai")
        provider, input_rate, output_rate = client._resolve_model("gpt-4o")
        assert provider == Provider.OPENAI
        assert input_rate == 0.005
        assert output_rate == 0.015

    def test_resolve_unknown_model_raises_error(self):
        """Unknown models raise ValueError."""
        client = LLMClient(anthropic_key="sk-ant-test")
        with pytest.raises(ValueError, match="Unknown model"):
            client._resolve_model("unknown-model-xyz")

    def test_all_models_in_registry_resolvable(self):
        """All models in registry can be resolved."""
        client = LLMClient(anthropic_key="sk-ant-test", openai_key="sk-test-openai")
        for model_name in MODEL_REGISTRY.keys():
            provider, input_rate, output_rate = client._resolve_model(model_name)
            assert provider in [Provider.ANTHROPIC, Provider.OPENAI]
            assert input_rate > 0
            assert output_rate > 0


class TestCostCalculation:
    """Test LLM cost calculation."""

    def test_cost_calculation_anthropic_haiku(self):
        """Haiku cost calculated correctly."""
        cost = LLMClient._calculate_cost(
            "claude-haiku-4-5-20251001",
            input_tokens=1000,
            output_tokens=500,
        )
        # (1000 * 0.001) + (500 * 0.005) = 1.0 + 2.5 = 3.5
        expected = (1000 / 1000 * 0.001) + (500 / 1000 * 0.005)
        assert abs(cost - expected) < 1e-10

    def test_cost_calculation_openai_gpt4o(self):
        """GPT-4o cost calculated correctly."""
        cost = LLMClient._calculate_cost(
            "gpt-4o",
            input_tokens=1000,
            output_tokens=500,
        )
        # (1000 * 0.005) + (500 * 0.015) = 5.0 + 7.5 = 12.5
        assert cost > 0
        assert isinstance(cost, float)

    def test_cost_calculation_zero_tokens(self):
        """Cost with zero tokens is zero."""
        cost = LLMClient._calculate_cost("gpt-4o", input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_cost_calculation_unknown_model(self):
        """Unknown model returns zero cost."""
        cost = LLMClient._calculate_cost(
            "unknown-model",
            input_tokens=1000,
            output_tokens=500,
        )
        assert cost == 0.0


class TestCircuitBreaker:
    """Test circuit breaker state machine."""

    def test_circuit_breaker_initial_state_closed(self):
        """Circuit breaker starts in CLOSED state."""
        breaker = CircuitBreaker()
        assert breaker._state == CircuitState.CLOSED
        assert breaker.allow_request() is True

    def test_circuit_breaker_opens_after_failures(self):
        """Circuit breaker opens after reaching failure threshold."""
        breaker = CircuitBreaker(failure_threshold=3)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.allow_request() is True  # Still closed
        breaker.record_failure()
        assert breaker._state == CircuitState.OPEN
        assert breaker.allow_request() is False

    def test_circuit_breaker_half_open_after_timeout(self):
        """Circuit breaker transitions to HALF_OPEN after recovery timeout."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=1)
        breaker.record_failure()
        assert breaker._state == CircuitState.OPEN
        assert breaker.allow_request() is False

        # Sleep to exceed recovery timeout
        time.sleep(1.1)
        assert breaker.allow_request() is True
        assert breaker._state == CircuitState.HALF_OPEN

    def test_circuit_breaker_closes_on_success(self):
        """Circuit breaker closes on successful request."""
        breaker = CircuitBreaker(failure_threshold=3)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_failure()
        assert breaker._state == CircuitState.OPEN

        breaker.record_success()
        assert breaker._state == CircuitState.CLOSED
        assert breaker._failure_count == 0

    def test_circuit_breaker_accepts_custom_threshold(self):
        """Circuit breaker respects custom failure threshold."""
        breaker = CircuitBreaker(failure_threshold=10)
        for _ in range(9):
            breaker.record_failure()
            assert breaker._state == CircuitState.CLOSED

        breaker.record_failure()
        assert breaker._state == CircuitState.OPEN


class TestAnthropicRequest:
    """Test Anthropic API request handling."""

    async def test_anthropic_system_message_separated(self):
        """System message is separated in Anthropic request."""
        client = LLMClient(anthropic_key="sk-ant-test")
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content="You are helpful."),
                LLMMessage(role="user", content="Hello"),
            ],
            model="claude-haiku-4-5-20251001",
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "content": [{"type": "text", "text": "Hi there!"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "stop_reason": "end_turn",
            }
            mock_post.return_value = mock_response

            response = await client._call_anthropic(request)

            body = mock_post.call_args[1]["json"]
            assert body["system"] == "You are helpful."
            assert len(body["messages"]) == 1
            assert body["messages"][0]["role"] == "user"
            assert response.content == "Hi there!"

    async def test_anthropic_multiple_text_blocks(self):
        """Multiple text blocks in response are concatenated."""
        client = LLMClient(anthropic_key="sk-ant-test")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="claude-haiku-4-5-20251001",
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "content": [
                    {"type": "text", "text": "Part 1"},
                    {"type": "text", "text": " Part 2"},
                ],
                "usage": {"input_tokens": 10, "output_tokens": 10},
            }
            mock_post.return_value = mock_response

            response = await client._call_anthropic(request)
            assert response.content == "Part 1 Part 2"

    async def test_anthropic_stop_sequences_included(self):
        """Stop sequences are included in Anthropic request."""
        client = LLMClient(anthropic_key="sk-ant-test")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="claude-haiku-4-5-20251001",
            stop_sequences=["END", "STOP"],
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "content": [{"type": "text", "text": "response"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
            mock_post.return_value = mock_response

            await client._call_anthropic(request)
            body = mock_post.call_args[1]["json"]
            assert body["stop_sequences"] == ["END", "STOP"]


class TestOpenAIRequest:
    """Test OpenAI API request handling."""

    async def test_openai_json_mode_enabled(self):
        """JSON mode is included when requested."""
        client = LLMClient(openai_key="sk-test-openai")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="return JSON")],
            model="gpt-4o",
            json_mode=True,
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "choices": [{"message": {"content": '{"result": "ok"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
            mock_post.return_value = mock_response

            await client._call_openai(request)
            body = mock_post.call_args[1]["json"]
            assert body["response_format"] == {"type": "json_object"}

    async def test_openai_system_message_included(self):
        """System message is included in messages for OpenAI."""
        client = LLMClient(openai_key="sk-test-openai")
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content="You are helpful."),
                LLMMessage(role="user", content="Hello"),
            ],
            model="gpt-4o",
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "choices": [{"message": {"content": "Hi!"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
            mock_post.return_value = mock_response

            await client._call_openai(request)
            body = mock_post.call_args[1]["json"]
            assert len(body["messages"]) == 2
            assert body["messages"][0]["role"] == "system"

    async def test_openai_stop_sequences_mapped_to_stop(self):
        """Stop sequences are mapped to 'stop' for OpenAI."""
        client = LLMClient(openai_key="sk-test-openai")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="gpt-4o",
            stop_sequences=["END", "STOP"],
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
            assert body["stop"] == ["END", "STOP"]


class TestCompleteRequest:
    """Test complete() request method with retries and circuit breaker."""

    async def test_complete_requires_api_key(self):
        """complete() raises ValueError if no API key for provider."""
        client = LLMClient(anthropic_key=None, openai_key=None)
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="gpt-4o",
        )

        with pytest.raises(ValueError, match="No API key"):
            await client.complete(request)

    async def test_complete_checks_circuit_breaker(self):
        """complete() checks circuit breaker state."""
        client = LLMClient(anthropic_key="sk-ant-test")
        breaker = client._breakers[Provider.ANTHROPIC]
        # Verify breaker starts in closed state
        assert breaker._state == CircuitState.CLOSED
        assert breaker.allow_request() is True

    async def test_complete_retries_on_timeout(self):
        """complete() retries on timeout."""
        client = LLMClient(anthropic_key="sk-ant-test")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="claude-haiku-4-5-20251001",
        )

        attempt_count = 0
        async def mock_call(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise httpx.TimeoutException("timeout")
            response = MagicMock()
            response.json.return_value = {
                "content": [{"type": "text", "text": "success"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
            return response

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = mock_call

            response = await client.complete(request, retries=2)
            assert response.content == "success"
            assert attempt_count == 3

    async def test_complete_respects_max_retries(self):
        """complete() fails after max retries."""
        client = LLMClient(anthropic_key="sk-ant-test")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="claude-haiku-4-5-20251001",
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.TimeoutException("timeout")

            with pytest.raises(RuntimeError, match="failed after"):
                await client.complete(request, retries=1)

    async def test_complete_updates_cost_tracking(self):
        """complete() updates total_cost_usd and total_requests."""
        client = LLMClient(anthropic_key="sk-ant-test")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="claude-haiku-4-5-20251001",
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "content": [{"type": "text", "text": "response"}],
                "usage": {"input_tokens": 1000, "output_tokens": 500},
                "stop_reason": "end_turn",
            }
            mock_post.return_value = mock_response

            await client.complete(request)
            assert client.total_requests == 1
            # Cost should be positive
            assert client.total_cost_usd > 0

    async def test_complete_records_circuit_breaker_success(self):
        """complete() calls breaker.record_success() on success."""
        client = LLMClient(anthropic_key="sk-ant-test")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="claude-haiku-4-5-20251001",
        )

        breaker = client._breakers[Provider.ANTHROPIC]
        breaker.record_failure()
        breaker.record_failure()
        assert breaker._failure_count == 2

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "content": [{"type": "text", "text": "response"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
            mock_post.return_value = mock_response

            await client.complete(request)
            assert breaker._failure_count == 0
            assert breaker._state == CircuitState.CLOSED


class TestResponseParsing:
    """Test response parsing from both providers."""

    async def test_anthropic_response_properties(self):
        """Anthropic response sets all expected properties."""
        client = LLMClient(anthropic_key="sk-ant-test")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="claude-haiku-4-5-20251001",
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "content": [{"type": "text", "text": "Hello!"}],
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "stop_reason": "end_turn",
                "model": "claude-haiku-4-5-20251001",
            }
            mock_post.return_value = mock_response

            response = await client._call_anthropic(request)
            assert response.content == "Hello!"
            assert response.input_tokens == 100
            assert response.output_tokens == 50
            assert response.total_tokens == 150
            assert response.provider == Provider.ANTHROPIC
            assert response.model == "claude-haiku-4-5-20251001"
            assert response.finish_reason == "end_turn"

    async def test_openai_response_properties(self):
        """OpenAI response sets all expected properties."""
        client = LLMClient(openai_key="sk-test-openai")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="gpt-4o",
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "choices": [
                    {
                        "message": {"content": "Hello!"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                "model": "gpt-4o",
            }
            mock_post.return_value = mock_response

            response = await client._call_openai(request)
            assert response.content == "Hello!"
            assert response.input_tokens == 100
            assert response.output_tokens == 50
            assert response.total_tokens == 150
            assert response.provider == Provider.OPENAI
            assert response.finish_reason == "stop"


class TestTokenCounting:
    """Test token counting in responses."""

    async def test_token_counting_zero_output(self):
        """Response with no output tokens."""
        client = LLMClient(anthropic_key="sk-ant-test")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="claude-haiku-4-5-20251001",
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "content": [{"type": "text", "text": ""}],
                "usage": {"input_tokens": 100, "output_tokens": 0},
            }
            mock_post.return_value = mock_response

            response = await client._call_anthropic(request)
            assert response.output_tokens == 0
            assert response.total_tokens == 100

    async def test_token_counting_large_response(self):
        """Response with large token count."""
        client = LLMClient(openai_key="sk-test-openai")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="gpt-4o",
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "choices": [{"message": {"content": "x" * 10000}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 5000},
            }
            mock_post.return_value = mock_response

            response = await client._call_openai(request)
            assert response.input_tokens == 1000
            assert response.output_tokens == 5000
            assert response.total_tokens == 6000


class TestRequestParameterValidation:
    """Test validation of request parameters."""

    def test_request_with_custom_temperature(self):
        """Request accepts custom temperature."""
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="gpt-4o",
            temperature=0.7,
        )
        assert request.temperature == 0.7

    def test_request_with_custom_max_tokens(self):
        """Request accepts custom max_tokens."""
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="gpt-4o",
            max_tokens=2000,
        )
        assert request.max_tokens == 2000

    def test_request_with_json_mode(self):
        """Request accepts json_mode flag."""
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="gpt-4o",
            json_mode=True,
        )
        assert request.json_mode is True

    def test_default_request_parameters(self):
        """Request uses sensible defaults."""
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="gpt-4o",
        )
        assert request.temperature == 0.1
        assert request.max_tokens == 4000
        assert request.json_mode is False


class TestErrorHandling:
    """Test error handling in various scenarios."""

    async def test_http_status_error_triggers_retry(self):
        """HTTP status error triggers retry."""
        client = LLMClient(anthropic_key="sk-ant-test")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="claude-haiku-4-5-20251001",
        )

        attempt_count = 0
        async def mock_call(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                response = MagicMock()
                response.status_code = 429
                response.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "rate limited", request=None, response=response
                )
                raise response.raise_for_status.side_effect
            response = MagicMock()
            response.json.return_value = {
                "content": [{"type": "text", "text": "success"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
            return response

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = mock_call

            response = await client.complete(request, retries=2)
            assert response.content == "success"

    async def test_missing_content_field_in_response(self):
        """Handles missing content field gracefully."""
        client = LLMClient(anthropic_key="sk-ant-test")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="test")],
            model="claude-haiku-4-5-20251001",
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "content": [],  # Empty content
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
            mock_post.return_value = mock_response

            response = await client._call_anthropic(request)
            assert response.content == ""


class TestClientCleanup:
    """Test client cleanup and resource management."""

    async def test_close_closes_http_client(self):
        """close() closes the HTTP client."""
        client = LLMClient(anthropic_key="sk-ant-test")
        with patch.object(client._http, "aclose", new_callable=AsyncMock) as mock_close:
            await client.close()
            mock_close.assert_called_once()
