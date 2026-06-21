"""Findings: confidence, tool confirmation, Layer 3 execution, confirming tools (evidence for API/UI/export).

Revision ID: 009
Revises: 008
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "findings",
        sa.Column("confidence", sa.Numeric(6, 5), nullable=True),
    )
    op.add_column(
        "findings",
        sa.Column(
            "deterministic_tool_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "findings",
        sa.Column("layer3_execution", sa.String(32), nullable=True),
    )
    op.add_column(
        "findings",
        sa.Column("confirming_tools_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.alter_column("findings", "deterministic_tool_confirmed", server_default=None)


def downgrade() -> None:
    op.drop_column("findings", "confirming_tools_json")
    op.drop_column("findings", "layer3_execution")
    op.drop_column("findings", "deterministic_tool_confirmed")
    op.drop_column("findings", "confidence")
