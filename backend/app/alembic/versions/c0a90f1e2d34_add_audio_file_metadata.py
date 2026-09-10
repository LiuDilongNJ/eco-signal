"""add audio file metadata

Revision ID: c0a90f1e2d34
Revises: b9d2e4f6a103
Create Date: 2026-09-10 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c0a90f1e2d34"
down_revision: str | None = "b9d2e4f6a103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("audio_setting", sa.Column("file_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("audio_setting", "file_metadata")
