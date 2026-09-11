"""align_annotator_role_permissions

Revision ID: ec69d2cf92ad
Revises: 797347095136
Create Date: 2026-09-11 04:53:35.236019

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'ec69d2cf92ad'
down_revision = '797347095136'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        WITH templates(role_code, scope_type, permission_name) AS (
            VALUES
                ('annotator', 'project', 'annotation:read'),
                ('annotator', 'project', 'review:read'),
                ('annotator', 'project', 'review:write_own'),
                ('annotator', 'collection', 'annotation:read'),
                ('annotator', 'collection', 'review:read'),
                ('annotator', 'collection', 'review:write_own')
        )
        INSERT INTO role_permission (role_id, scope_type, permission_id)
        SELECT r.role_id, t.scope_type, p.permission_id
        FROM templates t
        JOIN role r ON r.code = t.role_code
        JOIN permission p ON p.name = t.permission_name
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade():
    op.execute(
        """
        DELETE FROM role_permission
        WHERE (role_id, scope_type, permission_id) IN (
            SELECT r.role_id, t.scope_type, p.permission_id
            FROM (
                VALUES
                    ('annotator', 'project', 'annotation:read'),
                    ('annotator', 'project', 'review:read'),
                    ('annotator', 'project', 'review:write_own'),
                    ('annotator', 'collection', 'annotation:read'),
                    ('annotator', 'collection', 'review:read'),
                    ('annotator', 'collection', 'review:write_own')
            ) AS t(role_code, scope_type, permission_name)
            JOIN role r ON r.code = t.role_code
            JOIN permission p ON p.name = t.permission_name
        );
        """
    )
