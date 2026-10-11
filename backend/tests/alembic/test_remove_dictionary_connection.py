import importlib
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

cleanup = importlib.import_module("app.alembic.versions.f194a8d6c2e0_remove_fdw_dependency")


@pytest.fixture
def connection(geo_test_engine):
    with geo_test_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


def apply_cleanup(connection):
    with Operations.context(MigrationContext.configure(connection)):
        cleanup.upgrade()


def seed_mapping(connection):
    connection.execute(text("CREATE EXTENSION postgres_fdw"))
    connection.execute(text("CREATE SERVER geo_server FOREIGN DATA WRAPPER postgres_fdw"))
    connection.execute(text("CREATE USER MAPPING FOR CURRENT_USER SERVER geo_server"))
    connection.execute(text("""
        CREATE FOREIGN TABLE public.geo_col_xr_taxon_species (col_species_id text)
        SERVER geo_server OPTIONS (schema_name 'public', table_name 'col_xr_taxon_species')
    """))


def object_exists(connection, name):
    return connection.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": name}).scalar_one()


def server_exists(connection, name):
    return connection.execute(text("SELECT EXISTS(SELECT 1 FROM pg_foreign_server WHERE srvname=:name)"), {"name": name}).scalar_one()


def test_cleanup_without_extension_is_repeatable(connection):
    apply_cleanup(connection)
    apply_cleanup(connection)
    assert not object_exists(connection, "public.geo_col_xr_taxon_species")
    assert not server_exists(connection, "geo_server")


def test_cleanup_removes_mappings_and_preserves_data(connection):
    seed_mapping(connection)
    connection.execute(text("CREATE USER MAPPING FOR PUBLIC SERVER geo_server"))
    connection.execute(text("CREATE TABLE business_records (id integer PRIMARY KEY)"))
    connection.execute(text("INSERT INTO business_records VALUES (194)"))
    connection.execute(text("CREATE TABLE IF NOT EXISTS col_xr_taxon_species (col_species_id text)"))
    connection.execute(text("INSERT INTO col_xr_taxon_species (col_species_id) VALUES ('proof')"))
    apply_cleanup(connection)
    assert not object_exists(connection, "public.geo_col_xr_taxon_species")
    assert not server_exists(connection, "geo_server")
    assert connection.execute(text("SELECT COUNT(*) FROM pg_user_mapping")).scalar_one() == 0
    assert connection.execute(text("SELECT COUNT(*) FROM pg_extension WHERE extname='postgres_fdw'")).scalar_one() == 0
    assert connection.execute(text("SELECT id FROM business_records")).scalar_one() == 194
    assert connection.execute(text("SELECT COUNT(*) FROM col_xr_taxon_species WHERE col_species_id='proof'")).scalar_one() == 1


def test_cleanup_retains_extension_used_by_another_server(connection):
    seed_mapping(connection)
    connection.execute(text("CREATE SERVER another_server FOREIGN DATA WRAPPER postgres_fdw"))
    apply_cleanup(connection)
    assert not server_exists(connection, "geo_server")
    assert server_exists(connection, "another_server")
    assert connection.execute(text("SELECT COUNT(*) FROM pg_extension WHERE extname='postgres_fdw'")).scalar_one() == 1


def test_cleanup_retains_shared_extension_without_owner_privileges(connection):
    role = f"dictionary_cleanup_{uuid4().hex[:12]}"
    seed_mapping(connection)
    connection.execute(text("CREATE SERVER another_server FOREIGN DATA WRAPPER postgres_fdw"))
    connection.execute(text(f'CREATE ROLE "{role}"'))
    connection.execute(text(f'GRANT USAGE ON FOREIGN DATA WRAPPER postgres_fdw TO "{role}"'))
    connection.execute(text(f'ALTER SERVER geo_server OWNER TO "{role}"'))
    connection.execute(text(f'ALTER FOREIGN TABLE geo_col_xr_taxon_species OWNER TO "{role}"'))
    connection.execute(text(f'SET LOCAL ROLE "{role}"'))
    apply_cleanup(connection)
    assert not server_exists(connection, "geo_server")
    assert server_exists(connection, "another_server")
    assert connection.execute(text("SELECT COUNT(*) FROM pg_extension WHERE extname='postgres_fdw'")).scalar_one() == 1


def test_cleanup_rejects_additional_tables_before_deleting_mapping(connection):
    seed_mapping(connection)
    connection.execute(text("CREATE FOREIGN TABLE extra_dictionary (id integer) SERVER geo_server"))
    with pytest.raises(DBAPIError, match="additional tables"):
        with connection.begin_nested():
            apply_cleanup(connection)
    assert object_exists(connection, "public.geo_col_xr_taxon_species")
    assert object_exists(connection, "public.extra_dictionary")
    assert server_exists(connection, "geo_server")
    assert connection.execute(text("SELECT COUNT(*) FROM pg_user_mapping")).scalar_one() == 1


def test_cleanup_restricts_dependent_views(connection):
    seed_mapping(connection)
    connection.execute(text("CREATE VIEW dictionary_view AS SELECT col_species_id FROM geo_col_xr_taxon_species"))
    with pytest.raises(DBAPIError, match="depend"):
        with connection.begin_nested():
            apply_cleanup(connection)
    assert object_exists(connection, "public.geo_col_xr_taxon_species")
    assert object_exists(connection, "public.dictionary_view")
    assert server_exists(connection, "geo_server")


def test_cleanup_protects_same_named_regular_table(connection):
    connection.execute(text("CREATE TABLE geo_col_xr_taxon_species (id integer)"))
    connection.execute(text("INSERT INTO geo_col_xr_taxon_species VALUES (194)"))
    with pytest.raises(DBAPIError, match="unexpected object type or server"):
        with connection.begin_nested():
            apply_cleanup(connection)
    assert connection.execute(text("SELECT id FROM geo_col_xr_taxon_species")).scalar_one() == 194


def test_cleanup_rejects_table_mapped_to_another_server(connection):
    connection.execute(text("CREATE EXTENSION postgres_fdw"))
    connection.execute(text("CREATE SERVER another_server FOREIGN DATA WRAPPER postgres_fdw"))
    connection.execute(text("CREATE FOREIGN TABLE geo_col_xr_taxon_species (id integer) SERVER another_server"))
    with pytest.raises(DBAPIError, match="unexpected object type or server"):
        with connection.begin_nested():
            apply_cleanup(connection)
    assert server_exists(connection, "another_server")
    assert object_exists(connection, "public.geo_col_xr_taxon_species")


def test_cleanup_rejects_server_with_another_wrapper(connection):
    connection.execute(text("CREATE FOREIGN DATA WRAPPER another_wrapper"))
    connection.execute(text("CREATE SERVER geo_server FOREIGN DATA WRAPPER another_wrapper"))
    with pytest.raises(DBAPIError, match="unexpected wrapper"):
        with connection.begin_nested():
            apply_cleanup(connection)
    assert server_exists(connection, "geo_server")


def test_cleanup_removes_empty_server(connection):
    connection.execute(text("CREATE EXTENSION postgres_fdw"))
    connection.execute(text("CREATE SERVER geo_server FOREIGN DATA WRAPPER postgres_fdw"))
    apply_cleanup(connection)
    assert not server_exists(connection, "geo_server")


def test_downgrade_requires_manual_restoration():
    with pytest.raises(RuntimeError, match="restoration from a backup"):
        cleanup.downgrade()
