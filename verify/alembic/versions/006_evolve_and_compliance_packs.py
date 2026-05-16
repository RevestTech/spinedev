"""Evolve mode artifact + optional compliance reference pack IDs on projects.

Revision ID: 006
Revises: 005
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("evolve_artifact_json", JSONB, nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("compliance_control_pack_ids", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "compliance_control_pack_ids")
    op.drop_column("projects", "evolve_artifact_json")
