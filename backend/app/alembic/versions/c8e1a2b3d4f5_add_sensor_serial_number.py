"""add optional serial_number to sensor

Revision ID: c8e1a2b3d4f5
Revises: f4a6c8e9b012
Create Date: 2026-08-30 13:22:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8e1a2b3d4f5"
down_revision: str | None = "f4a6c8e9b012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sensor", sa.Column("serial_number", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("sensor", "serial_number")
