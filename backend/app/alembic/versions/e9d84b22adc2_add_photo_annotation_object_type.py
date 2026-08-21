"""add photo annotation object type

Revision ID: e9d84b22adc2
Revises: d3c273151f68
Create Date: 2026-08-21 13:41:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9d84b22adc2"
down_revision: str | None = "d3c273151f68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("annotation", sa.Column("object_type", sa.String(length=16), nullable=True))
    op.alter_column("annotation", "sound_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("annotation", "individual_num", existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint(
        "ck_annotation_object_type",
        "annotation",
        "object_type IS NULL OR object_type IN ('organism', 'other')",
    )
    op.create_index("ix_annotation_object_type", "annotation", ["object_type"])
    op.execute(
        """
        UPDATE annotation AS annotation
        SET object_type = 'other',
            sound_id = NULL,
            taxon_id = NULL,
            uncertain = NULL,
            individual_num = NULL,
            animal_sound_type = NULL,
            sound_distance_m = NULL,
            distance_not_estimable = NULL,
            confidence = NULL
        FROM media
        WHERE annotation.media_id = media.media_id
          AND media.media_type = 'photo'
        """
    )


def downgrade() -> None:
    op.execute("UPDATE annotation SET individual_num = 1 WHERE individual_num IS NULL")
    op.drop_index("ix_annotation_object_type", table_name="annotation")
    op.drop_constraint("ck_annotation_object_type", "annotation", type_="check")
    op.alter_column("annotation", "individual_num", existing_type=sa.Integer(), nullable=False)
    op.alter_column("annotation", "sound_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("annotation", "object_type")
