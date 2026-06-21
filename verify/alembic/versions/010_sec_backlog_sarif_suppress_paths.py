"""SEC backlog: project path globs, finding suppressions, SARIF path metadata, follow-up / evidence source.

Revision ID: 010
Revises: 009
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("audit_exclude_globs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("audit_test_path_globs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("findings", sa.Column("path_role", sa.String(32), nullable=True))
    op.add_column(
        "findings",
        sa.Column("follow_up_recommended", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("findings", sa.Column("evidence_source", sa.String(32), nullable=True))
    op.alter_column("findings", "follow_up_recommended", server_default=None)

    op.create_table(
        "finding_suppressions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "fingerprint", name="uq_finding_suppressions_project_fingerprint"),
    )
    op.create_index("idx_finding_suppressions_project_id", "finding_suppressions", ["project_id"])


def downgrade() -> None:
    op.drop_index("idx_finding_suppressions_project_id", table_name="finding_suppressions")
    op.drop_table("finding_suppressions")
    op.drop_column("findings", "evidence_source")
    op.drop_column("findings", "follow_up_recommended")
    op.drop_column("findings", "path_role")
    op.drop_column("projects", "audit_test_path_globs_json")
    op.drop_column("projects", "audit_exclude_globs_json")
