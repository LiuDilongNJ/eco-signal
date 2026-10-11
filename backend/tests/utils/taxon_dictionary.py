from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlmodel import Session

from app.core import geo_db
from app.repositories import taxon_repository as taxon_module


@pytest.fixture(scope="session")
def geo_test_engine(db_engine: Engine) -> Generator[Engine, None, None]:
    database = f"ecosignal_geo_test_{uuid4().hex[:12]}"
    admin = create_engine(db_engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database}" TEMPLATE template0'))
    engine = create_engine(db_engine.url.set(database=database), pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{database}"'))
        admin.dispose()


@pytest.fixture
def taxon_dictionary(geo_test_engine: Engine, monkeypatch) -> Generator[Session, None, None]:
    with Session(geo_test_engine) as session:
        session.exec(text("DROP TABLE IF EXISTS public.col_xr_taxon_species"))
        session.exec(text("""
            CREATE TABLE public.col_xr_taxon_species (
                col_species_id VARCHAR(64),
                cached_scientific_name VARCHAR(255),
                cached_common_name VARCHAR(255),
                col_genus_id VARCHAR(64), col_genus_name VARCHAR(255),
                col_family_id VARCHAR(64), col_family_name VARCHAR(255),
                col_order_id VARCHAR(64), col_order_name VARCHAR(255),
                col_class_id VARCHAR(64), col_class_name VARCHAR(255),
                taxonomy_source VARCHAR(50), run_id VARCHAR(64),
                imported_at TIMESTAMP WITH TIME ZONE
            )
        """))
        session.commit()
        monkeypatch.setattr(geo_db, "get_geo_engine", lambda: geo_test_engine)
        taxon_module._option_cache.clear()
        try:
            yield session
        finally:
            taxon_module._option_cache.clear()
