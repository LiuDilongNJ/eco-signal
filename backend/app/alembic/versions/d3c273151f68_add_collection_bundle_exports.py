"""add collection bundle exports

Revision ID: d3c273151f68
Revises: d1e2f3a4b5c6
Create Date: 2026-07-23 10:05:04.258750
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "d3c273151f68"
down_revision: str | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collection_bundle_export",
        sa.Column("export_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("queue_id", sa.Integer(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("filename", sqlmodel.sql.sqltypes.AutoString(length=250), nullable=True),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column("size_b", sa.BigInteger(), nullable=True),
        sa.Column("counts", sa.JSON(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("creation_date", sa.DateTime(), nullable=False),
        sa.Column("completion_date", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collection.collection_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.project_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["queue_id"], ["queue.queue_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("export_id"),
    )
    op.create_index(
        "ix_collection_bundle_export_collection_id",
        "collection_bundle_export",
        ["collection_id"],
    )
    op.create_index(
        "ix_collection_bundle_export_creation_date",
        "collection_bundle_export",
        ["creation_date"],
    )
    op.create_index(
        "ix_collection_bundle_export_expires_at",
        "collection_bundle_export",
        ["expires_at"],
    )
    op.create_index(
        "ix_collection_bundle_export_project_id",
        "collection_bundle_export",
        ["project_id"],
    )
    op.create_index(
        "ix_collection_bundle_export_queue_id",
        "collection_bundle_export",
        ["queue_id"],
        unique=True,
    )
    op.create_index(
        "ix_collection_bundle_export_status",
        "collection_bundle_export",
        ["status"],
    )
    op.create_index(
        "ix_collection_bundle_export_user_id",
        "collection_bundle_export",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_collection_bundle_export_user_id",
        table_name="collection_bundle_export",
    )
    op.drop_index(
        "ix_collection_bundle_export_status",
        table_name="collection_bundle_export",
    )
    op.drop_index(
        "ix_collection_bundle_export_queue_id",
        table_name="collection_bundle_export",
    )
    op.drop_index(
        "ix_collection_bundle_export_project_id",
        table_name="collection_bundle_export",
    )
    op.drop_index(
        "ix_collection_bundle_export_expires_at",
        table_name="collection_bundle_export",
    )
    op.drop_index(
        "ix_collection_bundle_export_creation_date",
        table_name="collection_bundle_export",
    )
    op.drop_index(
        "ix_collection_bundle_export_collection_id",
        table_name="collection_bundle_export",
    )
    op.drop_table("collection_bundle_export")
