"""Add company_quality_gates_json for three-tier standards merge.

Revision ID: 003
Revises: 002
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("company_quality_gates_json", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "company_quality_gates_json")
