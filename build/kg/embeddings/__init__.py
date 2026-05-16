"""Spine KG embedding pipeline — EPIC-6.7 (STORY-6.7.1, 6.7.2).

Lazy, cached, provider-agnostic text-to-vector indexing on top of the
``spine_kg.kg_node_embedding`` pgvector store (V2). See ``embedder_README.md``.
"""
from .embedder import (AnthropicEmbeddingProvider, EmbedderRunner,
                       EmbeddingProvider, LocalEmbeddingProvider,
                       OpenAIEmbeddingProvider, SCHEMA_DIMENSIONS, select_provider)

__all__ = ["AnthropicEmbeddingProvider", "EmbedderRunner", "EmbeddingProvider",
           "LocalEmbeddingProvider", "OpenAIEmbeddingProvider",
           "SCHEMA_DIMENSIONS", "select_provider"]
