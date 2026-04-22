"""
Unit tests for the Embeddings Service.

Tests:
  - Initialization and validation
  - embed_text / embed_batch / embed_code
  - Cosine similarity computation
  - Retry with exponential backoff
  - Batch processing
  - Factory functions
  - Error handling
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tron.infra.embeddings.service import (
    EmbeddingsService,
    get_embeddings_service,
    init_embeddings,
)


# ── Fixtures ──────────────────────────────────────────────────────────


SAMPLE_EMBEDDING = [0.1] * 1536


def _make_openai_response(embeddings: list[list[float]]) -> dict:
    """Build a mock OpenAI embeddings API response."""
    return {
        "data": [
            {"index": i, "embedding": emb}
            for i, emb in enumerate(embeddings)
        ],
        "model": "text-embedding-3-large",
        "usage": {"prompt_tokens": 10, "total_tokens": 10},
    }


@pytest.fixture
def svc() -> EmbeddingsService:
    """EmbeddingsService with a test API key."""
    return EmbeddingsService(api_key="sk-test-key-123")


@pytest.fixture
def mock_http_response():
    """Mock httpx.Response with successful embeddings response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = _make_openai_response([SAMPLE_EMBEDDING])
    resp.raise_for_status = MagicMock()
    return resp


# ── Initialization Tests ─────────────────────────────────────────────


class TestInit:

    def test_init_valid(self):
        """EmbeddingsService initializes with valid key."""
        svc = EmbeddingsService(api_key="sk-test")
        assert svc._model == "text-embedding-3-large"
        assert svc._dimensions == 1536

    def test_init_custom_model(self):
        """Custom model and dimensions accepted."""
        svc = EmbeddingsService(
            api_key="sk-test",
            model="text-embedding-3-small",
            dimensions=512,
        )
        assert svc._model == "text-embedding-3-small"
        assert svc._dimensions == 512

    def test_init_empty_key_raises(self):
        """Empty API key raises ValueError."""
        with pytest.raises(ValueError, match="api_key is missing"):
            EmbeddingsService(api_key="")

    def test_init_placeholder_key_raises(self):
        """Placeholder key raises ValueError."""
        with pytest.raises(ValueError, match="api_key is missing"):
            EmbeddingsService(api_key="REPLACE_ME_IN_VAULT")

    def test_repr(self, svc):
        """__repr__ includes model and dimensions."""
        r = repr(svc)
        assert "text-embedding-3-large" in r
        assert "1536" in r


# ── Similarity Tests ─────────────────────────────────────────────────


class TestSimilarity:

    async def test_identical_vectors(self, svc):
        """Identical vectors have similarity ~1.0."""
        vec = [1.0, 0.0, 0.0]
        sim = await svc.similarity(vec, vec)
        assert abs(sim - 1.0) < 1e-6

    async def test_orthogonal_vectors(self, svc):
        """Orthogonal vectors have similarity ~0.0."""
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        sim = await svc.similarity(a, b)
        assert abs(sim) < 1e-6

    async def test_opposite_vectors(self, svc):
        """Opposite vectors have similarity ~-1.0."""
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        sim = await svc.similarity(a, b)
        assert abs(sim - (-1.0)) < 1e-6

    async def test_empty_vectors(self, svc):
        """Empty vectors return 0.0."""
        assert await svc.similarity([], [1.0]) == 0.0
        assert await svc.similarity([1.0], []) == 0.0
        assert await svc.similarity([], []) == 0.0

    async def test_zero_vector(self, svc):
        """Zero vector returns 0.0."""
        assert await svc.similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    async def test_known_similarity(self, svc):
        """Known vectors produce expected similarity."""
        a = [1.0, 2.0, 3.0]
        b = [4.0, 5.0, 6.0]
        # Manual: dot=32, |a|=sqrt(14), |b|=sqrt(77)
        expected = 32 / (math.sqrt(14) * math.sqrt(77))
        actual = await svc.similarity(a, b)
        assert abs(actual - expected) < 1e-6


# ── Embed Text Tests ─────────────────────────────────────────────────


class TestEmbedText:

    async def test_embed_text_calls_api(self, svc, mock_http_response):
        """embed_text makes API call and returns vector."""
        svc._http = AsyncMock()
        svc._http.post = AsyncMock(return_value=mock_http_response)

        result = await svc.embed_text("hello world")

        assert len(result) == 1536
        svc._http.post.assert_called_once()
        call_args = svc._http.post.call_args
        assert "api.openai.com" in call_args[0][0]

    async def test_embed_text_sends_correct_payload(self, svc, mock_http_response):
        """embed_text sends model, input, and dimensions."""
        svc._http = AsyncMock()
        svc._http.post = AsyncMock(return_value=mock_http_response)

        await svc.embed_text("test input")

        call_kwargs = svc._http.post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["model"] == "text-embedding-3-large"
        assert payload["input"] == ["test input"]
        assert payload["dimensions"] == 1536


# ── Embed Batch Tests ────────────────────────────────────────────────


class TestEmbedBatch:

    async def test_embed_batch_empty(self, svc):
        """Empty input returns empty list."""
        result = await svc.embed_batch([])
        assert result == []

    async def test_embed_batch_single(self, svc, mock_http_response):
        """Single item batch works correctly."""
        svc._http = AsyncMock()
        svc._http.post = AsyncMock(return_value=mock_http_response)

        result = await svc.embed_batch(["hello"])
        assert len(result) == 1
        assert len(result[0]) == 1536

    async def test_embed_batch_multiple(self, svc):
        """Multiple items processed in correct order."""
        emb1 = [0.1] * 1536
        emb2 = [0.2] * 1536
        resp = MagicMock(spec=httpx.Response)
        resp.json.return_value = _make_openai_response([emb1, emb2])
        resp.raise_for_status = MagicMock()

        svc._http = AsyncMock()
        svc._http.post = AsyncMock(return_value=resp)

        result = await svc.embed_batch(["a", "b"])
        assert len(result) == 2
        assert result[0][0] == pytest.approx(0.1)
        assert result[1][0] == pytest.approx(0.2)

    async def test_embed_batch_clamps_size(self, svc, mock_http_response):
        """Batch size is clamped to 2048."""
        svc._http = AsyncMock()
        svc._http.post = AsyncMock(return_value=mock_http_response)

        # Should not raise even with large batch_size
        await svc.embed_batch(["x"], batch_size=10000)
        svc._http.post.assert_called_once()


# ── Embed Code Tests ─────────────────────────────────────────────────


class TestEmbedCode:

    async def test_embed_code_prepends_language(self, svc, mock_http_response):
        """embed_code prepends language prefix."""
        svc._http = AsyncMock()
        svc._http.post = AsyncMock(return_value=mock_http_response)

        await svc.embed_code("x = 1", language="python")

        call_kwargs = svc._http.post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["input"][0].startswith("[PYTHON]")

    async def test_embed_code_with_context(self, svc, mock_http_response):
        """embed_code includes context in prefix."""
        svc._http = AsyncMock()
        svc._http.post = AsyncMock(return_value=mock_http_response)

        await svc.embed_code("x = 1", language="python", context="async networking")

        call_kwargs = svc._http.post.call_args[1]
        payload = call_kwargs["json"]
        assert "[PYTHON: async networking]" in payload["input"][0]


# ── Retry Tests ──────────────────────────────────────────────────────


class TestRetry:

    async def test_retry_on_timeout(self, svc, mock_http_response):
        """Retries on timeout and eventually succeeds."""
        svc._http = AsyncMock()
        svc._http.post = AsyncMock(
            side_effect=[
                httpx.TimeoutException("timeout"),
                mock_http_response,
            ]
        )

        # Patch sleep to avoid real delays
        with patch("tron.infra.embeddings.service.asyncio.sleep", new_callable=AsyncMock):
            result = await svc.embed_text("test")

        assert len(result) == 1536
        assert svc._http.post.call_count == 2

    async def test_retry_exhausted_raises(self, svc):
        """After 3 retries, raises RuntimeError."""
        svc._http = AsyncMock()
        svc._http.post = AsyncMock(
            side_effect=httpx.TimeoutException("timeout")
        )

        with patch("tron.infra.embeddings.service.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="failed after 3 retries"):
                await svc.embed_text("test")

        assert svc._http.post.call_count == 3


# ── Factory Function Tests ───────────────────────────────────────────


class TestFactory:

    def test_init_embeddings(self):
        """init_embeddings creates and returns service."""
        import tron.infra.embeddings.service as mod

        old = mod._embeddings_service
        try:
            svc = init_embeddings("sk-factory-test")
            assert isinstance(svc, EmbeddingsService)
        finally:
            mod._embeddings_service = old

    def test_get_embeddings_service_not_initialized(self):
        """get_embeddings_service raises if not initialized."""
        import tron.infra.embeddings.service as mod

        old = mod._embeddings_service
        try:
            mod._embeddings_service = None
            with pytest.raises(RuntimeError, match="not initialized"):
                get_embeddings_service()
        finally:
            mod._embeddings_service = old

    def test_get_embeddings_service_after_init(self):
        """get_embeddings_service returns the initialized instance."""
        import tron.infra.embeddings.service as mod

        old = mod._embeddings_service
        try:
            svc = init_embeddings("sk-factory-test2")
            result = get_embeddings_service()
            assert result is svc
        finally:
            mod._embeddings_service = old
