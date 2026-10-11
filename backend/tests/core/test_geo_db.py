from collections.abc import Generator

import pytest

from app.core import geo_db
from app.core.config import settings


@pytest.fixture
def fresh_geo_engine() -> Generator[None, None, None]:
    geo_db.get_geo_engine.cache_clear()
    yield
    geo_db.get_geo_engine.cache_clear()


def test_get_geo_engine_uses_environment_connection(monkeypatch, fresh_geo_engine) -> None:
    monkeypatch.setenv("GEO_DB_SERVER", "geo-host")
    monkeypatch.setenv("GEO_DB_PORT", "6543")
    monkeypatch.setenv("GEO_DB_NAME", "dictionary")
    engine = geo_db.get_geo_engine()
    try:
        assert (engine.url.host, engine.url.port, engine.url.database) == ("geo-host", 6543, "dictionary")
        assert engine.url.username == settings.POSTGRES_USER
        assert geo_db.get_geo_engine() is engine
    finally:
        engine.dispose()


def test_get_geo_engine_defaults_to_compose_service(monkeypatch, fresh_geo_engine) -> None:
    for name in ("GEO_DB_SERVER", "GEO_DB_PORT", "GEO_DB_NAME"):
        monkeypatch.delenv(name, raising=False)
    engine = geo_db.get_geo_engine()
    try:
        assert (engine.url.host, engine.url.port, engine.url.database) == ("geo_db", 5432, "geo_db")
    finally:
        engine.dispose()
