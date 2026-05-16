"""
SQLAlchemy ORM models matching DATABASE_SCHEMA.md (v5.1).

Tables:
  1. projects
  2. audit_runs (partitioned by created_at)
  3. findings (partitioned by created_at)
  4. llm_usage (append-only ledger)
  5. llm_cost_hourly (aggregation)
  6. llm_cost_daily (aggregation)
  7. project_cost_limits
  8. cost_events
  9. code_files (graph nodes)
  10. file_dependencies (graph edges)
  11. finding_relationships (graph edges)
  12. standards (ltree hierarchy)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tron.infra.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _gen_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── 1. Projects ──

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_gen_uuid
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    repo_url: Mapped[Optional[str]] = mapped_column(Text)
    # Absolute path on the machine running the audit worker (must be mounted into
    # tron-worker if using Docker) where TRON_POST_SCAN.md + agent breadcrumbs are written.
    agent_handoff_path: Mapped[Optional[str]] = mapped_column(Text)
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    company_standards_version: Mapped[Optional[str]] = mapped_column(String(50))
    project_standards_version: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Proposal: standards + PLAN/BUILD artifacts (see MASTER_PROPOSAL_TODO.md)
    company_quality_gates_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    quality_gates_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    plan_artifact_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    # Latest interactive PLAN wizard answers (draft or last run).
    plan_questionnaire_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    last_build_result_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    # EVOLVE mode — last workflow artifact (Temporal EvolveWorkflow).
    evolve_artifact_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    # Optional built-in compliance reference pack IDs (see tron/standards/control_packs.py).
    compliance_control_pack_ids: Mapped[Optional[list]] = mapped_column(JSONB)

    # Relationships
    audit_runs: Mapped[list["AuditRun"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    cost_limits: Mapped[Optional["ProjectCostLimit"]] = relationship(back_populates="project", uselist=False)

    __table_args__ = (
        Index("idx_projects_status", "status", postgresql_where=text("deleted_at IS NULL")),
        Index("idx_projects_created_at", "created_at"),
        Index("idx_projects_updated_at", "updated_at", postgresql_where=text("deleted_at IS NULL")),
    )


# ── 2. Audit Runs ──

class AuditRun(Base):
    __tablename__ = "audit_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_gen_uuid
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    workflow_run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    commit_hash: Mapped[Optional[str]] = mapped_column(String(64))
    branch: Mapped[Optional[str]] = mapped_column(String(100))
    trigger_type: Mapped[Optional[str]] = mapped_column(String(50))
    triggered_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="running")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    findings_total: Mapped[int] = mapped_column(Integer, default=0)
    findings_critical: Mapped[int] = mapped_column(Integer, default=0)
    findings_high: Mapped[int] = mapped_column(Integer, default=0)
    findings_medium: Mapped[int] = mapped_column(Integer, default=0)
    findings_low: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_stack: Mapped[Optional[str]] = mapped_column(Text)
    threat_intel_alerts_json: Mapped[Optional[list]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="audit_runs")
    findings: Mapped[list["Finding"]] = relationship(back_populates="audit_run", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_audit_runs_progress"),
        Index("idx_audit_runs_project_id", "project_id", "created_at"),
        Index("idx_audit_runs_status", "status", "created_at"),
        Index("idx_audit_runs_workflow_id", "workflow_id"),
    )


# ── 3. Findings ──

class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_gen_uuid
    )
    audit_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_runs.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("code_files.id", ondelete="SET NULL")
    )
    line_start: Mapped[Optional[int]] = mapped_column(Integer)
    line_end: Mapped[Optional[int]] = mapped_column(Integer)
    column_start: Mapped[Optional[int]] = mapped_column(Integer)
    column_end: Mapped[Optional[int]] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_fix: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="open")
    resolution: Mapped[Optional[str]] = mapped_column(String(100))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    code_snippet: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Relationships
    audit_run: Mapped["AuditRun"] = relationship(back_populates="findings")

    __table_args__ = (
        Index("idx_findings_audit_run_id", "audit_run_id"),
        Index("idx_findings_project_severity", "project_id", "severity", "created_at"),
        Index("idx_findings_fingerprint", "fingerprint", "project_id"),
        Index("idx_findings_status", "status", "project_id", "created_at"),
        Index("idx_findings_file_id", "file_id"),
    )


# ── 4. LLM Usage (Append-Only Ledger) ──

class LLMUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_gen_uuid
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[Optional[str]] = mapped_column(String(255))
    workflow_run_id: Mapped[Optional[str]] = mapped_column(String(255))
    operation_mode: Mapped[Optional[str]] = mapped_column(String(20))
    operation_detail: Mapped[Optional[str]] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    cache_key: Mapped[Optional[str]] = mapped_column(String(64))
    request_id: Mapped[Optional[str]] = mapped_column(String(100))
    temperature: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2))
    max_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint("prompt_tokens >= 0", name="ck_llm_usage_prompt_tokens"),
        CheckConstraint("completion_tokens >= 0", name="ck_llm_usage_completion_tokens"),
        CheckConstraint("cost_usd >= 0", name="ck_llm_usage_cost"),
        CheckConstraint("duration_ms >= 0", name="ck_llm_usage_duration"),
        Index("idx_llm_usage_project_date", "project_id", "created_at"),
        Index("idx_llm_usage_workflow", "workflow_id", "created_at"),
        Index("idx_llm_usage_model", "model", "created_at"),
    )


# ── 5. Cost Aggregation (Hourly) ──

class LLMCostHourly(Base):
    __tablename__ = "llm_cost_hourly"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    hour_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(50), primary_key=True)
    model: Mapped[str] = mapped_column(String(100), primary_key=True)
    total_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    cached_calls: Mapped[int] = mapped_column(Integer, default=0)
    avg_duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("idx_llm_cost_hourly_project_time", "project_id", "hour_start"),
    )


# ── 6. Cost Aggregation (Daily) ──

class LLMCostDaily(Base):
    __tablename__ = "llm_cost_daily"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    day: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    total_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    cached_calls: Mapped[int] = mapped_column(Integer, default=0)
    plan_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    build_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    audit_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    fix_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("idx_llm_cost_daily_project_day", "project_id", "day"),
    )


# ── 7. Project Cost Limits ──

class ProjectCostLimit(Base):
    __tablename__ = "project_cost_limits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_gen_uuid
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        unique=True, nullable=False,
    )
    daily_limit_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=10.00)
    monthly_limit_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=100.00)
    action_on_limit: Mapped[str] = mapped_column(String(20), default="warn")
    warning_threshold: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=0.80)
    throttle_threshold: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=0.90)
    notify_email: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    notify_webhook: Mapped[Optional[str]] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="cost_limits")


# ── 8. Cost Events ──

class CostEvent(Base):
    __tablename__ = "cost_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_gen_uuid
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    current_spend_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    limit_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    threshold_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    action_taken: Mapped[Optional[str]] = mapped_column(String(50))
    notification_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    period: Mapped[Optional[str]] = mapped_column(String(20))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("idx_cost_events_project_date", "project_id", "created_at"),
    )


# ── 9. Code Files (Graph Nodes) ──

class CodeFile(Base):
    __tablename__ = "code_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_gen_uuid
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(50))
    file_type: Mapped[Optional[str]] = mapped_column(String(50))
    lines_of_code: Mapped[Optional[int]] = mapped_column(Integer)
    complexity_score: Mapped[Optional[int]] = mapped_column(Integer)
    # directory_path is ltree — stored as Text, cast in queries
    directory_path: Mapped[Optional[str]] = mapped_column(Text)
    dependency_count: Mapped[int] = mapped_column(Integer, default=0)
    dependent_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("project_id", "file_path", name="uq_code_files_project_path"),
        Index("idx_code_files_project", "project_id"),
        Index("idx_code_files_path", "file_path"),
        Index("idx_code_files_hash", "file_hash"),
    )


# ── 10. File Dependencies (Graph Edges) ──

class FileDependency(Base):
    __tablename__ = "file_dependencies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_gen_uuid
    )
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("code_files.id", ondelete="CASCADE"), nullable=False
    )
    target_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("code_files.id", ondelete="CASCADE"), nullable=False
    )
    dependency_type: Mapped[str] = mapped_column(String(50), nullable=False)
    import_statement: Mapped[Optional[str]] = mapped_column(Text)
    is_external: Mapped[bool] = mapped_column(Boolean, default=False)
    is_circular: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("source_file_id", "target_file_id", "dependency_type",
                         name="uq_file_deps_source_target_type"),
        CheckConstraint("source_file_id != target_file_id", name="ck_file_deps_no_self_loop"),
        Index("idx_file_deps_source", "source_file_id"),
        Index("idx_file_deps_target", "target_file_id"),
    )


# ── 11. Finding Relationships (Graph Edges) ──

class FindingRelationship(Base):
    __tablename__ = "finding_relationships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_gen_uuid
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), nullable=False
    )
    related_finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2))
    detected_by: Mapped[Optional[str]] = mapped_column(String(50))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("finding_id", "related_finding_id", "relationship_type",
                         name="uq_finding_rels"),
        CheckConstraint("finding_id != related_finding_id", name="ck_finding_rels_no_self"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_finding_rels_confidence"),
        Index("idx_finding_rels_finding", "finding_id"),
        Index("idx_finding_rels_related", "related_finding_id"),
    )


# ── 12. Standards (Hierarchy) ──

class Standard(Base):
    __tablename__ = "standards"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_gen_uuid
    )
    # hierarchy_path is ltree — stored as Text, cast in queries
    hierarchy_path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("standards.id", ondelete="CASCADE")
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    rules: Mapped[dict] = mapped_column(JSONB, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    version: Mapped[Optional[str]] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        Index("idx_standards_parent", "parent_id"),
        Index("idx_standards_project", "project_id"),
    )


# ── 13. API Keys (scoped keys; master key remains in vault) ──


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_gen_uuid
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("idx_api_keys_active", "active"),)
