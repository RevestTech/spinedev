"""
AgentMemory — High-level memory system for ISO agents.

Implements the 5 cognitive memory types defined in migration 002:
    - episodic:    Records of past audit executions and outcomes
    - semantic:    Learned facts about code, vulnerabilities, standards
    - procedural:  How-to knowledge — successful analysis strategies
    - working:     Short-lived, per-execution scratchpad (auto-expires)
    - meta:        Self-reflective notes on agent accuracy and confidence

Uses pgvector (3072-dim) for semantic recall and integrates with the
existing EmbeddingsService and MemoryStore infrastructure.

Architecture ref: docs/architecture/AI_AGENT_ARCHITECTURE.md §5
Migration ref:    docs/archive/legacy-sql/002_agent_memory.sql (superseded by Alembic)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


# ── Memory Types (migration 002 schema) ──────────────────────────────────


class MemoryCategory(str, Enum):
    """The 5 cognitive memory types from the agent_memory table.

    These map directly to the CHECK constraint in migration 002:
        memory_type IN ('episodic', 'semantic', 'procedural', 'working', 'meta')
    """

    EPISODIC = "episodic"
    """Records of past audit executions, findings, and outcomes.

    Examples:
    - "Audit run abc123 on project X found 4 critical SQL injection issues"
    - "Cross-validation disagreed on 2/5 findings in last security scan"
    """

    SEMANTIC = "semantic"
    """Learned facts about code patterns, vulnerabilities, and standards.

    Examples:
    - "React useEffect with empty deps array runs only on mount"
    - "OWASP Top 10 2021: A03 Injection includes SQL, NoSQL, OS, LDAP"
    """

    PROCEDURAL = "procedural"
    """How-to knowledge — strategies that worked for specific analysis tasks.

    Examples:
    - "For Django projects, check settings.py DEBUG flag + ALLOWED_HOSTS first"
    - "When analyzing JWT auth, examine token expiry, algorithm, and secret storage"
    """

    WORKING = "working"
    """Short-lived scratchpad for the current execution context.

    Auto-expires after the configured TTL (default: 4 hours).
    Used for intermediate reasoning, file dependency graphs, and
    cross-agent context sharing during a single audit run.
    """

    META = "meta"
    """Self-reflective notes on agent accuracy and confidence calibration.

    Examples:
    - "My false positive rate for XSS findings in React apps is ~35%"
    - "I tend to miss race conditions in async Python code"
    """


MEMORY_CATEGORY_DESCRIPTIONS: Dict[MemoryCategory, str] = {
    MemoryCategory.EPISODIC: "Records of past executions and outcomes",
    MemoryCategory.SEMANTIC: "Learned facts about code, vulnerabilities, standards",
    MemoryCategory.PROCEDURAL: "Successful analysis strategies and procedures",
    MemoryCategory.WORKING: "Short-lived per-execution scratchpad",
    MemoryCategory.META: "Self-reflective accuracy and confidence notes",
}


# Default TTLs for each memory category (in hours).
# Working memory expires quickly; others persist much longer.
DEFAULT_TTL_HOURS: Dict[MemoryCategory, Optional[int]] = {
    MemoryCategory.EPISODIC: None,       # Permanent
    MemoryCategory.SEMANTIC: None,       # Permanent
    MemoryCategory.PROCEDURAL: None,     # Permanent
    MemoryCategory.WORKING: 4,           # Expires after 4 hours
    MemoryCategory.META: None,           # Permanent
}


# ── Memory Entry ─────────────────────────────────────────────────────────


@dataclass
class MemoryEntry:
    """A single memory entry for agent recall.

    Maps to the agent_memory table columns from migration 002.
    """

    id: Optional[str] = None
    agent_id: str = ""
    memory_type: str = ""
    key: str = ""
    value: Dict[str, Any] = field(default_factory=dict)
    text: str = ""
    embedding: Optional[List[float]] = None
    metadata: Optional[Dict[str, Any]] = None
    importance: float = 0.5
    access_count: int = 0
    last_accessed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    @property
    def is_expired(self) -> bool:
        """Check if this memory has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at


@dataclass
class RecallResult:
    """Result from a semantic recall query."""

    entry: MemoryEntry
    similarity: float = 0.0
    """Cosine similarity score (0.0 to 1.0)."""


# ── Agent Memory Manager ─────────────────────────────────────────────────


class AgentMemoryManager:
    """High-level memory interface for a single ISO agent.

    Provides cognitive-style memory operations:
        - remember()          — store any memory type
        - recall()            — semantic search across memories
        - store_episode()     — record an audit execution
        - learn_fact()        — store a semantic fact
        - learn_procedure()   — store a successful strategy
        - set_working()       — set a working memory value (auto-expires)
        - get_working()       — retrieve a working memory value
        - reflect()           — store a meta-cognitive note
        - get_context()       — get all relevant context for a new task
        - prune_expired()     — clean up expired working memories

    This class does NOT own a database session; it delegates to an
    injected storage backend (typically MemoryStore from tron.memory.store
    or a direct async DB session).
    """

    def __init__(
        self,
        agent_id: str,
        embeddings_fn: Optional[Any] = None,
        storage_backend: Optional[Any] = None,
        working_ttl_hours: int = 4,
    ) -> None:
        """Initialize the AgentMemoryManager.

        Args:
            agent_id: Unique identifier for this agent instance.
            embeddings_fn: Async callable(text) -> List[float] for embeddings.
                          If None, semantic recall falls back to keyword/recency.
            storage_backend: Backend implementing store/recall/delete.
                            If None, uses in-memory dict (for testing).
            working_ttl_hours: TTL for working memory entries (default: 4h).
        """
        self.agent_id = agent_id
        self._embeddings_fn = embeddings_fn
        self._storage = storage_backend
        self._working_ttl_hours = working_ttl_hours

        # In-memory fallback store (used when no DB backend is provided)
        self._local_store: Dict[str, MemoryEntry] = {}
        self._local_counter: int = 0

        logger.info(
            "AgentMemoryManager initialized: agent=%s embeddings=%s backend=%s",
            agent_id,
            "enabled" if embeddings_fn else "disabled",
            type(storage_backend).__name__ if storage_backend else "in-memory",
        )

    # ── Core Operations ───────────────────────────────────────────────

    async def remember(
        self,
        category: MemoryCategory,
        key: str,
        text: str,
        value: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        importance: float = 0.5,
        ttl_hours: Optional[int] = None,
    ) -> MemoryEntry:
        """Store a memory of any category.

        Args:
            category: One of the 5 MemoryCategory types.
            key: Short identifier for this memory (e.g., "audit-run-abc123").
            text: Natural language description for semantic search.
            value: Structured data payload (JSONB in DB).
            metadata: Optional metadata dict.
            importance: Importance score 0.0-1.0 (default 0.5).
            ttl_hours: Override TTL (None = use category default).

        Returns:
            The stored MemoryEntry.
        """
        # Resolve TTL
        effective_ttl = ttl_hours if ttl_hours is not None else DEFAULT_TTL_HOURS.get(category)
        expires_at = None
        if effective_ttl is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=effective_ttl)

        # Generate embedding
        embedding = None
        if self._embeddings_fn and text:
            try:
                embedding = await self._embeddings_fn(text)
            except Exception as exc:
                logger.warning(
                    "Failed to generate embedding for agent=%s key=%s: %s",
                    self.agent_id, key, exc,
                )

        # Clamp importance
        importance = max(0.0, min(1.0, importance))

        entry = MemoryEntry(
            agent_id=self.agent_id,
            memory_type=category.value,
            key=key,
            value=value or {},
            text=text,
            embedding=embedding,
            metadata=metadata,
            importance=importance,
            access_count=0,
            last_accessed_at=None,
            expires_at=expires_at,
            created_at=datetime.now(timezone.utc),
        )

        # Persist
        if self._storage:
            entry = await self._storage.store(entry)
        else:
            self._local_counter += 1
            entry.id = f"mem-{self._local_counter}"
            self._local_store[entry.id] = entry

        logger.debug(
            "Stored memory: agent=%s type=%s key=%s importance=%.2f",
            self.agent_id, category.value, key, importance,
        )

        return entry

    async def recall(
        self,
        query: str,
        category: Optional[MemoryCategory] = None,
        limit: int = 10,
        min_similarity: float = 0.7,
    ) -> List[RecallResult]:
        """Recall memories via semantic similarity.

        Args:
            query: Natural language query.
            category: Filter to a specific memory category (optional).
            limit: Maximum results.
            min_similarity: Minimum cosine similarity threshold.

        Returns:
            List of RecallResult sorted by similarity (highest first).
        """
        if not query or not query.strip():
            return []

        if self._storage:
            return await self._storage.recall(
                agent_id=self.agent_id,
                query=query,
                memory_type=category.value if category else None,
                limit=limit,
                min_similarity=min_similarity,
            )

        # In-memory fallback: return all matching entries sorted by importance
        results = []
        for entry in self._local_store.values():
            if entry.is_expired:
                continue
            if entry.agent_id != self.agent_id:
                continue
            if category and entry.memory_type != category.value:
                continue

            # Simple keyword matching for in-memory fallback
            query_lower = query.lower()
            text_lower = entry.text.lower()
            similarity = 0.0

            # Count word overlap as a rough similarity proxy
            query_words = set(query_lower.split())
            text_words = set(text_lower.split())
            if query_words and text_words:
                overlap = len(query_words & text_words)
                similarity = overlap / max(len(query_words), 1)

            if similarity >= min_similarity or not self._embeddings_fn:
                entry.access_count += 1
                entry.last_accessed_at = datetime.now(timezone.utc)
                results.append(RecallResult(entry=entry, similarity=similarity))

        results.sort(key=lambda r: (r.similarity, r.entry.importance), reverse=True)
        return results[:limit]

    # ── Convenience Methods ───────────────────────────────────────────

    async def store_episode(
        self,
        key: str,
        description: str,
        audit_data: Dict[str, Any],
        importance: float = 0.5,
    ) -> MemoryEntry:
        """Record an audit execution episode.

        Args:
            key: Episode identifier (e.g., "audit-{run_id}").
            description: Human-readable summary of what happened.
            audit_data: Structured audit results (findings count, agents used, etc.).
            importance: How important this episode was (0.0-1.0).

        Returns:
            The stored MemoryEntry.
        """
        return await self.remember(
            category=MemoryCategory.EPISODIC,
            key=key,
            text=description,
            value=audit_data,
            importance=importance,
        )

    async def learn_fact(
        self,
        key: str,
        fact: str,
        evidence: Optional[Dict[str, Any]] = None,
        importance: float = 0.6,
    ) -> MemoryEntry:
        """Store a learned semantic fact.

        Args:
            key: Fact identifier (e.g., "vuln-pattern-sqli-django").
            fact: Natural language description of the fact.
            evidence: Supporting evidence data.
            importance: Default 0.6 (facts are generally useful).

        Returns:
            The stored MemoryEntry.
        """
        return await self.remember(
            category=MemoryCategory.SEMANTIC,
            key=key,
            text=fact,
            value=evidence or {},
            importance=importance,
        )

    async def learn_procedure(
        self,
        key: str,
        procedure: str,
        steps: Optional[List[str]] = None,
        conditions: Optional[Dict[str, Any]] = None,
        importance: float = 0.7,
    ) -> MemoryEntry:
        """Store a procedural strategy that worked.

        Args:
            key: Procedure identifier (e.g., "strategy-django-auth-scan").
            procedure: Description of the strategy.
            steps: Optional ordered list of steps.
            conditions: When this procedure should be applied.
            importance: Default 0.7 (procedures are high-value).

        Returns:
            The stored MemoryEntry.
        """
        value: Dict[str, Any] = {}
        if steps:
            value["steps"] = steps
        if conditions:
            value["conditions"] = conditions

        return await self.remember(
            category=MemoryCategory.PROCEDURAL,
            key=key,
            text=procedure,
            value=value,
            importance=importance,
        )

    async def set_working(
        self,
        key: str,
        text: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> MemoryEntry:
        """Set a working memory value (auto-expires).

        Working memory is the agent's short-term scratchpad for the
        current execution. It auto-expires after working_ttl_hours.

        Args:
            key: Working memory key (e.g., "current-file-graph").
            text: Description of what's being tracked.
            data: Structured data.

        Returns:
            The stored MemoryEntry.
        """
        return await self.remember(
            category=MemoryCategory.WORKING,
            key=key,
            text=text,
            value=data or {},
            importance=0.3,  # Working memory is low-importance for long-term
            ttl_hours=self._working_ttl_hours,
        )

    async def get_working(self, key: str) -> Optional[MemoryEntry]:
        """Retrieve a specific working memory value by key.

        Args:
            key: The working memory key to look up.

        Returns:
            The MemoryEntry if found and not expired, else None.
        """
        if self._storage:
            return await self._storage.get_by_key(
                agent_id=self.agent_id,
                key=key,
                memory_type=MemoryCategory.WORKING.value,
            )

        # In-memory fallback
        for entry in self._local_store.values():
            if (
                entry.agent_id == self.agent_id
                and entry.key == key
                and entry.memory_type == MemoryCategory.WORKING.value
                and not entry.is_expired
            ):
                entry.access_count += 1
                entry.last_accessed_at = datetime.now(timezone.utc)
                return entry

        return None

    async def reflect(
        self,
        key: str,
        reflection: str,
        metrics: Optional[Dict[str, Any]] = None,
        importance: float = 0.6,
    ) -> MemoryEntry:
        """Store a meta-cognitive reflection.

        Args:
            key: Reflection identifier (e.g., "accuracy-xss-react").
            reflection: What the agent learned about its own performance.
            metrics: Optional quantitative metrics (FP rate, accuracy, etc.).
            importance: Default 0.6.

        Returns:
            The stored MemoryEntry.
        """
        return await self.remember(
            category=MemoryCategory.META,
            key=key,
            text=reflection,
            value=metrics or {},
            importance=importance,
        )

    # ── Context Assembly ──────────────────────────────────────────────

    async def get_context(
        self,
        task_description: str,
        categories: Optional[List[MemoryCategory]] = None,
        limit: int = 20,
        min_importance: float = 0.3,
    ) -> List[MemoryEntry]:
        """Assemble relevant context for a new task.

        Retrieves the most relevant memories across multiple categories,
        filtering by importance and optionally by semantic similarity.

        Args:
            task_description: What the agent is about to do.
            categories: Which memory categories to search (default: all non-working).
            limit: Maximum total memories to return.
            min_importance: Minimum importance threshold.

        Returns:
            List of relevant MemoryEntry objects.
        """
        if categories is None:
            # Default: all categories except working (which is ephemeral)
            categories = [
                MemoryCategory.EPISODIC,
                MemoryCategory.SEMANTIC,
                MemoryCategory.PROCEDURAL,
                MemoryCategory.META,
            ]

        all_results: List[RecallResult] = []

        for cat in categories:
            results = await self.recall(
                query=task_description,
                category=cat,
                limit=limit,
                min_similarity=0.0,  # Don't filter by similarity here
            )
            all_results.extend(results)

        # Filter by importance and sort by combined score
        filtered = [
            r for r in all_results
            if r.entry.importance >= min_importance
        ]

        # Sort by importance * (1 + similarity) for relevance ranking
        filtered.sort(
            key=lambda r: r.entry.importance * (1.0 + r.similarity),
            reverse=True,
        )

        entries = [r.entry for r in filtered[:limit]]

        logger.info(
            "Context assembled for agent=%s: %d memories from %d categories",
            self.agent_id, len(entries), len(categories),
        )

        return entries

    # ── Maintenance ───────────────────────────────────────────────────

    async def prune_expired(self) -> int:
        """Remove expired memories (primarily working memory).

        Returns:
            Number of memories removed.
        """
        if self._storage:
            return await self._storage.cleanup_expired(agent_id=self.agent_id)

        # In-memory fallback
        expired_ids = [
            mid for mid, entry in self._local_store.items()
            if entry.agent_id == self.agent_id and entry.is_expired
        ]
        for mid in expired_ids:
            del self._local_store[mid]

        if expired_ids:
            logger.info(
                "Pruned %d expired memories for agent=%s",
                len(expired_ids), self.agent_id,
            )

        return len(expired_ids)

    async def decay_importance(
        self,
        older_than_days: int = 30,
        decay_factor: float = 0.9,
    ) -> int:
        """Decay importance of old memories.

        Memories older than `older_than_days` have their importance
        multiplied by `decay_factor`. This prevents memory bloat and
        keeps recent knowledge prioritized.

        Args:
            older_than_days: Only decay memories older than this.
            decay_factor: Multiply importance by this (0.0-1.0).

        Returns:
            Number of memories decayed.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        decayed = 0

        if self._storage:
            return await self._storage.decay_importance(
                agent_id=self.agent_id,
                cutoff=cutoff,
                factor=decay_factor,
            )

        # In-memory fallback
        for entry in self._local_store.values():
            if (
                entry.agent_id == self.agent_id
                and entry.created_at
                and entry.created_at < cutoff
                and not entry.is_expired
            ):
                entry.importance *= decay_factor
                decayed += 1

        if decayed:
            logger.info(
                "Decayed importance for %d memories (agent=%s, older_than=%dd)",
                decayed, self.agent_id, older_than_days,
            )

        return decayed

    # ── Statistics ────────────────────────────────────────────────────

    async def stats(self) -> Dict[str, Any]:
        """Get memory statistics for this agent.

        Returns:
            Dict with counts by category, total, avg importance, etc.
        """
        if self._storage:
            return await self._storage.stats(agent_id=self.agent_id)

        # In-memory fallback
        counts: Dict[str, int] = {}
        total_importance = 0.0
        total_access = 0
        active_count = 0

        for entry in self._local_store.values():
            if entry.agent_id != self.agent_id:
                continue
            if entry.is_expired:
                continue

            active_count += 1
            counts[entry.memory_type] = counts.get(entry.memory_type, 0) + 1
            total_importance += entry.importance
            total_access += entry.access_count

        return {
            "agent_id": self.agent_id,
            "total_memories": active_count,
            "by_category": counts,
            "avg_importance": total_importance / max(active_count, 1),
            "total_access_count": total_access,
        }

    def __repr__(self) -> str:
        backend = type(self._storage).__name__ if self._storage else "in-memory"
        return (
            f"<AgentMemoryManager agent={self.agent_id} "
            f"backend={backend} "
            f"embeddings={'on' if self._embeddings_fn else 'off'}>"
        )
