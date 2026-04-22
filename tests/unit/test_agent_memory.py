"""
Comprehensive tests for the AgentMemory module (tron/agents/memory.py).

Covers:
    - MemoryCategory enum values and descriptions
    - MemoryEntry creation, defaults, expiration logic
    - RecallResult dataclass
    - AgentMemoryManager in-memory mode:
        - remember() across all 5 categories
        - recall() with keyword-based similarity
        - store_episode(), learn_fact(), learn_procedure()
        - set_working() / get_working() with auto-expiry
        - reflect() meta-cognitive storage
        - get_context() cross-category retrieval
        - prune_expired() cleanup
        - decay_importance() aging
        - stats() reporting
    - AgentMemoryManager with mock embeddings
    - Edge cases: empty queries, expired entries, importance clamping
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from tron.agents.memory import (
    AgentMemoryManager,
    MemoryCategory,
    MemoryEntry,
    RecallResult,
    MEMORY_CATEGORY_DESCRIPTIONS,
    DEFAULT_TTL_HOURS,
)


# ── MemoryCategory Enum ──────────────────────────────────────────────────


class TestMemoryCategory:
    """Tests for MemoryCategory enum."""

    def test_five_categories_defined(self) -> None:
        """All 5 cognitive memory types are present."""
        assert len(MemoryCategory) == 5

    def test_episodic_value(self) -> None:
        assert MemoryCategory.EPISODIC.value == "episodic"

    def test_semantic_value(self) -> None:
        assert MemoryCategory.SEMANTIC.value == "semantic"

    def test_procedural_value(self) -> None:
        assert MemoryCategory.PROCEDURAL.value == "procedural"

    def test_working_value(self) -> None:
        assert MemoryCategory.WORKING.value == "working"

    def test_meta_value(self) -> None:
        assert MemoryCategory.META.value == "meta"

    def test_all_values_match_migration_constraint(self) -> None:
        """Values match the CHECK constraint in migration 002."""
        expected = {"episodic", "semantic", "procedural", "working", "meta"}
        actual = {c.value for c in MemoryCategory}
        assert actual == expected

    def test_is_string_enum(self) -> None:
        """MemoryCategory is a str enum — values are usable as strings."""
        assert isinstance(MemoryCategory.EPISODIC, str)
        assert MemoryCategory.EPISODIC == "episodic"

    def test_all_categories_have_descriptions(self) -> None:
        """Every category has a description in MEMORY_CATEGORY_DESCRIPTIONS."""
        for cat in MemoryCategory:
            assert cat in MEMORY_CATEGORY_DESCRIPTIONS
            assert len(MEMORY_CATEGORY_DESCRIPTIONS[cat]) > 10


class TestDefaultTTLHours:
    """Tests for DEFAULT_TTL_HOURS mapping."""

    def test_working_memory_has_ttl(self) -> None:
        assert DEFAULT_TTL_HOURS[MemoryCategory.WORKING] == 4

    def test_episodic_is_permanent(self) -> None:
        assert DEFAULT_TTL_HOURS[MemoryCategory.EPISODIC] is None

    def test_semantic_is_permanent(self) -> None:
        assert DEFAULT_TTL_HOURS[MemoryCategory.SEMANTIC] is None

    def test_procedural_is_permanent(self) -> None:
        assert DEFAULT_TTL_HOURS[MemoryCategory.PROCEDURAL] is None

    def test_meta_is_permanent(self) -> None:
        assert DEFAULT_TTL_HOURS[MemoryCategory.META] is None

    def test_all_categories_have_ttl_entry(self) -> None:
        for cat in MemoryCategory:
            assert cat in DEFAULT_TTL_HOURS


# ── MemoryEntry ──────────────────────────────────────────────────────────


class TestMemoryEntry:
    """Tests for MemoryEntry dataclass."""

    def test_default_creation(self) -> None:
        entry = MemoryEntry()
        assert entry.id is None
        assert entry.agent_id == ""
        assert entry.memory_type == ""
        assert entry.key == ""
        assert entry.value == {}
        assert entry.text == ""
        assert entry.embedding is None
        assert entry.metadata is None
        assert entry.importance == 0.5
        assert entry.access_count == 0
        assert entry.last_accessed_at is None
        assert entry.expires_at is None
        assert entry.created_at is None

    def test_creation_with_values(self) -> None:
        now = datetime.now(timezone.utc)
        entry = MemoryEntry(
            id="mem-1",
            agent_id="security-iso",
            memory_type="episodic",
            key="audit-abc",
            value={"findings": 5},
            text="Audit found 5 critical issues",
            importance=0.8,
            created_at=now,
        )
        assert entry.id == "mem-1"
        assert entry.agent_id == "security-iso"
        assert entry.memory_type == "episodic"
        assert entry.value["findings"] == 5
        assert entry.importance == 0.8

    def test_is_expired_when_no_expiry(self) -> None:
        entry = MemoryEntry(expires_at=None)
        assert entry.is_expired is False

    def test_is_expired_when_future(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        entry = MemoryEntry(expires_at=future)
        assert entry.is_expired is False

    def test_is_expired_when_past(self) -> None:
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        entry = MemoryEntry(expires_at=past)
        assert entry.is_expired is True

    def test_is_expired_boundary(self) -> None:
        """Exactly at expiry time counts as expired."""
        now = datetime.now(timezone.utc) - timedelta(seconds=1)
        entry = MemoryEntry(expires_at=now)
        assert entry.is_expired is True


# ── RecallResult ─────────────────────────────────────────────────────────


class TestRecallResult:
    """Tests for RecallResult dataclass."""

    def test_creation(self) -> None:
        entry = MemoryEntry(id="mem-1", text="test")
        result = RecallResult(entry=entry, similarity=0.85)
        assert result.entry.id == "mem-1"
        assert result.similarity == 0.85

    def test_default_similarity(self) -> None:
        entry = MemoryEntry()
        result = RecallResult(entry=entry)
        assert result.similarity == 0.0


# ── AgentMemoryManager (in-memory mode) ──────────────────────────────────


@pytest.mark.asyncio
class TestAgentMemoryManagerInit:
    """Tests for AgentMemoryManager initialization."""

    async def test_init_defaults(self) -> None:
        mgr = AgentMemoryManager(agent_id="test-agent")
        assert mgr.agent_id == "test-agent"
        assert mgr._embeddings_fn is None
        assert mgr._storage is None
        assert mgr._working_ttl_hours == 4

    async def test_init_with_embeddings(self) -> None:
        embed_fn = AsyncMock(return_value=[0.1] * 3072)
        mgr = AgentMemoryManager(
            agent_id="test-agent",
            embeddings_fn=embed_fn,
        )
        assert mgr._embeddings_fn is embed_fn

    async def test_repr(self) -> None:
        mgr = AgentMemoryManager(agent_id="sec-iso")
        r = repr(mgr)
        assert "sec-iso" in r
        assert "in-memory" in r
        assert "embeddings" in r


@pytest.mark.asyncio
class TestRemember:
    """Tests for remember() core method."""

    async def test_remember_episodic(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.remember(
            category=MemoryCategory.EPISODIC,
            key="audit-run-1",
            text="Ran security audit on project X",
            value={"findings": 3},
        )
        assert entry.agent_id == "agent-1"
        assert entry.memory_type == "episodic"
        assert entry.key == "audit-run-1"
        assert entry.value == {"findings": 3}
        assert entry.id is not None
        assert entry.expires_at is None  # Episodic = permanent

    async def test_remember_working_has_ttl(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.remember(
            category=MemoryCategory.WORKING,
            key="scratch-1",
            text="Temporary data",
        )
        assert entry.expires_at is not None
        # Default working TTL is 4 hours
        delta = entry.expires_at - datetime.now(timezone.utc)
        assert timedelta(hours=3, minutes=50) < delta < timedelta(hours=4, minutes=10)

    async def test_remember_custom_ttl_overrides_default(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.remember(
            category=MemoryCategory.SEMANTIC,
            key="fact-1",
            text="A learned fact",
            ttl_hours=24,  # Override: semantic is normally permanent
        )
        assert entry.expires_at is not None

    async def test_remember_clamps_importance_high(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.remember(
            category=MemoryCategory.SEMANTIC,
            key="fact-1",
            text="test",
            importance=1.5,
        )
        assert entry.importance == 1.0

    async def test_remember_clamps_importance_low(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.remember(
            category=MemoryCategory.SEMANTIC,
            key="fact-1",
            text="test",
            importance=-0.5,
        )
        assert entry.importance == 0.0

    async def test_remember_with_metadata(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.remember(
            category=MemoryCategory.META,
            key="meta-1",
            text="reflection",
            metadata={"source": "cross-validation"},
        )
        assert entry.metadata == {"source": "cross-validation"}

    async def test_remember_generates_embedding(self) -> None:
        embed_fn = AsyncMock(return_value=[0.1, 0.2, 0.3])
        mgr = AgentMemoryManager(agent_id="agent-1", embeddings_fn=embed_fn)

        entry = await mgr.remember(
            category=MemoryCategory.SEMANTIC,
            key="fact",
            text="SQL injection in Django ORM",
        )
        assert entry.embedding == [0.1, 0.2, 0.3]
        embed_fn.assert_called_once_with("SQL injection in Django ORM")

    async def test_remember_handles_embedding_failure(self) -> None:
        embed_fn = AsyncMock(side_effect=RuntimeError("API down"))
        mgr = AgentMemoryManager(agent_id="agent-1", embeddings_fn=embed_fn)

        entry = await mgr.remember(
            category=MemoryCategory.SEMANTIC,
            key="fact",
            text="A fact",
        )
        assert entry.embedding is None  # Gracefully handles failure

    async def test_remember_assigns_unique_ids(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        e1 = await mgr.remember(MemoryCategory.SEMANTIC, "k1", "text1")
        e2 = await mgr.remember(MemoryCategory.SEMANTIC, "k2", "text2")
        assert e1.id != e2.id

    async def test_remember_sets_created_at(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        before = datetime.now(timezone.utc)
        entry = await mgr.remember(MemoryCategory.EPISODIC, "k1", "text")
        after = datetime.now(timezone.utc)
        assert before <= entry.created_at <= after


@pytest.mark.asyncio
class TestRecall:
    """Tests for recall() semantic search."""

    async def test_recall_empty_query_returns_empty(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        results = await mgr.recall("")
        assert results == []

    async def test_recall_whitespace_query_returns_empty(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        results = await mgr.recall("   ")
        assert results == []

    async def test_recall_matching_keyword(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        await mgr.remember(MemoryCategory.SEMANTIC, "k1", "SQL injection vulnerability")
        await mgr.remember(MemoryCategory.SEMANTIC, "k2", "buffer overflow in C code")

        results = await mgr.recall("SQL injection")
        assert len(results) >= 1
        assert any("SQL" in r.entry.text for r in results)

    async def test_recall_filters_by_category(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        await mgr.remember(MemoryCategory.SEMANTIC, "k1", "SQL injection facts")
        await mgr.remember(MemoryCategory.EPISODIC, "k2", "SQL injection episode")

        results = await mgr.recall(
            "SQL injection",
            category=MemoryCategory.SEMANTIC,
        )
        for r in results:
            assert r.entry.memory_type == "semantic"

    async def test_recall_filters_by_agent_id(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        await mgr.remember(MemoryCategory.SEMANTIC, "k1", "memory for agent-1")

        # Memories stored by agent-1 should not appear for agent-2
        mgr2 = AgentMemoryManager(agent_id="agent-2")
        results = await mgr2.recall("memory for agent-1")
        assert len(results) == 0

    async def test_recall_skips_expired(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.remember(
            MemoryCategory.WORKING, "k1", "temporary data", ttl_hours=0
        )
        # Force expiry
        entry.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        results = await mgr.recall("temporary data")
        expired_results = [r for r in results if r.entry.key == "k1"]
        assert len(expired_results) == 0

    async def test_recall_increments_access_count(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        await mgr.remember(MemoryCategory.SEMANTIC, "k1", "test recall access count")

        results = await mgr.recall("test recall access count")
        if results:
            assert results[0].entry.access_count >= 1

    async def test_recall_respects_limit(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        for i in range(20):
            await mgr.remember(MemoryCategory.SEMANTIC, f"k{i}", f"memory number {i}")

        results = await mgr.recall("memory number", limit=5)
        assert len(results) <= 5

    async def test_recall_sorted_by_similarity_and_importance(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        await mgr.remember(MemoryCategory.SEMANTIC, "k1", "high importance", importance=0.9)
        await mgr.remember(MemoryCategory.SEMANTIC, "k2", "low importance", importance=0.1)

        results = await mgr.recall("importance")
        if len(results) >= 2:
            assert results[0].entry.importance >= results[1].entry.importance


# ── Convenience Methods ──────────────────────────────────────────────────


@pytest.mark.asyncio
class TestStoreEpisode:
    """Tests for store_episode() convenience method."""

    async def test_store_episode(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.store_episode(
            key="audit-run-abc",
            description="Security audit found 5 critical issues",
            audit_data={"findings_count": 5, "severity": "critical"},
            importance=0.8,
        )
        assert entry.memory_type == "episodic"
        assert entry.key == "audit-run-abc"
        assert entry.value["findings_count"] == 5
        assert entry.importance == 0.8
        assert entry.expires_at is None  # Permanent


@pytest.mark.asyncio
class TestLearnFact:
    """Tests for learn_fact() convenience method."""

    async def test_learn_fact(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.learn_fact(
            key="vuln-sqli-django",
            fact="Django ORM parameterizes queries by default",
            evidence={"source": "Django docs"},
        )
        assert entry.memory_type == "semantic"
        assert entry.importance == 0.6  # Default for facts

    async def test_learn_fact_custom_importance(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.learn_fact(
            key="fact-1",
            fact="Important fact",
            importance=0.95,
        )
        assert entry.importance == 0.95


@pytest.mark.asyncio
class TestLearnProcedure:
    """Tests for learn_procedure() convenience method."""

    async def test_learn_procedure(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.learn_procedure(
            key="strategy-django-auth",
            procedure="For Django auth audits, check settings then middleware",
            steps=["Check DEBUG flag", "Check ALLOWED_HOSTS", "Review middleware"],
            conditions={"framework": "django", "check_type": "auth"},
        )
        assert entry.memory_type == "procedural"
        assert entry.value["steps"] == ["Check DEBUG flag", "Check ALLOWED_HOSTS", "Review middleware"]
        assert entry.value["conditions"]["framework"] == "django"
        assert entry.importance == 0.7  # Default for procedures

    async def test_learn_procedure_without_steps(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.learn_procedure(
            key="proc-1",
            procedure="General approach",
        )
        assert "steps" not in entry.value


@pytest.mark.asyncio
class TestWorkingMemory:
    """Tests for set_working() and get_working()."""

    async def test_set_working(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.set_working(
            key="file-graph",
            text="Current dependency graph",
            data={"nodes": 10, "edges": 15},
        )
        assert entry.memory_type == "working"
        assert entry.importance == 0.3
        assert entry.expires_at is not None
        assert entry.value["nodes"] == 10

    async def test_get_working_found(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        await mgr.set_working(key="scratch", text="temp value")

        result = await mgr.get_working("scratch")
        assert result is not None
        assert result.key == "scratch"
        assert result.text == "temp value"

    async def test_get_working_not_found(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        result = await mgr.get_working("nonexistent")
        assert result is None

    async def test_get_working_skips_expired(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.set_working(key="old", text="expired data")
        # Force expiry
        entry.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        result = await mgr.get_working("old")
        assert result is None

    async def test_get_working_increments_access_count(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        await mgr.set_working(key="counter-test", text="data")

        result = await mgr.get_working("counter-test")
        assert result is not None
        assert result.access_count == 1

    async def test_working_memory_custom_ttl(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1", working_ttl_hours=1)
        entry = await mgr.set_working(key="short", text="short-lived")
        delta = entry.expires_at - datetime.now(timezone.utc)
        assert timedelta(minutes=50) < delta < timedelta(hours=1, minutes=10)


@pytest.mark.asyncio
class TestReflect:
    """Tests for reflect() meta-cognitive storage."""

    async def test_reflect(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.reflect(
            key="accuracy-xss",
            reflection="My XSS detection in React has 35% false positive rate",
            metrics={"fp_rate": 0.35, "sample_size": 100},
        )
        assert entry.memory_type == "meta"
        assert entry.value["fp_rate"] == 0.35
        assert entry.importance == 0.6

    async def test_reflect_custom_importance(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.reflect(
            key="critical-insight",
            reflection="Very important self-observation",
            importance=0.95,
        )
        assert entry.importance == 0.95


# ── Context Assembly ─────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetContext:
    """Tests for get_context() cross-category retrieval."""

    async def test_get_context_returns_relevant_memories(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        await mgr.learn_fact("f1", "SQL injection patterns in Django")
        await mgr.learn_procedure("p1", "Django security audit procedure")
        await mgr.store_episode("e1", "Past Django security audit", {"ok": True})

        context = await mgr.get_context("Django security audit")
        assert len(context) >= 1

    async def test_get_context_excludes_working_by_default(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        await mgr.set_working("w1", "working memory item about Django")
        await mgr.learn_fact("f1", "fact about Django")

        context = await mgr.get_context("Django")
        memory_types = {e.memory_type for e in context}
        assert "working" not in memory_types

    async def test_get_context_filters_by_importance(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        await mgr.remember(MemoryCategory.SEMANTIC, "low", "low importance fact", importance=0.1)
        await mgr.remember(MemoryCategory.SEMANTIC, "high", "high importance fact", importance=0.9)

        context = await mgr.get_context("fact", min_importance=0.5)
        for entry in context:
            assert entry.importance >= 0.5

    async def test_get_context_respects_limit(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        for i in range(30):
            await mgr.learn_fact(f"f{i}", f"fact number {i}")

        context = await mgr.get_context("fact", limit=5)
        assert len(context) <= 5

    async def test_get_context_specific_categories(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        await mgr.learn_fact("f1", "a semantic fact")
        await mgr.store_episode("e1", "an episode", {})
        await mgr.reflect("m1", "a meta reflection")

        context = await mgr.get_context(
            "test",
            categories=[MemoryCategory.SEMANTIC, MemoryCategory.META],
        )
        types = {e.memory_type for e in context}
        assert "episodic" not in types


# ── Maintenance ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestPruneExpired:
    """Tests for prune_expired()."""

    async def test_prune_expired_removes_old_working(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.set_working("old", "expired working memory")
        entry.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        count = await mgr.prune_expired()
        assert count == 1

    async def test_prune_expired_keeps_valid(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        await mgr.set_working("fresh", "still valid")
        await mgr.learn_fact("f1", "permanent fact")

        count = await mgr.prune_expired()
        assert count == 0

    async def test_prune_expired_only_prunes_own_agent(self) -> None:
        mgr1 = AgentMemoryManager(agent_id="agent-1")
        mgr2 = AgentMemoryManager(agent_id="agent-2")

        entry = await mgr1.set_working("old", "expired")
        entry.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        # Agent-2's prune should not affect agent-1's local store
        count = await mgr2.prune_expired()
        assert count == 0


@pytest.mark.asyncio
class TestDecayImportance:
    """Tests for decay_importance()."""

    async def test_decay_old_memories(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.remember(
            MemoryCategory.SEMANTIC, "old-fact", "old fact", importance=1.0
        )
        # Fake old creation date
        entry.created_at = datetime.now(timezone.utc) - timedelta(days=60)

        decayed = await mgr.decay_importance(older_than_days=30, decay_factor=0.5)
        assert decayed == 1
        assert entry.importance == 0.5

    async def test_decay_skips_recent(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.remember(
            MemoryCategory.SEMANTIC, "new-fact", "recent fact", importance=1.0
        )

        decayed = await mgr.decay_importance(older_than_days=30)
        assert decayed == 0
        assert entry.importance == 1.0

    async def test_decay_custom_factor(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.remember(
            MemoryCategory.EPISODIC, "old-ep", "old episode", importance=0.8
        )
        entry.created_at = datetime.now(timezone.utc) - timedelta(days=90)

        await mgr.decay_importance(older_than_days=30, decay_factor=0.9)
        assert abs(entry.importance - 0.72) < 0.01  # 0.8 * 0.9 = 0.72


# ── Stats ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestStats:
    """Tests for stats() reporting."""

    async def test_stats_empty(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        s = await mgr.stats()
        assert s["agent_id"] == "agent-1"
        assert s["total_memories"] == 0
        assert s["by_category"] == {}
        assert s["avg_importance"] == 0.0
        assert s["total_access_count"] == 0

    async def test_stats_with_memories(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        await mgr.learn_fact("f1", "fact 1")
        await mgr.learn_fact("f2", "fact 2")
        await mgr.store_episode("e1", "episode 1", {})
        await mgr.reflect("m1", "reflection 1")

        s = await mgr.stats()
        assert s["total_memories"] == 4
        assert s["by_category"]["semantic"] == 2
        assert s["by_category"]["episodic"] == 1
        assert s["by_category"]["meta"] == 1

    async def test_stats_excludes_expired(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.set_working("w1", "working mem")
        entry.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        await mgr.learn_fact("f1", "permanent fact")

        s = await mgr.stats()
        assert s["total_memories"] == 1  # Only the permanent fact


# ── Embedding Integration ────────────────────────────────────────────────


@pytest.mark.asyncio
class TestEmbeddingIntegration:
    """Tests for embedding-related functionality."""

    async def test_remember_calls_embedding_fn(self) -> None:
        embed_fn = AsyncMock(return_value=[0.1] * 3072)
        mgr = AgentMemoryManager(agent_id="agent-1", embeddings_fn=embed_fn)

        await mgr.remember(MemoryCategory.SEMANTIC, "k", "test text")
        embed_fn.assert_called_once_with("test text")

    async def test_remember_empty_text_still_stores(self) -> None:
        embed_fn = AsyncMock(return_value=[])
        mgr = AgentMemoryManager(agent_id="agent-1", embeddings_fn=embed_fn)

        entry = await mgr.remember(MemoryCategory.SEMANTIC, "k", "")
        assert entry.id is not None
        # Empty text should not call embeddings
        embed_fn.assert_not_called()

    async def test_embedding_failure_does_not_prevent_storage(self) -> None:
        embed_fn = AsyncMock(side_effect=Exception("connection refused"))
        mgr = AgentMemoryManager(agent_id="agent-1", embeddings_fn=embed_fn)

        entry = await mgr.remember(MemoryCategory.SEMANTIC, "k", "text")
        assert entry.id is not None
        assert entry.embedding is None


# ── Edge Cases ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestEdgeCases:
    """Edge case tests."""

    async def test_multiple_agents_isolated(self) -> None:
        mgr1 = AgentMemoryManager(agent_id="agent-1")
        mgr2 = AgentMemoryManager(agent_id="agent-2")

        await mgr1.learn_fact("f1", "fact for agent 1")
        await mgr2.learn_fact("f1", "fact for agent 2")

        s1 = await mgr1.stats()
        s2 = await mgr2.stats()
        assert s1["total_memories"] == 1
        assert s2["total_memories"] == 1

    async def test_all_five_categories_storable(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        for cat in MemoryCategory:
            entry = await mgr.remember(cat, f"key-{cat.value}", f"text for {cat.value}")
            assert entry.memory_type == cat.value

        s = await mgr.stats()
        # Working may expire instantly if TTL=0, but default is 4h so it should be here
        assert s["total_memories"] == 5

    async def test_large_value_payload(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        large_value = {f"key_{i}": f"value_{i}" * 100 for i in range(100)}
        entry = await mgr.remember(
            MemoryCategory.EPISODIC,
            key="large",
            text="large payload test",
            value=large_value,
        )
        assert len(entry.value) == 100

    async def test_special_characters_in_text(self) -> None:
        mgr = AgentMemoryManager(agent_id="agent-1")
        entry = await mgr.remember(
            MemoryCategory.SEMANTIC,
            key="special",
            text="SQL: SELECT * FROM users WHERE id = '1'; -- injection",
        )
        assert "SELECT" in entry.text
        assert "injection" in entry.text

    async def test_concurrent_operations(self) -> None:
        """Multiple async operations don't corrupt state."""
        import asyncio

        mgr = AgentMemoryManager(agent_id="agent-1")

        async def store_batch(start: int) -> None:
            for i in range(start, start + 10):
                await mgr.learn_fact(f"f{i}", f"fact {i}")

        await asyncio.gather(store_batch(0), store_batch(10), store_batch(20))

        s = await mgr.stats()
        assert s["total_memories"] == 30
