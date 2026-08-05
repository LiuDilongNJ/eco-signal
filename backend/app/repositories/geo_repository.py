import logging
import os
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlmodel import Session, func, select

from app.models.site import IhoSeaArea, IucnGet
from app.repositories.base import BaseRepository
from app.repositories.query_helpers import apply_pagination

log = logging.getLogger(__name__)


class GeoDataUnavailableError(Exception):
    """Raised when geo_db foreign tables (adm_0/1/2) are not yet available."""
    pass


def _try_reimport_fdw_tables() -> bool:
    """
    Attempt to re-import GADM foreign tables via a fresh DB connection.

    This is called as a self-healing mechanism when adm_* tables are missing
    (e.g., setup_fdw.py silently failed at startup because geo_db wasn't ready yet).
    Uses a separate engine to avoid interfering with the current session's transaction.
    Returns True if the import succeeded, False otherwise.
    """
    host = os.getenv("POSTGRES_SERVER", "db")
    port = os.getenv("POSTGRES_PORT", "5432")
    dbname = os.getenv("POSTGRES_DB", "ecosignal")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"

    try:
        eng = create_engine(url, pool_pre_ping=True)
        with eng.begin() as conn:
            conn.execute(text("DROP FOREIGN TABLE IF EXISTS adm_0 CASCADE"))
            conn.execute(text("DROP FOREIGN TABLE IF EXISTS adm_1 CASCADE"))
            conn.execute(text("DROP FOREIGN TABLE IF EXISTS adm_2 CASCADE"))
            conn.execute(text("""
                IMPORT FOREIGN SCHEMA public
                    LIMIT TO (adm_0, adm_1, adm_2)
                    FROM SERVER geo_server INTO public
            """))
        log.info("GADM foreign tables re-imported successfully.")
        return True
    except Exception as e:
        log.warning("Failed to re-import GADM foreign tables (geo_db may still be loading): %s", e)
        return False


class GeoRepository(BaseRepository[IhoSeaArea, Any, Any]):
    def __init__(self):
        super().__init__(IhoSeaArea)

    def _execute_gadm_query(
        self, session: Session, sql: str, params: dict
    ) -> list[tuple[Any, ...]]:
        """
        Execute a GADM raw SQL query with self-healing on UndefinedTable errors.

        If the foreign tables are missing, attempts to re-import them via FDW
        and retries once. Raises GeoDataUnavailableError if recovery fails.
        """
        try:
            return list(session.execute(text(sql), params).fetchall())
        except ProgrammingError:
            session.rollback()
            log.warning("GADM foreign table missing, attempting FDW re-import ...")
            if _try_reimport_fdw_tables():
                try:
                    return list(session.execute(text(sql), params).fetchall())
                except ProgrammingError:
                    session.rollback()
            raise GeoDataUnavailableError(
                "Geo data is not yet available. Please wait for geo_db import to complete."
            )

    def get_gadm_options(
        self,
        session: Session,
        level: int,
        parent_gid: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[tuple[str, str]], int]:
        if level not in (0, 1, 2):
            return [], 0

        table, id_column, name_column, parent_column = {
            0: ("adm_0", '"GID_0"', '"COUNTRY"', None),
            1: ("adm_1", '"GID_1"', '"NAME_1"', '"GID_0"'),
            2: ("adm_2", '"GID_2"', '"NAME_2"', '"GID_1"'),
        }[level]
        conditions = [f"{name_column} IS NOT NULL", f"{name_column} <> ''"]
        params: dict[str, Any] = {
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        if search:
            conditions.append(f"{name_column} ILIKE :like_search")
            params["like_search"] = f"%{search}%"
        if parent_column is not None and parent_gid is not None:
            conditions.append(f"{parent_column} = :parent_gid")
            params["parent_gid"] = parent_gid
        where_sql = " AND ".join(conditions)
        total_rows = self._execute_gadm_query(
            session,
            f"SELECT COUNT(*) FROM {table} WHERE {where_sql}",
            params,
        )
        rows = self._execute_gadm_query(
            session,
            f"""
                SELECT {id_column} AS gid, {name_column} AS name
                FROM {table}
                WHERE {where_sql}
                ORDER BY {name_column}, {id_column}
                LIMIT :limit OFFSET :offset
            """,
            params,
        )
        return rows, int(total_rows[0][0])

    def get_iho_options(
        self,
        session: Session,
        search: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[tuple[int, str]], int]:
        stmt = select(IhoSeaArea.id, IhoSeaArea.name).where(
            IhoSeaArea.name.is_not(None),
            IhoSeaArea.name != "",
        )
        if search:
            stmt = stmt.where(IhoSeaArea.name.ilike(f"%{search}%"))
        stmt = stmt.distinct().order_by(IhoSeaArea.name, IhoSeaArea.id)
        total = session.exec(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        ).one()
        return list(session.exec(apply_pagination(stmt, page, page_size)).all()), total

    def get_iucn_options(
        self,
        session: Session,
        level: int,
        parent_id: int | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[IucnGet], int]:
        stmt = select(IucnGet).where(IucnGet.level == level)
        if search:
            stmt = stmt.where(IucnGet.name.ilike(f"%{search}%"))
        if parent_id is not None:
            stmt = stmt.where(IucnGet.pid == parent_id)
        total = session.exec(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        ).one()
        stmt = stmt.order_by(IucnGet.name, IucnGet.iucn_get_id)
        return list(session.exec(apply_pagination(stmt, page, page_size)).all()), total


geo_repository = GeoRepository()
