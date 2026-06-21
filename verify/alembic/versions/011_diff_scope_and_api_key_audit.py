"""Pre-PR diff scope on audit_runs + API key audit log table + project webhooks.

Revision ID: 011
Revises: 010

What this adds:

  * ``audit_runs.diff_files_json`` — when set, the audit pipeline restricts
    its scan to exactly these paths. Used by ``POST /api/audits/diff`` for
    PR-time gates that should only re-scan changed files.
  * ``audit_runs.diff_base_ref`` / ``audit_runs.diff_head_ref`` — the
    refs the diff was computed from (informational; surfaced in the audit
    detail page).
  * ``api_key_audit_log`` — one row per scoped-API-key call with key id,
    HTTP method, route, status code, IP, user agent, timestamp.
    Required for any enterprise security review ("show me who hit X
    last week").
  * ``projects.audit_webhook_url`` — outbound POST target on audit
    completion. ``projects.audit_webhook_secret_id`` references a
    keyvault entry holding the HMAC signing secret. Customers wire
    Slack / Linear / Jira / PagerDuty without bespoke integrations.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── projects: outbound webhook config ─────────────────────────────
    op.add_column(
        "projects",
        sa.Column(
            "audit_webhook_url",
            sa.String(2048),
            nullable=True,
            comment=(
                "Outbound URL POSTed on audit completion/failure. Body is "
                "JSON; signed with HMAC-SHA256 in X-Tron-Signature when "
                "audit_webhook_secret_id resolves to a keyvault entry."
            ),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "audit_webhook_secret_id",
            sa.String(255),
            nullable=True,
            comment="Keyvault path to the HMAC signing secret (optional).",
        ),
    )

    # ── audit_runs: diff-scope columns ────────────────────────────────
    op.add_column(
        "audit_runs",
        sa.Column(
            "diff_files_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "When non-null, the audit pipeline restricts its scan to "
                "exactly these relative paths. Set by POST /api/audits/diff."
            ),
        ),
    )
    op.add_column(
        "audit_runs",
        sa.Column(
            "diff_base_ref",
            sa.String(255),
            nullable=True,
            comment="Base git ref of the diff (e.g. 'main'); informational.",
        ),
    )
    op.add_column(
        "audit_runs",
        sa.Column(
            "diff_head_ref",
            sa.String(255),
            nullable=True,
            comment="Head git ref of the diff (e.g. 'feature/x'); informational.",
        ),
    )

    # ── api_key_audit_log table ───────────────────────────────────────
    op.create_table(
        "api_key_audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "api_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_keys.id", ondelete="CASCADE"),
            nullable=True,
            comment=(
                "Null for master-key calls (master has no row in api_keys). "
                "Set for any scoped-key call."
            ),
        ),
        sa.Column("is_master", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_admin_session", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("status_code", sa.Integer, nullable=True),
        sa.Column("remote_addr", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "idx_api_key_audit_log_key_time",
        "api_key_audit_log",
        ["api_key_id", "created_at"],
    )
    op.create_index(
        "idx_api_key_audit_log_path_time",
        "api_key_audit_log",
        ["path", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_api_key_audit_log_path_time", table_name="api_key_audit_log")
    op.drop_index("idx_api_key_audit_log_key_time", table_name="api_key_audit_log")
    op.drop_table("api_key_audit_log")
    op.drop_column("audit_runs", "diff_head_ref")
    op.drop_column("audit_runs", "diff_base_ref")
    op.drop_column("audit_runs", "diff_files_json")
    op.drop_column("projects", "audit_webhook_secret_id")
    op.drop_column("projects", "audit_webhook_url")
