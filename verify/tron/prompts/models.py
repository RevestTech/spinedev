"""
SQLAlchemy models for the Prompt Management system.

Tables:
  1. prompt_templates — Slug-identified templates with versioning metadata
  2. prompt_versions — Immutable versioned snapshots of each template
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tron.infra.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _gen_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── 1. Prompt Templates ──


class PromptTemplate(Base):
    """Template registry with version tracking.

    Each template is identified by a unique slug (template_id) and tracks
    when new versions are created. The actual prompt content lives in
    PromptVersion records.
    """

    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_gen_uuid
    )
    template_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    agent_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Relationships
    versions: Mapped[list[PromptVersion]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_prompt_templates_agent_type", "agent_type"),
    )


# ── 2. Prompt Versions ──


class PromptVersion(Base):
    """Immutable version snapshot of a prompt template.

    Each update to a template creates a new PromptVersion record with an
    incremented version number. Old versions are retained for drift
    detection and audit trails.
    """

    __tablename__ = "prompt_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_gen_uuid
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_templates.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=[])
    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(100))

    # Relationships
    template: Mapped[PromptTemplate] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint(
            "template_id", "version",
            name="uq_prompt_versions_template_version"
        ),
        Index("idx_prompt_versions_template_version", "template_id", "version"),
    )
