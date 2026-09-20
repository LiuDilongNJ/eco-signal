"""allow multiline media notes and annotation comments

Revision ID: c3f8a1b2d4e6
Revises: 0b1dd5fefe1c
Create Date: 2026-09-20 20:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f8a1b2d4e6"
down_revision: str | None = "0b1dd5fefe1c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "media",
        "note",
        existing_type=sa.String(length=250),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "annotation",
        "comments",
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "annotation",
        "comments",
        existing_type=sa.Text(),
        type_=sa.String(length=500),
        existing_nullable=True,
    )
    op.alter_column(
        "media",
        "note",
        existing_type=sa.Text(),
        type_=sa.String(length=250),
        existing_nullable=True,
    )
