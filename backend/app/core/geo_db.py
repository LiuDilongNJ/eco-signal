import os
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.sql.elements import TextClause

from app.core.config import settings

DEFAULT_STATEMENT_TIMEOUT_MS = 3000


def _geo_db_url() -> str:
    host = os.getenv("GEO_DB_SERVER", "geo_db")
    port = os.getenv("GEO_DB_PORT", "5432")
    database = os.getenv("GEO_DB_NAME", "geo_db")
    return f"postgresql+psycopg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{host}:{port}/{database}"


@lru_cache(maxsize=1)
def get_geo_engine() -> Engine:
    return create_engine(_geo_db_url(), pool_pre_ping=True, connect_args={"connect_timeout": 3})


def fetch_geo_rows(
    sql: str | TextClause,
    params: dict[str, Any],
    timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> list[dict[str, Any]]:
    """Run a read-only query on the geographical database; SQLAlchemy errors propagate to the caller."""
    statement = text(sql) if isinstance(sql, str) else sql
    with get_geo_engine().connect() as connection:
        connection.execute(text(f"SET LOCAL statement_timeout = '{int(timeout_ms)}ms'"))
        return [dict(row) for row in connection.execute(statement, params).mappings().all()]
