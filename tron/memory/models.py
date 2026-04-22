"""SQLAlchemy ORM model for agent memories."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tron.infra.db.base import Base


def _utcnow() -> datetime:
    """Return current UTC time."""
    return datetime.now(timezone.utc)


def _gen_uuid() -> uuid.UUID:
    """Generate a new UUID."""
    return uuid.uuid4()


class AgentMemory(Base):
    """Agent memory storage with semantic search via pgvector.
    
    Stores different types of agent learning (findings, patterns, context,
    decisions, feedback) with embeddings for semantic similarity search.
    """

    __tablename__ = "agent_memories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_gen_uuid
    )

    agent_id: Mapped[str] = mapped_column(
        String(100), nullable=False,
        doc="Agent that created this memory"
    )

    memory_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        doc="One of: finding, pattern, context, decision, feedback"
    )

    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        doc="FK to projects; nullable for cross-project memories"
    )

    content: Mapped[str] = mapped_column(
        Text, nullable=False,
        doc="Natural language summary of the memory"
    )

    metadata_json: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        doc="Arbitrary structured metadata (e.g., severity, confidence, tags)"
    )

    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(1536), nullable=True,
        doc="1536-dim vector (OpenAI text-embedding-3-large) for semantic search"
    )

    relevance_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0,
        doc="Relevance score; decays over time or via consolidation"
    )

    access_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        doc="Number of times this memory has been recalled"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        doc="When the memory was created"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow,
        doc="Last update time"
    )

    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="TTL-based expiration; NULL means no expiration"
    )

    __table_args__ = (
        Index("idx_agent_memories_agent_id", "agent_id"),
        Index("idx_agent_memories_project_id", "project_id"),
        Index("idx_agent_memories_memory_type", "memory_type"),
        Index("idx_agent_memories_created_at", "created_at"),
        Index("idx_agent_memories_expires_at", "expires_at",
              postgresql_where=text("expires_at IS NOT NULL")),
    )

    def __repr__(self) -> str:
        return (
            f"<AgentMemory id={self.id} agent_id={self.agent_id} "
            f"type={self.memory_type} access_count={self.access_count}>"
        )
