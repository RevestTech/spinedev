"""Embeddings service — async vector embeddings for code analysis.

Provides text and code embeddings with retry logic and batch processing.
Uses OpenAI embeddings API directly (httpx async client, no openai library).
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Module-level instance for factory pattern
_embeddings_service: Optional[EmbeddingsService] = None


class EmbeddingsService:
    """Async embeddings service using OpenAI API.

    Features:
        - Text and code-aware embeddings
        - Batch processing with rate limiting
        - Retry with exponential backoff
        - Cosine similarity computation
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-large",
        dimensions: int = 1536,
    ) -> None:
        """Initialize the embeddings service.

        Args:
            api_key: OpenAI API key.
            model: Model name (default: text-embedding-3-large).
            dimensions: Vector dimension size (default: 1536).

        Raises:
            ValueError: If api_key is empty or invalid.
        """
        if not api_key or api_key == "REPLACE_ME_IN_VAULT":
            raise ValueError(
                "EmbeddingsService: api_key is missing or not configured. "
                "Set it in the container keyvault before using embeddings."
            )
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._http = httpx.AsyncClient(timeout=30)

    async def embed_text(self, text: str) -> List[float]:
        """Embed a single text string.

        Args:
            text: Text to embed.

        Returns:
            List of floats (vector embedding).

        Raises:
            RuntimeError: If API call fails after retries.
        """
        vectors = await self.embed_batch([text])
        return vectors[0] if vectors else []

    async def embed_batch(
        self,
        texts: List[str],
        batch_size: int = 100,
    ) -> List[List[float]]:
        """Embed multiple texts in batches.

        Args:
            texts: List of texts to embed.
            batch_size: Batch size for API calls (default: 100, max: 2048).

        Returns:
            List of embedding vectors (one per input text).
        """
        if not texts:
            return []

        # Clamp batch_size to OpenAI limits
        batch_size = min(batch_size, 2048)

        all_embeddings: List[List[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_embeddings = await self._embed_batch_internal(batch)
            all_embeddings.extend(batch_embeddings)

            # Rate limit between batches
            if i + batch_size < len(texts):
                await asyncio.sleep(0.1)

        return all_embeddings

    async def embed_code(
        self,
        code: str,
        language: str,
        context: str = "",
    ) -> List[float]:
        """Embed code with language and context priming.

        Prepends language and context to the code to influence the embedding
        towards code semantics rather than natural language.

        Args:
            code: Source code to embed.
            language: Programming language (python, javascript, etc.).
            context: Optional context (e.g., "async network code").

        Returns:
            List of floats (vector embedding).
        """
        # Prime the embedding with language + context
        prefix = f"[{language.upper()}"
        if context:
            prefix += f": {context}"
        prefix += "]\n"

        primed_text = prefix + code

        return await self.embed_text(primed_text)

    async def similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """Compute cosine similarity between two vectors.

        Args:
            vec_a: First vector.
            vec_b: Second vector.

        Returns:
            Cosine similarity score (0.0 to 1.0).
        """
        if not vec_a or not vec_b:
            return 0.0

        # Cosine similarity = (A · B) / (|A| * |B|)
        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    # ── Internal ───────────────────────────────────────────────────

    async def _embed_batch_internal(
        self,
        texts: List[str],
    ) -> List[List[float]]:
        """Internal batch embedding with retry logic.

        Args:
            texts: List of texts (up to 2048 per batch).

        Returns:
            List of embeddings in input order.

        Raises:
            RuntimeError: If API call fails after 3 retries.
        """
        max_retries = 3

        for attempt in range(max_retries):
            try:
                response = await self._call_openai_embeddings(texts)
                return response
            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(
                        "Embeddings API failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1,
                        max_retries,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        "Embeddings API failed after %d retries: %s",
                        max_retries,
                        exc,
                    )
                    raise RuntimeError(
                        f"Embeddings API failed after {max_retries} retries: {exc}"
                    )

        return []  # Should not reach

    async def _call_openai_embeddings(
        self,
        texts: List[str],
    ) -> List[List[float]]:
        """Call OpenAI embeddings API directly.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embeddings.

        Raises:
            httpx.HTTPStatusError: If API returns error.
            httpx.TimeoutException: If request times out.
        """
        payload = {
            "model": self._model,
            "input": texts,
        }

        # Add dimensions param for text-embedding-3-* models
        if "text-embedding-3" in self._model:
            payload["dimensions"] = self._dimensions

        resp = await self._http.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        # Extract embeddings in input order
        embeddings: Dict[int, List[float]] = {}
        for item in data.get("data", []):
            index = item.get("index", 0)
            embedding = item.get("embedding", [])
            embeddings[index] = embedding

        # Return in input order
        return [embeddings.get(i, []) for i in range(len(texts))]

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()

    def __repr__(self) -> str:
        return (
            f"<EmbeddingsService model={self._model} "
            f"dimensions={self._dimensions}>"
        )


# ── Factory Functions ──────────────────────────────────────────────────


def init_embeddings(api_key: str) -> EmbeddingsService:
    """Initialize and set the global embeddings service.

    Args:
        api_key: OpenAI API key.

    Returns:
        The initialized EmbeddingsService instance.
    """
    global _embeddings_service
    _embeddings_service = EmbeddingsService(api_key=api_key)
    logger.info("EmbeddingsService initialized")
    return _embeddings_service


def get_embeddings_service() -> EmbeddingsService:
    """Get the global embeddings service instance.

    Returns:
        The EmbeddingsService instance.

    Raises:
        RuntimeError: If service was not initialized via init_embeddings().
    """
    if _embeddings_service is None:
        raise RuntimeError(
            "EmbeddingsService not initialized. Call init_embeddings() first."
        )
    return _embeddings_service
