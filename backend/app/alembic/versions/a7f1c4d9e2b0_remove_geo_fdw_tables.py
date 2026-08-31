"""remove GADM and IHO postgres_fdw tables

Revision ID: a7f1c4d9e2b0
Revises: f4a6c8e9b012
Create Date: 2026-08-30 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "a7f1c4d9e2b0"
down_revision: str | None = "c8e1a2b3d4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("adm_0", "adm_1", "adm_2", "iho_sea_area"):
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relname = '{table}' AND c.relkind = 'f'
                ) THEN
                    EXECUTE 'DROP FOREIGN TABLE public.{table}';
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    # Foreign mappings are runtime configuration. They are intentionally not
    # recreated because geographic reads now use geo_db directly.
    pass
