"""Initial schema — all 12 tables, extensions, triggers, and indexes.

Revision ID: 001
Revises: None
Create Date: 2026-04-11

Matches DATABASE_SCHEMA.md v5.1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Extensions ──
    op.execute("CREATE EXTENSION IF NOT EXISTS ltree")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ── Trigger function for updated_at ──
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ── 1. Projects ──
    op.create_table(
        "projects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("repo_url", sa.Text),
        sa.Column("default_branch", sa.String(100), server_default="main"),
        sa.Column("company_standards_version", sa.String(50)),
        sa.Column("project_standards_version", sa.String(50)),
        sa.Column("status", sa.String(50), server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_by", UUID(as_uuid=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_projects_status", "projects", ["status"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_projects_created_at", "projects", [sa.text("created_at DESC")])
    op.create_index("idx_projects_updated_at", "projects", [sa.text("updated_at DESC")], postgresql_where=sa.text("deleted_at IS NULL"))
    op.execute("""
        CREATE TRIGGER update_projects_updated_at
        BEFORE UPDATE ON projects
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    # ── 2. Audit Runs ──
    op.create_table(
        "audit_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_id", sa.String(255), nullable=False),
        sa.Column("workflow_run_id", sa.String(255), nullable=False),
        sa.Column("commit_hash", sa.String(64)),
        sa.Column("branch", sa.String(100)),
        sa.Column("trigger_type", sa.String(50)),
        sa.Column("triggered_by", UUID(as_uuid=True)),
        sa.Column("status", sa.String(50), nullable=False, server_default="running"),
        sa.Column("progress", sa.Integer, server_default="0"),
        sa.Column("quality_score", sa.Numeric(5, 2)),
        sa.Column("findings_total", sa.Integer, server_default="0"),
        sa.Column("findings_critical", sa.Integer, server_default="0"),
        sa.Column("findings_high", sa.Integer, server_default="0"),
        sa.Column("findings_medium", sa.Integer, server_default="0"),
        sa.Column("findings_low", sa.Integer, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text),
        sa.Column("error_stack", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_audit_runs_progress"),
    )
    op.create_index("idx_audit_runs_project_id", "audit_runs", ["project_id", sa.text("created_at DESC")])
    op.create_index("idx_audit_runs_status", "audit_runs", ["status", sa.text("created_at DESC")])
    op.create_index("idx_audit_runs_workflow_id", "audit_runs", ["workflow_id"])
    op.execute("""
        CREATE TRIGGER update_audit_runs_updated_at
        BEFORE UPDATE ON audit_runs
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    # ── 3. Code Files (Graph Nodes) — created before findings for FK ──
    op.create_table(
        "code_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("language", sa.String(50)),
        sa.Column("file_type", sa.String(50)),
        sa.Column("lines_of_code", sa.Integer),
        sa.Column("complexity_score", sa.Integer),
        sa.Column("directory_path", sa.Text),  # ltree — cast in queries
        sa.Column("dependency_count", sa.Integer, server_default="0"),
        sa.Column("dependent_count", sa.Integer, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("project_id", "file_path", name="uq_code_files_project_path"),
    )
    op.create_index("idx_code_files_project", "code_files", ["project_id"])
    op.create_index("idx_code_files_path", "code_files", ["file_path"])
    op.create_index("idx_code_files_hash", "code_files", ["file_hash"])
    # ltree-specific indexes created via raw SQL
    op.execute("CREATE INDEX idx_code_files_directory_gist ON code_files USING GIST (CAST(directory_path AS ltree))")
    op.execute("CREATE INDEX idx_code_files_path_trgm ON code_files USING GIN (file_path gin_trgm_ops)")

    # ── 4. Findings ──
    op.create_table(
        "findings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("audit_run_id", UUID(as_uuid=True), sa.ForeignKey("audit_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("rule_id", sa.String(255), nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("file_id", UUID(as_uuid=True), sa.ForeignKey("code_files.id", ondelete="SET NULL")),
        sa.Column("line_start", sa.Integer),
        sa.Column("line_end", sa.Integer),
        sa.Column("column_start", sa.Integer),
        sa.Column("column_end", sa.Integer),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("category", sa.String(100)),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("suggested_fix", sa.Text),
        sa.Column("status", sa.String(50), server_default="open"),
        sa.Column("resolution", sa.String(100)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", UUID(as_uuid=True)),
        sa.Column("code_snippet", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_findings_audit_run_id", "findings", ["audit_run_id"])
    op.create_index("idx_findings_project_severity", "findings", ["project_id", "severity", sa.text("created_at DESC")])
    op.create_index("idx_findings_fingerprint", "findings", ["fingerprint", "project_id"])
    op.create_index("idx_findings_status", "findings", ["status", "project_id", sa.text("created_at DESC")])
    op.create_index("idx_findings_file_id", "findings", ["file_id"])
    op.create_index("idx_findings_open", "findings", ["project_id", "severity", sa.text("created_at DESC")], postgresql_where=sa.text("status = 'open'"))
    op.execute("""
        CREATE INDEX idx_findings_search ON findings
        USING GIN (to_tsvector('english', title || ' ' || description));
    """)
    op.execute("""
        CREATE TRIGGER update_findings_updated_at
        BEFORE UPDATE ON findings
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    # ── 5. LLM Usage (Append-Only Ledger) ──
    op.create_table(
        "llm_usage",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_id", sa.String(255)),
        sa.Column("workflow_run_id", sa.String(255)),
        sa.Column("operation_mode", sa.String(20)),
        sa.Column("operation_detail", sa.String(255)),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer, nullable=False),
        sa.Column("completion_tokens", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("cached", sa.Boolean, server_default="false"),
        sa.Column("cache_key", sa.String(64)),
        sa.Column("request_id", sa.String(100)),
        sa.Column("temperature", sa.Numeric(3, 2)),
        sa.Column("max_tokens", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("prompt_tokens >= 0", name="ck_llm_usage_prompt_tokens"),
        sa.CheckConstraint("completion_tokens >= 0", name="ck_llm_usage_completion_tokens"),
        sa.CheckConstraint("cost_usd >= 0", name="ck_llm_usage_cost"),
        sa.CheckConstraint("duration_ms >= 0", name="ck_llm_usage_duration"),
    )
    op.create_index("idx_llm_usage_project_date", "llm_usage", ["project_id", sa.text("created_at DESC")])
    op.create_index("idx_llm_usage_workflow", "llm_usage", ["workflow_id", sa.text("created_at DESC")])
    op.create_index("idx_llm_usage_model", "llm_usage", ["model", sa.text("created_at DESC")])

    # ── 6. Cost Aggregation (Hourly) ──
    op.create_table(
        "llm_cost_hourly",
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("hour_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("provider", sa.String(50), primary_key=True),
        sa.Column("model", sa.String(100), primary_key=True),
        sa.Column("total_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("cached_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_duration_ms", sa.Integer),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_llm_cost_hourly_project_time", "llm_cost_hourly", ["project_id", sa.text("hour_start DESC")])

    # ── 7. Cost Aggregation (Daily) ──
    op.create_table(
        "llm_cost_daily",
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("day", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("total_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("cached_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("plan_cost_usd", sa.Numeric(10, 2), server_default="0"),
        sa.Column("build_cost_usd", sa.Numeric(10, 2), server_default="0"),
        sa.Column("audit_cost_usd", sa.Numeric(10, 2), server_default="0"),
        sa.Column("fix_cost_usd", sa.Numeric(10, 2), server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_llm_cost_daily_project_day", "llm_cost_daily", ["project_id", sa.text("day DESC")])

    # ── 8. Project Cost Limits ──
    op.create_table(
        "project_cost_limits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("daily_limit_usd", sa.Numeric(10, 2), nullable=False, server_default="10.00"),
        sa.Column("monthly_limit_usd", sa.Numeric(10, 2), nullable=False, server_default="100.00"),
        sa.Column("action_on_limit", sa.String(20), server_default="warn"),
        sa.Column("warning_threshold", sa.Numeric(3, 2), server_default="0.80"),
        sa.Column("throttle_threshold", sa.Numeric(3, 2), server_default="0.90"),
        sa.Column("notify_email", ARRAY(sa.Text)),
        sa.Column("notify_webhook", sa.Text),
        sa.Column("enabled", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    # ── 9. Cost Events ──
    op.create_table(
        "cost_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("current_spend_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("limit_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("threshold_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("action_taken", sa.String(50)),
        sa.Column("notification_sent", sa.Boolean, server_default="false"),
        sa.Column("period", sa.String(20)),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_cost_events_project_date", "cost_events", ["project_id", sa.text("created_at DESC")])

    # ── 10. File Dependencies (Graph Edges) ──
    op.create_table(
        "file_dependencies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_file_id", UUID(as_uuid=True), sa.ForeignKey("code_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_file_id", UUID(as_uuid=True), sa.ForeignKey("code_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dependency_type", sa.String(50), nullable=False),
        sa.Column("import_statement", sa.Text),
        sa.Column("is_external", sa.Boolean, server_default="false"),
        sa.Column("is_circular", sa.Boolean, server_default="false"),
        sa.Column("usage_count", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("source_file_id", "target_file_id", "dependency_type", name="uq_file_deps_source_target_type"),
        sa.CheckConstraint("source_file_id != target_file_id", name="ck_file_deps_no_self_loop"),
    )
    op.create_index("idx_file_deps_source", "file_dependencies", ["source_file_id"])
    op.create_index("idx_file_deps_target", "file_dependencies", ["target_file_id"])

    # ── 11. Finding Relationships (Graph Edges) ──
    op.create_table(
        "finding_relationships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("finding_id", UUID(as_uuid=True), sa.ForeignKey("findings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("related_finding_id", UUID(as_uuid=True), sa.ForeignKey("findings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship_type", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2)),
        sa.Column("detected_by", sa.String(50)),
        sa.Column("reason", sa.Text),
        sa.Column("metadata", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("finding_id", "related_finding_id", "relationship_type", name="uq_finding_rels"),
        sa.CheckConstraint("finding_id != related_finding_id", name="ck_finding_rels_no_self"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_finding_rels_confidence"),
    )
    op.create_index("idx_finding_rels_finding", "finding_relationships", ["finding_id"])
    op.create_index("idx_finding_rels_related", "finding_relationships", ["related_finding_id"])

    # ── 12. Standards (Hierarchy) ──
    op.create_table(
        "standards",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("hierarchy_path", sa.Text, unique=True, nullable=False),
        sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("standards.id", ondelete="CASCADE")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("company_id", UUID(as_uuid=True)),
        sa.Column("rules", JSONB, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("version", sa.String(50)),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_standards_parent", "standards", ["parent_id"])
    op.create_index("idx_standards_project", "standards", ["project_id"])
    op.execute("CREATE INDEX idx_standards_path_gist ON standards USING GIST (CAST(hierarchy_path AS ltree))")
    op.execute("CREATE INDEX idx_standards_rules ON standards USING GIN (rules)")


def downgrade() -> None:
    op.drop_table("standards")
    op.drop_table("finding_relationships")
    op.drop_table("file_dependencies")
    op.drop_table("cost_events")
    op.drop_table("project_cost_limits")
    op.drop_table("llm_cost_daily")
    op.drop_table("llm_cost_hourly")
    op.drop_table("llm_usage")
    op.drop_table("findings")
    op.drop_table("code_files")
    op.drop_table("audit_runs")
    op.drop_table("projects")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column()")
