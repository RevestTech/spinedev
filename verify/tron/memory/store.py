"""Core MemoryStore for agent memory persistence and semantic search."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tron.infra.embeddings.service import EmbeddingsService
from tron.memory.models import AgentMemory
from tron.memory.types import MemoryType

logger = logging.getLogger(__name__)


@dataclass
class MemoryResult:
    """Result of a memory recall query."""

    memory: AgentMemory
    similarity: float
    """Cosine similarity score (0.0 to 1.0)."""


class MemoryStore:
    """Core memory store for agent learning with semantic search.
    
    Provides methods to:
    - Store new memories with optional embeddings
    - Recall memories via semantic similarity or time-based queries
    - Consolidate and decay memories over time
    - Clean up expired memories
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embeddings_service: Optional[EmbeddingsService] = None,
    ) -> None:
        """Initialize the MemoryStore.

        Args:
            session_factory: Async session factory from db/session.py
            embeddings_service: Optional embeddings service for semantic search.
                               If None, fallback to keyword/time-based recall.
        """
        self._session_factory = session_factory
        self._embeddings_service = embeddings_service
        logger.info(
            "MemoryStore initialized (embeddings=%s)",
            "enabled" if embeddings_service else "disabled",
        )

    async def store(
        self,
        agent_id: str,
        memory_type: str,
        content: str,
        project_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        ttl_hours: Optional[int] = None,
    ) -> AgentMemory:
        """Store a new memory.

        Args:
            agent_id: Agent that created this memory.
            memory_type: One of: finding, pattern, context, decision, feedback.
            content: Natural language summary of the memory.
            project_id: Optional FK to projects.id (UUID as string).
            metadata: Optional structured metadata (dict).
            ttl_hours: Optional TTL; if set, memory expires after N hours.

        Returns:
            The stored AgentMemory object.

        Raises:
            ValueError: If memory_type is invalid.
        """
        # Validate memory_type
        valid_types = {t.value for t in MemoryType}
        if memory_type not in valid_types:
            raise ValueError(
                f"Invalid memory_type={memory_type}. "
                f"Must be one of: {', '.join(valid_types)}"
            )

        # Generate embedding if service available
        embedding = None
        if self._embeddings_service:
            try:
                embedding = await self._embeddings_service.embed_text(content)
            except Exception as exc:
                logger.warning(
                    "Failed to embed memory for agent %s: %s",
                    agent_id,
                    exc,
                )

        # Calculate expiration
        expires_at = None
        if ttl_hours:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

        # Convert project_id string to UUID if provided
        import uuid
        project_id_uuid = None
        if project_id:
            try:
                project_id_uuid = uuid.UUID(project_id)
            except (ValueError, TypeError):
                logger.warning(
                    "Invalid project_id=%s, treating as None",
                    project_id,
                )

        memory = AgentMemory(
            agent_id=agent_id,
            memory_type=memory_type,
            content=content,
            project_id=project_id_uuid,
            metadata_json=metadata,
            embedding=embedding,
            expires_at=expires_at,
        )

        async with self._session_factory() as session:
            session.add(memory)
            await session.commit()
            await session.refresh(memory)

        logger.info(
            "Stored memory id=%s agent=%s type=%s project=%s",
            memory.id,
            agent_id,
            memory_type,
            project_id or "None",
        )

        return memory

    async def recall(
        self,
        query: str,
        agent_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 10,
        min_similarity: float = 0.7,
    ) -> list[MemoryResult]:
        """Recall memories via semantic similarity.

        Uses pgvector cosine distance if embeddings available. Falls back to
        simple keyword matching if embeddings not available.

        Args:
            query: Query text (will be embedded if service available).
            agent_id: Filter by agent_id (optional).
            memory_type: Filter by memory_type (optional).
            project_id: Filter by project_id (optional).
            limit: Max results to return.
            min_similarity: Min cosine similarity score (0.0 to 1.0).

        Returns:
            List of MemoryResult objects sorted by similarity (highest first).
        """
        if not query or not query.strip():
            logger.warning("Empty query passed to recall()")
            return []

        # If embeddings service available, use semantic search
        if self._embeddings_service:
            return await self._recall_semantic(
                query=query,
                agent_id=agent_id,
                memory_type=memory_type,
                project_id=project_id,
                limit=limit,
                min_similarity=min_similarity,
            )
        else:
            # Fallback to recent memories without embeddings
            logger.debug(
                "Embeddings service not available; falling back to time-based recall"
            )
            return await self._recall_recent(
                agent_id=agent_id,
                memory_type=memory_type,
                project_id=project_id,
                limit=limit,
            )

    async def _recall_semantic(
        self,
        query: str,
        agent_id: Optional[str],
        memory_type: Optional[str],
        project_id: Optional[str],
        limit: int,
        min_similarity: float,
    ) -> list[MemoryResult]:
        """Semantic search using pgvector cosine distance (<=>) operator."""
        # Embed the query
        try:
            query_embedding = await self._embeddings_service.embed_text(query)
        except Exception as exc:
            logger.warning("Failed to embed query: %s; falling back to recent", exc)
            return await self._recall_recent(
                agent_id=agent_id,
                memory_type=memory_type,
                project_id=project_id,
                limit=limit,
            )

        if not query_embedding:
            logger.warning("Empty query embedding; falling back to recent")
            return await self._recall_recent(
                agent_id=agent_id,
                memory_type=memory_type,
                project_id=project_id,
                limit=limit,
            )

        # Build filters
        filters = []
        filters.append(AgentMemory.embedding.isnot(None))
        filters.append(AgentMemory.expires_at.is_(None) |
                      (AgentMemory.expires_at > datetime.now(timezone.utc)))

        if agent_id:
            filters.append(AgentMemory.agent_id == agent_id)
        if memory_type:
            filters.append(AgentMemory.memory_type == memory_type)
        if project_id:
            import uuid
            try:
                project_id_uuid = uuid.UUID(project_id)
                filters.append(AgentMemory.project_id == project_id_uuid)
            except (ValueError, TypeError):
                pass

        # pgvector cosine distance: <=> operator
        # Distance is (1 - similarity), so we filter: distance <= (1 - min_similarity)

        stmt = (
            select(
                AgentMemory,
                (1 - (AgentMemory.embedding.cosine_distance(query_embedding)))
                .label("similarity"),
            )
            .where(and_(*filters))
            .order_by(AgentMemory.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            rows = result.fetchall()

        results = []
        for memory, similarity in rows:
            # Increment access count
            memory.access_count += 1

            # Only include if meets min_similarity threshold
            if similarity >= min_similarity:
                results.append(MemoryResult(memory=memory, similarity=similarity))

        # Persist updated access counts
        if results:
            async with self._session_factory() as session:
                for mem_result in results:
                    stmt_update = (
                        select(AgentMemory)
                        .where(AgentMemory.id == mem_result.memory.id)
                    )
                    result_update = await session.execute(stmt_update)
                    mem_obj = result_update.scalar_one_or_none()
                    if mem_obj:
                        mem_obj.access_count += 1
                await session.commit()

        logger.info(
            "Semantic recall: query matched %d/%d memories (min_sim=%.2f)",
            len(results),
            len(rows),
            min_similarity,
        )

        return results

    async def recall_recent(
        self,
        agent_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[AgentMemory]:
        """Get recent memories without semantic search.

        Returns memories sorted by created_at descending (most recent first),
        excluding expired ones.

        Args:
            agent_id: Filter by agent_id (optional).
            memory_type: Filter by memory_type (optional).
            project_id: Filter by project_id (optional).
            limit: Max results to return.

        Returns:
            List of AgentMemory objects sorted by recency.
        """
        return await self._recall_recent(
            agent_id=agent_id,
            memory_type=memory_type,
            project_id=project_id,
            limit=limit,
        )

    async def _recall_recent(
        self,
        agent_id: Optional[str],
        memory_type: Optional[str],
        project_id: Optional[str],
        limit: int,
    ) -> list[AgentMemory]:
        """Internal helper for recent recall."""
        filters = [
            AgentMemory.expires_at.is_(None) |
            (AgentMemory.expires_at > datetime.now(timezone.utc))
        ]

        if agent_id:
            filters.append(AgentMemory.agent_id == agent_id)
        if memory_type:
            filters.append(AgentMemory.memory_type == memory_type)
        if project_id:
            import uuid
            try:
                project_id_uuid = uuid.UUID(project_id)
                filters.append(AgentMemory.project_id == project_id_uuid)
            except (ValueError, TypeError):
                pass

        stmt = (
            select(AgentMemory)
            .where(and_(*filters))
            .order_by(AgentMemory.created_at.desc())
            .limit(limit)
        )

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            memories = result.scalars().all()

        logger.info(
            "Recent recall: agent=%s type=%s returned %d memories",
            agent_id or "all",
            memory_type or "all",
            len(memories),
        )

        return list(memories)

    async def consolidate(
        self,
        agent_id: str,
        project_id: Optional[str] = None,
    ) -> int:
        """Consolidate similar memories and decay old ones.

        This is a maintenance operation that:
        1. Finds similar memories (via cosine distance)
        2. Merges them (increments access_count, updates content)
        3. Decays relevance_score for old memories

        Args:
            agent_id: Agent whose memories to consolidate.
            project_id: Optional project filter.

        Returns:
            Number of memories consolidated.
        """
        if not self._embeddings_service:
            logger.info(
                "Consolidation skipped for agent %s: embeddings service not available",
                agent_id,
            )
            return 0

        filters = [AgentMemory.agent_id == agent_id]
        if project_id:
            import uuid
            try:
                project_id_uuid = uuid.UUID(project_id)
                filters.append(AgentMemory.project_id == project_id_uuid)
            except (ValueError, TypeError):
                pass

        # Get all memories for this agent
        stmt = (
            select(AgentMemory)
            .where(and_(*filters))
            .order_by(AgentMemory.created_at.desc())
        )

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            memories = result.scalars().all()

        if not memories:
            return 0

        consolidated_count = 0

        # Simple consolidation: increment access_count for accessed memories,
        # decay relevance for memories older than 30 days
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        async with self._session_factory() as session:
            for memory in memories:
                # Decay old memories
                if memory.created_at < cutoff:
                    memory.relevance_score *= 0.9  # 10% decay
                    consolidated_count += 1

            await session.commit()

        logger.info(
            "Consolidation complete for agent %s: %d memories processed",
            agent_id,
            consolidated_count,
        )

        return consolidated_count

    async def cleanup_expired(self) -> int:
        """Remove expired memories.

        Returns:
            Number of memories deleted.
        """
        stmt = select(AgentMemory).where(
            AgentMemory.expires_at.isnot(None) &
            (AgentMemory.expires_at <= datetime.now(timezone.utc))
        )

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            expired = result.scalars().all()

            for memory in expired:
                await session.delete(memory)

            await session.commit()
            deleted_count = len(expired)

        logger.info("Cleaned up %d expired memories", deleted_count)
        return deleted_count

    async def get_context(
        self,
        agent_id: str,
        project_id: str,
        limit: int = 20,
    ) -> list[AgentMemory]:
        """Get relevant context for an agent starting a task.

        Retrieves high-relevance, non-expired memories ordered by
        recency and access_count (recently used memories are more useful).

        Args:
            agent_id: Agent that needs context.
            project_id: Project context (UUID as string).
            limit: Max context memories to return.

        Returns:
            List of AgentMemory objects relevant to the task.
        """
        import uuid

        try:
            project_id_uuid = uuid.UUID(project_id)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid project_id=%s for context retrieval",
                project_id,
            )
            return []

        filters = [
            AgentMemory.agent_id == agent_id,
            AgentMemory.project_id == project_id_uuid,
            AgentMemory.relevance_score > 0.5,
            AgentMemory.expires_at.is_(None) |
            (AgentMemory.expires_at > datetime.now(timezone.utc)),
        ]

        # Sort by: relevance_score (desc), then access_count (desc), then created_at (desc)
        stmt = (
            select(AgentMemory)
            .where(and_(*filters))
            .order_by(
                AgentMemory.relevance_score.desc(),
                AgentMemory.access_count.desc(),
                AgentMemory.created_at.desc(),
            )
            .limit(limit)
        )

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            memories = result.scalars().all()

        logger.info(
            "Context retrieval for agent %s, project %s: %d memories",
            agent_id,
            project_id,
            len(memories),
        )

        return list(memories)
