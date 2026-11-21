"""add media storage_collection_id

Revision ID: d93e66109de6
Revises: f194a8d6c2e0
Create Date: 2026-11-21 13:50:17.101305

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'd93e66109de6'
down_revision = 'f194a8d6c2e0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("media", sa.Column("storage_collection_id", sa.Integer(), nullable=True))
    op.create_index("idx_media_storage_collection_id", "media", ["storage_collection_id"])
    # Backfill existing physical media records with their earliest linked collection bucket.
    op.execute(
        """
        UPDATE media AS m
        SET storage_collection_id = sub.collection_id
        FROM (
            SELECT DISTINCT ON (media_id) media_id, collection_id
            FROM media_collection
            ORDER BY media_id, added_date ASC, collection_id ASC
        ) AS sub
        WHERE m.media_id = sub.media_id
          AND m.storage_collection_id IS NULL
          AND m.is_metadata = FALSE
        """
    )


def downgrade():
    op.drop_index("idx_media_storage_collection_id", table_name="media")
    op.drop_column("media", "storage_collection_id")
