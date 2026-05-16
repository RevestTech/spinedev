"""
Unit tests for the Agent Memory System.

Tests:
  - MemoryType enum
  - AgentMemory model fields
  - MemoryStore.store() validation
  - MemoryStore.recall_recent() without embeddings
  - MemoryStore.get_context()
  - MemoryStore.cleanup_expired()
  - MemoryStore.consolidate()

Note: These tests mock the database layer since we can't use pgvector
with SQLite. The integration tests would use a real PostgreSQL DB.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tron.memory.types import MemoryType, MEMORY_TYPE_DESCRIPTIONS


# ── MemoryType Tests ──────────────────────────────────────────────────


class TestMemoryType:

    def test_all_five_types_exist(self):
        """All 5 memory types are defined."""
        expected = {"finding", "pattern", "context", "decision", "feedback"}
        actual = {m.value for m in MemoryType}
        assert actual == expected

    def test_str_enum(self):
        """MemoryType values are strings."""
        assert MemoryType.FINDING == "finding"
        assert str(MemoryType.PATTERN) == "MemoryType.PATTERN"

    def test_descriptions_complete(self):
        """Every MemoryType has a description."""
        for mt in MemoryType:
            assert mt in MEMORY_TYPE_DESCRIPTIONS
            assert len(MEMORY_TYPE_DESCRIPTIONS[mt]) > 0

    def test_from_string(self):
        """MemoryType can be created from string value."""
        assert MemoryType("finding") == MemoryType.FINDING
        assert MemoryType("feedback") == MemoryType.FEEDBACK

    def test_invalid_type_raises(self):
        """Invalid string raises ValueError."""
        with pytest.raises(ValueError):
            MemoryType("invalid_type")


# ── AgentMemory Model Tests ──────────────────────────────────────────


class TestAgentMemoryModel:

    def test_model_import(self):
        """AgentMemory model can be imported."""
        from tron.memory.models import AgentMemory
        assert AgentMemory.__tablename__ == "agent_memories"

    def test_model_fields(self):
        """AgentMemory has all expected columns."""
        from tron.memory.models import AgentMemory

        expected_columns = {
            "id", "agent_id", "memory_type", "project_id",
            "content", "metadata_json", "embedding",
            "relevance_score", "access_count",
            "created_at", "updated_at", "expires_at",
        }
        actual_columns = set(AgentMemory.__table__.columns.keys())
        assert expected_columns == actual_columns

    def test_model_repr(self):
        """AgentMemory repr includes key fields."""
        from tron.memory.models import AgentMemory

        m = MagicMock(spec=AgentMemory)
        m.id = uuid.uuid4()
        m.agent_id = "test-agent"
        m.memory_type = "finding"
        m.access_count = 5

        # Call the real __repr__ with our mock
        r = AgentMemory.__repr__(m)
        assert "test-agent" in r
        assert "finding" in r
        assert "5" in r

    def test_model_indexes(self):
        """AgentMemory table has expected indexes."""
        from tron.memory.models import AgentMemory

        index_names = {idx.name for idx in AgentMemory.__table__.indexes}
        assert "idx_agent_memories_agent_id" in index_names
        assert "idx_agent_memories_project_id" in index_names
        assert "idx_agent_memories_memory_type" in index_names
        assert "idx_agent_memories_created_at" in index_names
        assert "idx_agent_memories_expires_at" in index_names


# ── MemoryStore Tests ────────────────────────────────────────────────


class TestMemoryStoreValidation:
    """Tests for MemoryStore that don't need a real DB."""

    def test_init_without_embeddings(self):
        """MemoryStore initializes without embeddings service."""
        from tron.memory.store import MemoryStore

        mock_factory = MagicMock()
        store = MemoryStore(session_factory=mock_factory)
        assert store._embeddings_service is None

    def test_init_with_embeddings(self):
        """MemoryStore initializes with embeddings service."""
        from tron.memory.store import MemoryStore

        mock_factory = MagicMock()
        mock_embeddings = MagicMock()
        store = MemoryStore(
            session_factory=mock_factory,
            embeddings_service=mock_embeddings,
        )
        assert store._embeddings_service is mock_embeddings


class TestMemoryStoreStore:
    """Tests for MemoryStore.store() method."""

    @pytest.fixture
    def mock_session(self):
        """Mock async session that supports context manager."""
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        return session

    @pytest.fixture
    def mock_factory(self, mock_session):
        """Mock session factory returning mock_session."""
        factory = MagicMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = ctx
        return factory

    @pytest.fixture
    def store(self, mock_factory):
        from tron.memory.store import MemoryStore
        return MemoryStore(session_factory=mock_factory)

    async def test_store_valid_memory(self, store, mock_session):
        """store() creates an AgentMemory with valid inputs."""
        result = await store.store(
            agent_id="security-iso",
            memory_type="finding",
            content="SQL injection pattern detected in user input handling",
        )

        from tron.memory.models import AgentMemory
        assert isinstance(result, AgentMemory)
        assert result.agent_id == "security-iso"
        assert result.memory_type == "finding"
        assert result.content == "SQL injection pattern detected in user input handling"

    async def test_store_invalid_type_raises(self, store):
        """store() with invalid memory_type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid memory_type"):
            await store.store(
                agent_id="test",
                memory_type="invalid_type",
                content="test",
            )

    async def test_store_with_ttl(self, store):
        """store() with ttl_hours sets expires_at."""
        result = await store.store(
            agent_id="test",
            memory_type="context",
            content="temp context",
            ttl_hours=24,
        )

        assert result.expires_at is not None
        # Should be roughly 24 hours from now
        delta = result.expires_at - datetime.now(timezone.utc)
        assert 23 * 3600 < delta.total_seconds() < 25 * 3600

    async def test_store_with_metadata(self, store):
        """store() includes metadata_json."""
        result = await store.store(
            agent_id="test",
            memory_type="decision",
            content="Decided to skip console.log in tests",
            metadata={"reason": "too noisy", "confidence": 0.9},
        )

        assert result.metadata_json == {"reason": "too noisy", "confidence": 0.9}

    async def test_store_with_project_id(self, store):
        """store() converts string project_id to UUID."""
        pid = str(uuid.uuid4())
        result = await store.store(
            agent_id="test",
            memory_type="context",
            content="Uses Flask",
            project_id=pid,
        )

        assert result.project_id == uuid.UUID(pid)

    async def test_store_with_invalid_project_id(self, store):
        """store() with invalid project_id treats it as None."""
        result = await store.store(
            agent_id="test",
            memory_type="context",
            content="test",
            project_id="not-a-uuid",
        )

        assert result.project_id is None

    async def test_store_with_embeddings(self, mock_factory):
        """store() generates embedding when service available."""
        from tron.memory.store import MemoryStore

        mock_embeddings = AsyncMock()
        mock_embeddings.embed_text = AsyncMock(return_value=[0.1] * 1536)

        store = MemoryStore(
            session_factory=mock_factory,
            embeddings_service=mock_embeddings,
        )

        result = await store.store(
            agent_id="test",
            memory_type="finding",
            content="test content",
        )

        mock_embeddings.embed_text.assert_called_once_with("test content")
        assert result.embedding == [0.1] * 1536

    async def test_store_embedding_failure_graceful(self, mock_factory):
        """store() continues without embedding if service fails."""
        from tron.memory.store import MemoryStore

        mock_embeddings = AsyncMock()
        mock_embeddings.embed_text = AsyncMock(side_effect=RuntimeError("API error"))

        store = MemoryStore(
            session_factory=mock_factory,
            embeddings_service=mock_embeddings,
        )

        result = await store.store(
            agent_id="test",
            memory_type="finding",
            content="test content",
        )

        # Should succeed without embedding
        assert result.embedding is None


class TestMemoryStoreRecall:
    """Tests for recall methods."""

    async def test_recall_empty_query(self):
        """recall() with empty query returns empty list."""
        from tron.memory.store import MemoryStore

        store = MemoryStore(session_factory=MagicMock())
        result = await store.recall(query="")
        assert result == []

    async def test_recall_whitespace_query(self):
        """recall() with whitespace-only query returns empty list."""
        from tron.memory.store import MemoryStore

        store = MemoryStore(session_factory=MagicMock())
        result = await store.recall(query="   ")
        assert result == []


class TestMemoryStoreConsolidate:
    """Tests for consolidation."""

    async def test_consolidate_without_embeddings(self):
        """consolidate() returns 0 when no embeddings service."""
        from tron.memory.store import MemoryStore

        store = MemoryStore(session_factory=MagicMock())
        result = await store.consolidate(agent_id="test")
        assert result == 0


class TestMemoryResult:
    """Tests for MemoryResult dataclass."""

    def test_memory_result_fields(self):
        """MemoryResult has expected fields."""
        from tron.memory.store import MemoryResult
        from tron.memory.models import AgentMemory

        m = MagicMock(spec=AgentMemory)
        m.id = uuid.uuid4()
        m.agent_id = "test"
        m.memory_type = "finding"
        m.content = "test"
        m.access_count = 0

        mr = MemoryResult(memory=m, similarity=0.95)
        assert mr.similarity == 0.95
        assert mr.memory.agent_id == "test"
