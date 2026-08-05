"""
setup_fdw.py - Configure postgres_fdw in the main database.

This script is called by prestart.sh on every container startup.
It is idempotent: safe to run multiple times.

It connects to the main database and:
1. Creates the postgres_fdw extension.
2. Creates a foreign server pointing to geo_db.
3. Creates a user mapping.
4. Imports iho_sea_area and adm_0/adm_1/adm_2 as foreign tables.
5. Creates a dedicated XR taxon foreign table mapping:
   geo_col_xr_taxon_species -> geo_db.public.col_xr_taxon_species
"""

import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def get_main_db_url() -> str:
    """Build the main database URL from environment variables."""
    host = os.getenv("POSTGRES_SERVER", "db")
    port = os.getenv("POSTGRES_PORT", "5432")
    dbname = os.getenv("POSTGRES_DB", "ecosignal")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"


def setup_fdw() -> None:
    """Run all FDW setup steps against the main database."""
    geo_host = os.getenv("GEO_DB_SERVER", "geo_db")
    geo_port = os.getenv("GEO_DB_PORT", "5432")
    geo_dbname = os.getenv("GEO_DB_NAME", "geo_db")
    geo_user = os.getenv("POSTGRES_USER", "postgres")
    geo_password = os.getenv("POSTGRES_PASSWORD", "postgres")

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(get_main_db_url(), pool_pre_ping=True)
        log.info("Connected to main database, setting up FDW ...")

        with engine.begin() as conn:
            # 1. Enable postgres_fdw extension
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgres_fdw"))
            log.info("postgres_fdw extension enabled.")

            # 2. Create foreign server (idempotent via DO block)
            conn.execute(text(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_foreign_server WHERE srvname = 'geo_server'
                    ) THEN
                        CREATE SERVER geo_server
                            FOREIGN DATA WRAPPER postgres_fdw
                            OPTIONS (host '{geo_host}', port '{geo_port}', dbname '{geo_dbname}');
                    ELSE
                        -- Update options in case host/port changed
                        ALTER SERVER geo_server
                            OPTIONS (SET host '{geo_host}', SET port '{geo_port}', SET dbname '{geo_dbname}');
                    END IF;
                END
                $$;
            """))
            log.info("Foreign server 'geo_server' configured.")

            # 3. Create user mapping (idempotent via DO block)
            conn.execute(text(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_user_mappings
                        WHERE srvname = 'geo_server'
                          AND usename = current_user
                    ) THEN
                        CREATE USER MAPPING FOR CURRENT_USER
                            SERVER geo_server
                            OPTIONS (user '{geo_user}', password '{geo_password}');
                    ELSE
                        ALTER USER MAPPING FOR CURRENT_USER
                            SERVER geo_server
                            OPTIONS (SET user '{geo_user}', SET password '{geo_password}');
                    END IF;
                END
                $$;
            """))
            log.info("User mapping configured.")

            # 4. Drop existing foreign tables and re-import from geo_db
            # Only import if the geo_db tables exist (i.e., data has been loaded)
            try:
                conn.execute(text("DROP FOREIGN TABLE IF EXISTS iho_sea_area CASCADE"))
                conn.execute(text("DROP FOREIGN TABLE IF EXISTS adm_0 CASCADE"))
                conn.execute(text("DROP FOREIGN TABLE IF EXISTS adm_1 CASCADE"))
                conn.execute(text("DROP FOREIGN TABLE IF EXISTS adm_2 CASCADE"))
                conn.execute(text("""
                    IMPORT FOREIGN SCHEMA public
                        LIMIT TO (iho_sea_area, adm_0, adm_1, adm_2)
                        FROM SERVER geo_server
                        INTO public
                """))
                log.info("Foreign tables (iho_sea_area, adm_0, adm_1, adm_2) imported successfully.")
            except Exception as e:
                # geo_db tables may not exist yet (before first data import)
                log.warning(
                    "Could not import foreign tables (geo_db may be empty, run import_geo_data.py first): %s", e
                )

            # 5. Ensure XR taxon foreign table exists with a stable local name
            #    We create this explicitly to avoid name collisions and to keep
            #    API-side queries predictable.
            try:
                conn.execute(text("DROP FOREIGN TABLE IF EXISTS geo_col_xr_taxon_species CASCADE"))
                conn.execute(text("""
                    CREATE FOREIGN TABLE geo_col_xr_taxon_species (
                        col_species_id VARCHAR(64),
                        cached_scientific_name VARCHAR(255),
                        cached_common_name VARCHAR(255),
                        col_genus_id VARCHAR(64),
                        col_genus_name VARCHAR(255),
                        col_family_id VARCHAR(64),
                        col_family_name VARCHAR(255),
                        col_order_id VARCHAR(64),
                        col_order_name VARCHAR(255),
                        col_class_id VARCHAR(64),
                        col_class_name VARCHAR(255),
                        taxonomy_source VARCHAR(50),
                        run_id VARCHAR(64),
                        imported_at TIMESTAMP WITH TIME ZONE
                    )
                    SERVER geo_server
                    OPTIONS (schema_name 'public', table_name 'col_xr_taxon_species')
                """))
                log.info("Foreign table geo_col_xr_taxon_species created successfully.")
            except Exception as e:
                log.warning(
                    "Could not create foreign table geo_col_xr_taxon_species (XR table may be empty/not created yet): %s",
                    e,
                )

        log.info("FDW setup complete.")

    except Exception as e:
        log.error("FDW setup failed: %s", e)
        # Do not exit with error - main app should still start even if geo_db is unavailable
        sys.exit(0)


if __name__ == "__main__":
    setup_fdw()
