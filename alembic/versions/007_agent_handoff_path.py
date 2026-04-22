"""Optional absolute path on the worker host where Tron writes agent handoff files after each audit.

Revision ID: 007
Revises: 006
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("agent_handoff_path", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "agent_handoff_path")
