"""Embeddings service — async vector embedding via OpenAI API.

Provides code-aware embeddings with language and context priming,
batch processing, and cosine similarity computation.
"""

from tron.infra.embeddings.service import (
    EmbeddingsService,
    init_embeddings,
    get_embeddings_service,
)

__all__ = [
    "EmbeddingsService",
    "init_embeddings",
    "get_embeddings_service",
]
