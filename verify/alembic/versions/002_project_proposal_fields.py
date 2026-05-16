"""Add proposal fields: quality gates, plan artifact, build result on projects.

Revision ID: 002
Revises: 001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("quality_gates_json", JSONB, nullable=True))
    op.add_column("projects", sa.Column("plan_artifact_json", JSONB, nullable=True))
    op.add_column("projects", sa.Column("last_build_result_json", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "last_build_result_json")
    op.drop_column("projects", "plan_artifact_json")
    op.drop_column("projects", "quality_gates_json")
