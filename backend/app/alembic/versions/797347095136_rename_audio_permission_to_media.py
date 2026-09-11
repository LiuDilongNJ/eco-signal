"""rename_audio_permission_to_media

Revision ID: 797347095136
Revises: c0a90f1e2d34
Create Date: 2026-09-11 01:59:25.713324

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '797347095136'
down_revision = 'c0a90f1e2d34'
branch_labels = None
depends_on = None



_VIEW_SQL_UPGRADE = """
CREATE VIEW user_effective_permissions AS
WITH direct_grants AS (
    SELECT up.user_id, up.project_id, up.collection_id, p.resource_type, p.action
    FROM user_permission up
    JOIN permission p ON p.permission_id = up.permission_id
    LEFT JOIN user_scope_role usr
      ON usr.user_id = up.user_id
     AND usr.project_id = up.project_id
     AND usr.collection_id IS NOT DISTINCT FROM up.collection_id
    LEFT JOIN role r ON r.role_id = usr.role_id
    WHERE usr.id IS NULL OR r.code = 'custom'

    UNION

    SELECT usr.user_id, usr.project_id, usr.collection_id, p.resource_type, p.action
    FROM user_scope_role usr
    JOIN role r ON r.role_id = usr.role_id
    JOIN role_permission rp
      ON rp.role_id = usr.role_id
     AND rp.scope_type = CASE WHEN usr.collection_id IS NULL THEN 'project' ELSE 'collection' END
    JOIN permission p ON p.permission_id = rp.permission_id
    WHERE r.kind = 'access' AND r.code <> 'custom'
),
expanded_grants AS (
    SELECT user_id, project_id, collection_id, resource_type, action
    FROM direct_grants

    UNION

    SELECT user_id, project_id, collection_id, resource_type, 'read'::varchar
    FROM direct_grants
    WHERE action = 'write'

    UNION

    SELECT user_id, project_id, collection_id, resource_type, 'read_own'::varchar
    FROM direct_grants
    WHERE resource_type IN ('annotation', 'review')
      AND action IN ('read', 'write', 'read_own', 'write_own')

    UNION

    SELECT user_id, project_id, collection_id, resource_type, 'write_own'::varchar
    FROM direct_grants
    WHERE resource_type IN ('annotation', 'review')
      AND action = 'write'
)
SELECT user_id, project_id, NULL::integer AS collection_id,
       'project'::varchar AS scope_type, resource_type, action
FROM expanded_grants
WHERE collection_id IS NULL
  AND resource_type = 'project'
  AND action IN ('read', 'write')

UNION

SELECT user_id, project_id, collection_id,
       'project_collection'::varchar AS scope_type, resource_type, action
FROM expanded_grants
WHERE collection_id IS NOT NULL

UNION

SELECT eg.user_id, eg.project_id, pc.collection_id,
       'project_collection'::varchar AS scope_type, eg.resource_type, eg.action
FROM expanded_grants eg
JOIN project_collection pc ON pc.project_id = eg.project_id
WHERE eg.collection_id IS NULL
  AND eg.resource_type IN ('media', 'site', 'annotation', 'review')

UNION

SELECT dg.user_id, dg.project_id, dg.collection_id,
       'project_collection'::varchar AS scope_type, sub.resource_type, sub.action
FROM direct_grants dg
CROSS JOIN (
    VALUES
        ('collection'::varchar, 'read'::varchar),
        ('collection'::varchar, 'write'::varchar),
        ('media'::varchar, 'read'::varchar),
        ('media'::varchar, 'write'::varchar),
        ('site'::varchar, 'read'::varchar),
        ('site'::varchar, 'write'::varchar),
        ('annotation'::varchar, 'read'::varchar),
        ('annotation'::varchar, 'write'::varchar),
        ('annotation'::varchar, 'read_own'::varchar),
        ('annotation'::varchar, 'write_own'::varchar),
        ('review'::varchar, 'read'::varchar),
        ('review'::varchar, 'write'::varchar),
        ('review'::varchar, 'read_own'::varchar),
        ('review'::varchar, 'write_own'::varchar)
) sub(resource_type, action)
WHERE dg.collection_id IS NOT NULL
  AND dg.resource_type = 'collection'
  AND dg.action = 'write'

UNION

SELECT dg.user_id, dg.project_id, pc.collection_id,
       'project_collection'::varchar AS scope_type, sub.resource_type, sub.action
FROM direct_grants dg
JOIN project_collection pc ON pc.project_id = dg.project_id
CROSS JOIN (
    VALUES
        ('collection'::varchar, 'read'::varchar),
        ('collection'::varchar, 'write'::varchar),
        ('media'::varchar, 'read'::varchar),
        ('media'::varchar, 'write'::varchar),
        ('site'::varchar, 'read'::varchar),
        ('site'::varchar, 'write'::varchar),
        ('annotation'::varchar, 'read'::varchar),
        ('annotation'::varchar, 'write'::varchar),
        ('annotation'::varchar, 'read_own'::varchar),
        ('annotation'::varchar, 'write_own'::varchar),
        ('review'::varchar, 'read'::varchar),
        ('review'::varchar, 'write'::varchar),
        ('review'::varchar, 'read_own'::varchar),
        ('review'::varchar, 'write_own'::varchar)
) sub(resource_type, action)
WHERE dg.collection_id IS NULL
  AND dg.resource_type = 'project'
  AND dg.action = 'write'

UNION

SELECT DISTINCT user_id, project_id, NULL::integer,
       'project'::varchar, 'project'::varchar, 'read'::varchar
FROM direct_grants
WHERE collection_id IS NOT NULL;
"""


_VIEW_SQL_DOWNGRADE = """
CREATE VIEW user_effective_permissions AS
WITH direct_grants AS (
    SELECT up.user_id, up.project_id, up.collection_id, p.resource_type, p.action
    FROM user_permission up
    JOIN permission p ON p.permission_id = up.permission_id
    LEFT JOIN user_scope_role usr
      ON usr.user_id = up.user_id
     AND usr.project_id = up.project_id
     AND usr.collection_id IS NOT DISTINCT FROM up.collection_id
    LEFT JOIN role r ON r.role_id = usr.role_id
    WHERE usr.id IS NULL OR r.code = 'custom'

    UNION

    SELECT usr.user_id, usr.project_id, usr.collection_id, p.resource_type, p.action
    FROM user_scope_role usr
    JOIN role r ON r.role_id = usr.role_id
    JOIN role_permission rp
      ON rp.role_id = usr.role_id
     AND rp.scope_type = CASE WHEN usr.collection_id IS NULL THEN 'project' ELSE 'collection' END
    JOIN permission p ON p.permission_id = rp.permission_id
    WHERE r.kind = 'access' AND r.code <> 'custom'
),
expanded_grants AS (
    SELECT user_id, project_id, collection_id, resource_type, action
    FROM direct_grants

    UNION

    SELECT user_id, project_id, collection_id, resource_type, 'read'::varchar
    FROM direct_grants
    WHERE action = 'write'

    UNION

    SELECT user_id, project_id, collection_id, resource_type, 'read_own'::varchar
    FROM direct_grants
    WHERE resource_type IN ('annotation', 'review')
      AND action IN ('read', 'write', 'read_own', 'write_own')

    UNION

    SELECT user_id, project_id, collection_id, resource_type, 'write_own'::varchar
    FROM direct_grants
    WHERE resource_type IN ('annotation', 'review')
      AND action = 'write'
)
SELECT user_id, project_id, NULL::integer AS collection_id,
       'project'::varchar AS scope_type, resource_type, action
FROM expanded_grants
WHERE collection_id IS NULL
  AND resource_type = 'project'
  AND action IN ('read', 'write')

UNION

SELECT user_id, project_id, collection_id,
       'project_collection'::varchar AS scope_type, resource_type, action
FROM expanded_grants
WHERE collection_id IS NOT NULL

UNION

SELECT eg.user_id, eg.project_id, pc.collection_id,
       'project_collection'::varchar AS scope_type, eg.resource_type, eg.action
FROM expanded_grants eg
JOIN project_collection pc ON pc.project_id = eg.project_id
WHERE eg.collection_id IS NULL
  AND eg.resource_type IN ('audio', 'site', 'annotation', 'review')

UNION

SELECT dg.user_id, dg.project_id, dg.collection_id,
       'project_collection'::varchar AS scope_type, sub.resource_type, sub.action
FROM direct_grants dg
CROSS JOIN (
    VALUES
        ('collection'::varchar, 'read'::varchar),
        ('collection'::varchar, 'write'::varchar),
        ('audio'::varchar, 'read'::varchar),
        ('audio'::varchar, 'write'::varchar),
        ('site'::varchar, 'read'::varchar),
        ('site'::varchar, 'write'::varchar),
        ('annotation'::varchar, 'read'::varchar),
        ('annotation'::varchar, 'write'::varchar),
        ('annotation'::varchar, 'read_own'::varchar),
        ('annotation'::varchar, 'write_own'::varchar),
        ('review'::varchar, 'read'::varchar),
        ('review'::varchar, 'write'::varchar),
        ('review'::varchar, 'read_own'::varchar),
        ('review'::varchar, 'write_own'::varchar)
) sub(resource_type, action)
WHERE dg.collection_id IS NOT NULL
  AND dg.resource_type = 'collection'
  AND dg.action = 'write'

UNION

SELECT dg.user_id, dg.project_id, pc.collection_id,
       'project_collection'::varchar AS scope_type, sub.resource_type, sub.action
FROM direct_grants dg
JOIN project_collection pc ON pc.project_id = dg.project_id
CROSS JOIN (
    VALUES
        ('collection'::varchar, 'read'::varchar),
        ('collection'::varchar, 'write'::varchar),
        ('audio'::varchar, 'read'::varchar),
        ('audio'::varchar, 'write'::varchar),
        ('site'::varchar, 'read'::varchar),
        ('site'::varchar, 'write'::varchar),
        ('annotation'::varchar, 'read'::varchar),
        ('annotation'::varchar, 'write'::varchar),
        ('annotation'::varchar, 'read_own'::varchar),
        ('annotation'::varchar, 'write_own'::varchar),
        ('review'::varchar, 'read'::varchar),
        ('review'::varchar, 'write'::varchar),
        ('review'::varchar, 'read_own'::varchar),
        ('review'::varchar, 'write_own'::varchar)
) sub(resource_type, action)
WHERE dg.collection_id IS NULL
  AND dg.resource_type = 'project'
  AND dg.action = 'write'

UNION

SELECT DISTINCT user_id, project_id, NULL::integer,
       'project'::varchar, 'project'::varchar, 'read'::varchar
FROM direct_grants
WHERE collection_id IS NOT NULL;
"""


def upgrade():
    op.execute(
        """
        UPDATE permission
        SET resource_type = 'media', name = 'media:read'
        WHERE name = 'audio:read'
        """
    )
    op.execute(
        """
        UPDATE permission
        SET resource_type = 'media', name = 'media:write'
        WHERE name = 'audio:write'
        """
    )
    op.execute("DROP VIEW IF EXISTS user_accessible_collections")
    op.execute("DROP VIEW IF EXISTS user_effective_permissions")
    op.execute(_VIEW_SQL_UPGRADE)
    op.execute(
        """
        CREATE VIEW user_accessible_collections AS
        SELECT user_id, project_id, collection_id, resource_type, action
        FROM user_effective_permissions
        WHERE scope_type = 'project_collection'
        """
    )


def downgrade():
    op.execute(
        """
        UPDATE permission
        SET resource_type = 'audio', name = 'audio:read'
        WHERE name = 'media:read'
        """
    )
    op.execute(
        """
        UPDATE permission
        SET resource_type = 'audio', name = 'audio:write'
        WHERE name = 'media:write'
        """
    )
    op.execute("DROP VIEW IF EXISTS user_accessible_collections")
    op.execute("DROP VIEW IF EXISTS user_effective_permissions")
    op.execute(_VIEW_SQL_DOWNGRADE)
    op.execute(
        """
        CREATE VIEW user_accessible_collections AS
        SELECT user_id, project_id, collection_id, resource_type, action
        FROM user_effective_permissions
        WHERE scope_type = 'project_collection'
        """
    )

