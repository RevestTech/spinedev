"""Saved GitHub orgs (multi-org switcher).

Revision ID: 012
Revises: 011

Persists the user-curated list of GitHub organizations / accounts that
appear in the GitHub repo browser dropdown. Without this, users had to
re-type the org name every time they wanted to switch repos.

Notes
-----
* ``login`` is the path component used by the GitHub REST API
  (``/orgs/{login}/repos`` or ``/users/{login}/repos``). It's case-
  insensitive on GitHub but we normalise to lowercase before insert
  so the unique index actually enforces uniqueness.
* ``kind`` distinguishes orgs from user accounts so the UI can label
  them and the backend can pick the correct API path. We don't enforce
  it via FK — GitHub is the source of truth.
* No FK to ``api_keys`` or any auth table — this is shared
  infrastructure: every Tron operator uses the same vault PAT, so the
  saved list is a singleton config, not per-user.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "saved_github_orgs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "login",
            sa.String(100),
            nullable=False,
            comment=(
                "GitHub login (org or user). Stored lowercase. Used directly "
                "as the path segment in /orgs/{login}/repos or "
                "/users/{login}/repos."
            ),
        ),
        sa.Column(
            "display_name",
            sa.String(255),
            nullable=True,
            comment="Optional human-friendly label; falls back to login.",
        ),
        sa.Column(
            "kind",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'org'"),
            comment="'org' or 'user' — controls which GitHub API path is used.",
        ),
        sa.Column(
            "pinned",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
            comment="Pinned entries sort first in the UI dropdown.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "kind IN ('org', 'user')",
            name="ck_saved_github_orgs_kind",
        ),
    )
    # Case-insensitive uniqueness — login is stored lowercase, but the
    # functional index defends against any future code path that forgets.
    op.create_index(
        "idx_saved_github_orgs_login_lower",
        "saved_github_orgs",
        [sa.text("lower(login)")],
        unique=True,
    )
    op.create_index(
        "idx_saved_github_orgs_pinned_created",
        "saved_github_orgs",
        ["pinned", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_saved_github_orgs_pinned_created",
        table_name="saved_github_orgs",
    )
    op.drop_index(
        "idx_saved_github_orgs_login_lower",
        table_name="saved_github_orgs",
    )
    op.drop_table("saved_github_orgs")
