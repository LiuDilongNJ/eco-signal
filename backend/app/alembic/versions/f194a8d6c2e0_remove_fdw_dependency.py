"""Remove unused database connection objects."""
from alembic import op


revision = 'f194a8d6c2e0'
down_revision = 'c3f8a1b2d4e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            table_oid oid;
            table_kind "char";
            server_oid oid;
            extension_oid oid;
            wrapper_name text;
            mapping record;
        BEGIN
            SELECT c.oid, c.relkind INTO table_oid, table_kind
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = 'geo_col_xr_taxon_species';
            SELECT s.oid, w.fdwname INTO server_oid, wrapper_name
            FROM pg_foreign_server s JOIN pg_foreign_data_wrapper w ON w.oid = s.srvfdw
            WHERE s.srvname = 'geo_server';

            IF table_oid IS NOT NULL AND (
                table_kind <> 'f' OR server_oid IS NULL OR NOT EXISTS (
                    SELECT 1 FROM pg_foreign_table
                    WHERE ftrelid = table_oid AND ftserver = server_oid
                )
            ) THEN
                RAISE EXCEPTION 'Taxon mapping has an unexpected object type or server';
            END IF;
            IF server_oid IS NOT NULL THEN
                IF wrapper_name <> 'postgres_fdw' THEN
                    RAISE EXCEPTION 'Geographical connection has an unexpected wrapper';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM pg_foreign_table
                    WHERE ftserver = server_oid AND ftrelid IS DISTINCT FROM table_oid
                ) THEN
                    RAISE EXCEPTION 'Geographical connection is used by additional tables';
                END IF;
            END IF;

            IF table_oid IS NOT NULL THEN
                DROP FOREIGN TABLE public.geo_col_xr_taxon_species RESTRICT;
            END IF;
            IF server_oid IS NOT NULL THEN
                FOR mapping IN SELECT umuser FROM pg_user_mappings WHERE srvid = server_oid LOOP
                    IF mapping.umuser = 0 THEN
                        DROP USER MAPPING FOR PUBLIC SERVER geo_server;
                    ELSE
                        EXECUTE format('DROP USER MAPPING FOR %I SERVER geo_server', pg_get_userbyid(mapping.umuser));
                    END IF;
                END LOOP;
                DROP SERVER geo_server RESTRICT;
            END IF;

            SELECT oid INTO extension_oid FROM pg_extension WHERE extname = 'postgres_fdw';
            IF extension_oid IS NOT NULL AND EXISTS (
                SELECT 1
                FROM pg_depend member
                JOIN pg_depend dependency
                    ON dependency.refclassid = member.classid AND dependency.refobjid = member.objid
                WHERE member.refclassid = 'pg_extension'::regclass
                  AND member.refobjid = extension_oid AND member.deptype = 'e'
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_depend own_member
                      WHERE own_member.classid = dependency.classid AND own_member.objid = dependency.objid
                        AND own_member.refclassid = 'pg_extension'::regclass
                        AND own_member.refobjid = extension_oid AND own_member.deptype = 'e'
                  )
            ) THEN
                RAISE NOTICE 'Database connection extension retained because other objects depend on it';
            ELSIF extension_oid IS NOT NULL THEN
                BEGIN
                    DROP EXTENSION postgres_fdw RESTRICT;
                EXCEPTION WHEN dependent_objects_still_exist THEN
                    RAISE NOTICE 'Database connection extension retained because other objects depend on it';
                END;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    raise RuntimeError("Database connection objects require restoration from a backup before downgrading")
