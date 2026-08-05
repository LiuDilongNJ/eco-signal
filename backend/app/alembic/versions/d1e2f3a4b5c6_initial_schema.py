from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Execute app.sql to create schema and data.sql to insert seed data."""
    alembic_dir = Path(__file__).parent.parent
    connection = op.get_bind()

    schema_file = alembic_dir / "app.sql"
    if not schema_file.exists():
        raise FileNotFoundError(f"Schema SQL file not found: {schema_file}")

    schema_content = schema_file.read_text(encoding="utf-8")
    connection.exec_driver_sql(schema_content)

    data_file = alembic_dir / "data.sql"
    if not data_file.exists():
        raise FileNotFoundError(f"Data SQL file not found: {data_file}")

    data_content = data_file.read_text(encoding="utf-8")
    connection.exec_driver_sql(data_content)


def downgrade() -> None:
    """Drop schema objects created by the baseline SQL files."""
    op.execute("DROP VIEW IF EXISTS user_accessible_collections CASCADE")
    op.execute("DROP VIEW IF EXISTS user_effective_permissions CASCADE")

    op.execute("DROP TRIGGER IF EXISTS enforce_project_collection_public_constraint ON project_collection")
    op.execute("DROP TRIGGER IF EXISTS enforce_project_public_constraint ON project")
    op.execute("DROP TRIGGER IF EXISTS enforce_collection_public_constraint ON collection")

    op.execute("DROP FUNCTION IF EXISTS check_project_collection_public_constraint()")
    op.execute("DROP FUNCTION IF EXISTS check_project_public_constraint()")
    op.execute("DROP FUNCTION IF EXISTS check_collection_public_constraint()")

    tables = [
        "operation_log",
        "network_node",
        "setting",
        "news",
        "queue",
        "model",
        "index_log",
        "index_type",
        "task",
        "annotation_review",
        "annotation_review_status",
        "annotation",
        "label_media",
        "label",
        "preview",
        "media_collection",
        "file_upload",
        "media",
        "photo_setting",
        "audio_setting",
        "sound_classification",
        "taxon_sound_type",
        "taxon",
        "sensor",
        "camera_lens",
        "lens",
        "camera",
        "recorder_microphone",
        "microphone",
        "recorder",
        "license",
        "site_project",
        "site_collection",
        "site",
        "user_permission",
        "collection_taxon",
        "project_collection",
        "collection_contributor",
        "collection",
        "project_contributor",
        "project",
        "user_preference",
        '"user"',
        "permission",
        "role",
        "iucn_get",
    ]

    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
