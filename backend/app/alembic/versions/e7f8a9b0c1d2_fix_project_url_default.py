"""Fix project URL default and null values

Revision ID: e7f8a9b0c1d2
Revises: d3c273151f68
Create Date: 2026-08-06 16:50:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "d3c273151f68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE project SET url = '' WHERE url IS NULL")
    op.execute("ALTER TABLE project ALTER COLUMN url SET DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE project ALTER COLUMN url DROP DEFAULT")
