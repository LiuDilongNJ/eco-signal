"""add model version column

Revision ID: 0b1dd5fefe1c
Revises: 83925dc92de3
Create Date: 2026-09-12 15:35:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0b1dd5fefe1c"
down_revision: str | None = "83925dc92de3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model", sa.Column("version", sa.String(length=50), nullable=True))
    op.execute("UPDATE model SET version = '2.4' WHERE model_id = 1")
    op.execute("UPDATE model SET version = '1.3.0' WHERE model_id = 2")
    op.execute("UPDATE model SET version = '1.0.0' WHERE model_id = 3")


def downgrade() -> None:
    op.drop_column("model", "version")
