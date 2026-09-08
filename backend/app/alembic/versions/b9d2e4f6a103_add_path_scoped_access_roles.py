"""add path-scoped access roles and ownership permissions

Revision ID: b9d2e4f6a103
Revises: a7f1c4d9e2b0
Create Date: 2026-09-05 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b9d2e4f6a103"
down_revision: str | None = "a7f1c4d9e2b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_VIEW_SQL = """
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


def upgrade() -> None:
    op.add_column("role", sa.Column("code", sa.String(length=64), nullable=True))
    op.add_column("role", sa.Column("kind", sa.String(length=20), nullable=False, server_default="system"))
    op.add_column("role", sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"))
    op.execute(
        """
        UPDATE role
        SET code = CASE
            WHEN name = 'Administrator' THEN 'administrator'
            WHEN name = 'User' THEN 'user'
            ELSE 'system-' || role_id::text
        END
        WHERE code IS NULL
        """
    )
    op.create_unique_constraint("uq_role_code", "role", ["code"])
    op.create_index("ix_role_kind", "role", ["kind"])
    op.create_index("ix_role_code", "role", ["code"])

    op.execute(
        """
        DO $$
        DECLARE constraint_name text;
        BEGIN
            SELECT conname INTO constraint_name
            FROM pg_constraint
            WHERE conrelid = 'permission'::regclass
              AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%action%';
            IF constraint_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE permission DROP CONSTRAINT %I', constraint_name);
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        ALTER TABLE permission
        ADD CONSTRAINT ck_permission_action
        CHECK (action IN ('read', 'write', 'read_own', 'write_own'))
        """
    )

    op.execute(
        """
        INSERT INTO role (name, code, kind, display_order)
        VALUES
            ('Viewer', 'viewer', 'access', 10),
            ('Annotator', 'annotator', 'access', 20),
            ('Reviewer', 'reviewer', 'access', 30),
            ('Manager', 'manager', 'access', 40),
            ('Custom', 'custom', 'access', 50)
        ON CONFLICT (code) DO UPDATE
        SET name = EXCLUDED.name,
            kind = EXCLUDED.kind,
            display_order = EXCLUDED.display_order
        """
    )
    op.execute(
        """
        INSERT INTO permission (resource_type, action, name)
        VALUES
            ('annotation', 'read_own', 'annotation:read_own'),
            ('annotation', 'write_own', 'annotation:write_own'),
            ('review', 'read_own', 'review:read_own'),
            ('review', 'write_own', 'review:write_own')
        ON CONFLICT (name) DO NOTHING
        """
    )

    op.create_table(
        "role_permission",
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("permission_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("scope_type IN ('project', 'collection')", name="ck_role_permission_scope"),
        sa.ForeignKeyConstraint(["role_id"], ["role.role_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permission.permission_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("role_id", "scope_type", "permission_id"),
    )
    op.create_table(
        "user_scope_role",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=True),
        sa.Column("creation_date", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_id"], ["role.role_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["project.project_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["collection_id"], ["collection.collection_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["project_id", "collection_id"],
            ["project_collection.project_id", "project_collection.collection_id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_user_scope_role_user", "user_scope_role", ["user_id"])
    op.create_index("ix_user_scope_role_project", "user_scope_role", ["project_id"])
    op.create_index("ix_user_scope_role_collection", "user_scope_role", ["collection_id"])
    op.create_index(
        "uq_user_scope_role_project",
        "user_scope_role",
        ["user_id", "project_id"],
        unique=True,
        postgresql_where=sa.text("collection_id IS NULL"),
    )
    op.create_index(
        "uq_user_scope_role_collection",
        "user_scope_role",
        ["user_id", "project_id", "collection_id"],
        unique=True,
        postgresql_where=sa.text("collection_id IS NOT NULL"),
    )

    op.execute(
        """
        WITH templates(role_code, scope_type, permission_name) AS (
            VALUES
                ('viewer', 'project', 'project:read'),
                ('viewer', 'project', 'audio:read'),
                ('viewer', 'project', 'site:read'),
                ('viewer', 'project', 'annotation:read'),
                ('viewer', 'project', 'review:read'),
                ('viewer', 'collection', 'collection:read'),
                ('viewer', 'collection', 'audio:read'),
                ('viewer', 'collection', 'site:read'),
                ('viewer', 'collection', 'annotation:read'),
                ('viewer', 'collection', 'review:read'),
                ('annotator', 'project', 'project:read'),
                ('annotator', 'project', 'audio:read'),
                ('annotator', 'project', 'site:read'),
                ('annotator', 'project', 'annotation:write_own'),
                ('annotator', 'collection', 'collection:read'),
                ('annotator', 'collection', 'audio:read'),
                ('annotator', 'collection', 'site:read'),
                ('annotator', 'collection', 'annotation:write_own'),
                ('reviewer', 'project', 'project:read'),
                ('reviewer', 'project', 'audio:read'),
                ('reviewer', 'project', 'site:read'),
                ('reviewer', 'project', 'annotation:read'),
                ('reviewer', 'project', 'review:read'),
                ('reviewer', 'project', 'review:write_own'),
                ('reviewer', 'collection', 'collection:read'),
                ('reviewer', 'collection', 'audio:read'),
                ('reviewer', 'collection', 'site:read'),
                ('reviewer', 'collection', 'annotation:read'),
                ('reviewer', 'collection', 'review:read'),
                ('reviewer', 'collection', 'review:write_own'),
                ('manager', 'project', 'project:write'),
                ('manager', 'collection', 'collection:write')
        )
        INSERT INTO role_permission (role_id, scope_type, permission_id)
        SELECT r.role_id, t.scope_type, p.permission_id
        FROM templates t
        JOIN role r ON r.code = t.role_code
        JOIN permission p ON p.name = t.permission_name
        ON CONFLICT DO NOTHING
        """
    )

    op.execute(
        """
        WITH grouped AS (
            SELECT up.user_id, up.project_id, up.collection_id,
                   array_agg(p.name ORDER BY p.name) AS permissions
            FROM user_permission up
            JOIN permission p ON p.permission_id = up.permission_id
            GROUP BY up.user_id, up.project_id, up.collection_id
        ), matching_roles AS (
            SELECT g.user_id, g.project_id, g.collection_id,
                   CASE
                       WHEN g.collection_id IS NULL AND g.permissions = ARRAY['project:write']::varchar[] THEN 'manager'
                       WHEN g.collection_id IS NOT NULL AND g.permissions = ARRAY['collection:write']::varchar[] THEN 'manager'
                       WHEN g.collection_id IS NULL AND g.permissions = ARRAY['annotation:read','audio:read','project:read','review:read','site:read']::varchar[] THEN 'viewer'
                       WHEN g.collection_id IS NOT NULL AND g.permissions = ARRAY['annotation:read','audio:read','collection:read','review:read','site:read']::varchar[] THEN 'viewer'
                       WHEN g.collection_id IS NULL AND g.permissions = ARRAY['annotation:write_own','audio:read','project:read','site:read']::varchar[] THEN 'annotator'
                       WHEN g.collection_id IS NOT NULL AND g.permissions = ARRAY['annotation:write_own','audio:read','collection:read','site:read']::varchar[] THEN 'annotator'
                       WHEN g.collection_id IS NULL AND g.permissions = ARRAY['annotation:read','audio:read','project:read','review:read','review:write_own','site:read']::varchar[] THEN 'reviewer'
                       WHEN g.collection_id IS NOT NULL AND g.permissions = ARRAY['annotation:read','audio:read','collection:read','review:read','review:write_own','site:read']::varchar[] THEN 'reviewer'
                       ELSE 'custom'
                   END AS role_code
            FROM grouped g
        )
        INSERT INTO user_scope_role (user_id, role_id, project_id, collection_id)
        SELECT m.user_id, r.role_id, m.project_id, m.collection_id
        FROM matching_roles m
        JOIN role r ON r.code = m.role_code
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        DELETE FROM user_permission up
        USING user_scope_role usr
        JOIN role r ON r.role_id = usr.role_id
        WHERE r.code IN ('viewer', 'annotator', 'reviewer', 'manager')
          AND usr.user_id = up.user_id
          AND usr.project_id = up.project_id
          AND usr.collection_id IS NOT DISTINCT FROM up.collection_id
        """
    )

    op.execute("DROP VIEW IF EXISTS user_accessible_collections")
    op.execute("DROP VIEW IF EXISTS user_effective_permissions")
    op.execute(_VIEW_SQL)
    op.execute(
        """
        CREATE VIEW user_accessible_collections AS
        SELECT user_id, project_id, collection_id, resource_type, action
        FROM user_effective_permissions
        WHERE scope_type = 'project_collection'
        """
    )


def downgrade() -> None:
    raise RuntimeError("Cannot safely downgrade while ownership-scoped permissions may exist")
