"""cascade annotation task deletion

Revision ID: 81e7c29a461b
Revises: d93e66109de6
Create Date: 2026-11-27 06:19:39.094047

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '81e7c29a461b'
down_revision = 'd93e66109de6'
branch_labels = None
depends_on = None


def _replace_foreign_key(ondelete: str) -> None:
    name = "task_annotation_id_fkey"
    op.drop_constraint(name, "task", type_="foreignkey")
    op.create_foreign_key(
        name,
        "task",
        "annotation",
        ["annotation_id"],
        ["annotation_id"],
        ondelete=ondelete,
        onupdate="CASCADE",
    )


def upgrade() -> None:
    _replace_foreign_key("CASCADE")


def downgrade() -> None:
    _replace_foreign_key("SET NULL")
