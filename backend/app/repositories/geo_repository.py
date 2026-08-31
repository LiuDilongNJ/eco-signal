import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, func, select

from app.core.config import settings
from app.models.site import IhoSeaArea, IucnGet
from app.repositories.query_helpers import apply_pagination


class GeoDataUnavailableError(Exception):
    """Raised when geo_db cannot serve a required read."""


GeoMatchStatus = Literal["matched", "unmatched", "ambiguous"]


@dataclass(frozen=True)
class GeoOptionMatch:
    gid: str
    name: str


@dataclass(frozen=True)
class CoordinateMatches:
    gadm_status: GeoMatchStatus
    gadm0: GeoOptionMatch | None
    gadm1: GeoOptionMatch | None
    gadm2: GeoOptionMatch | None
    iho_status: GeoMatchStatus
    iho: GeoOptionMatch | None


def _geo_db_url() -> str:
    host = os.getenv("GEO_DB_SERVER", "geo_db")
    port = os.getenv("GEO_DB_PORT", "5432")
    database = os.getenv("GEO_DB_NAME", "geo_db")
    return f"postgresql+psycopg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{host}:{port}/{database}"


@lru_cache(maxsize=1)
def _geo_engine():
    return create_engine(_geo_db_url(), pool_pre_ping=True, connect_args={"connect_timeout": 3})


class GeoRepository:
    """Direct geo_db reads in production; transaction-local fixtures in tests."""

    @staticmethod
    def _uses_test_tables() -> bool:
        return settings.POSTGRES_DB.endswith("_test")

    @staticmethod
    def _remote_rows(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            with _geo_engine().connect() as connection:
                connection.execute(text("SET LOCAL statement_timeout = '3000ms'"))
                return [dict(row) for row in connection.execute(text(sql), params).mappings().all()]
        except SQLAlchemyError as exc:
            raise GeoDataUnavailableError("Geo data is temporarily unavailable") from exc

    def get_gadm_options(self, session: Session, level: int, parent_gid: str | None = None, search: str | None = None, page: int = 1, page_size: int = 100) -> tuple[list[tuple[str, str]], int]:
        if level not in (0, 1, 2):
            return [], 0
        table, id_col, name_col, parent_col = {
            0: ("adm_0", '"GID_0"', '"COUNTRY"', None),
            1: ("adm_1", '"GID_1"', '"NAME_1"', '"GID_0"'),
            2: ("adm_2", '"GID_2"', '"NAME_2"', '"GID_1"'),
        }[level]
        clauses = [f"{name_col} IS NOT NULL", f"{name_col} <> ''"]
        params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
        if search:
            clauses.append(f"{name_col} ILIKE :search")
            params["search"] = f"%{search}%"
        if parent_col and parent_gid:
            clauses.append(f"{parent_col} = :parent_gid")
            params["parent_gid"] = parent_gid
        where = " AND ".join(clauses)
        count_sql = f"SELECT COUNT(*) AS count FROM {table} WHERE {where}"
        rows_sql = f"SELECT {id_col} AS gid, {name_col} AS name FROM {table} WHERE {where} ORDER BY {name_col}, {id_col} LIMIT :limit OFFSET :offset"
        if self._uses_test_tables():
            count = session.execute(text(count_sql), params).scalar_one()
            rows = session.execute(text(rows_sql), params).fetchall()
            return [(str(row[0]), str(row[1])) for row in rows], int(count)
        count = self._remote_rows(count_sql, params)[0]["count"]
        rows = self._remote_rows(rows_sql, params)
        return [(str(row["gid"]), str(row["name"])) for row in rows], int(count)

    def get_iho_options(self, session: Session, search: str | None = None, page: int = 1, page_size: int = 100) -> tuple[list[tuple[int, str]], int]:
        if self._uses_test_tables():
            stmt = select(IhoSeaArea.id, IhoSeaArea.name).where(IhoSeaArea.name.is_not(None), IhoSeaArea.name != "")
            if search:
                stmt = stmt.where(IhoSeaArea.name.ilike(f"%{search}%"))
            total = session.exec(select(func.count()).select_from(stmt.order_by(None).subquery())).one()
            rows = session.exec(apply_pagination(stmt.distinct().order_by(IhoSeaArea.name, IhoSeaArea.id), page, page_size)).all()
            return [(int(row[0]), str(row[1])) for row in rows], int(total)
        params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
        where = "name IS NOT NULL AND name <> ''"
        if search:
            where += " AND name ILIKE :search"
            params["search"] = f"%{search}%"
        total = self._remote_rows(f"SELECT COUNT(*) AS count FROM iho_sea_area WHERE {where}", params)[0]["count"]
        rows = self._remote_rows(f"SELECT id, name FROM iho_sea_area WHERE {where} ORDER BY name, id LIMIT :limit OFFSET :offset", params)
        return [(int(row["id"]), str(row["name"])) for row in rows], int(total)

    def get_iucn_options(self, session: Session, level: int, parent_id: int | None = None, search: str | None = None, page: int = 1, page_size: int = 100) -> tuple[list[IucnGet], int]:
        stmt = select(IucnGet).where(IucnGet.level == level)
        if search:
            stmt = stmt.where(IucnGet.name.ilike(f"%{search}%"))
        if parent_id is not None:
            stmt = stmt.where(IucnGet.pid == parent_id)
        total = session.exec(select(func.count()).select_from(stmt.order_by(None).subquery())).one()
        return list(session.exec(apply_pagination(stmt.order_by(IucnGet.name, IucnGet.iucn_get_id), page, page_size)).all()), int(total)

    def resolve_iho(self, session: Session, iho_id: int) -> GeoOptionMatch | None:
        if self._uses_test_tables():
            row = session.exec(select(IhoSeaArea.id, IhoSeaArea.name).where(IhoSeaArea.id == iho_id)).first()
            return GeoOptionMatch(str(row[0]), str(row[1])) if row and row[1] else None
        rows = self._remote_rows("SELECT id, name FROM iho_sea_area WHERE id = :id LIMIT 2", {"id": iho_id})
        return GeoOptionMatch(str(rows[0]["id"]), str(rows[0]["name"])) if len(rows) == 1 and rows[0]["name"] else None

    def resolve_iho_id_by_name(self, session: Session, name: str) -> int | None:
        if self._uses_test_tables():
            return session.exec(select(IhoSeaArea.id).where(IhoSeaArea.name == name)).first()
        rows = self._remote_rows("SELECT id FROM iho_sea_area WHERE name = :name LIMIT 2", {"name": name})
        return int(rows[0]["id"]) if len(rows) == 1 else None

    def resolve_gadm_hierarchy(self, session: Session, g0: str | None, g1: str | None, g2: str | None) -> dict[str, str | None]:
        empty = {key: None for key in ("gadm0", "gadm1", "gadm2", "gadm0_gid", "gadm1_gid", "gadm2_gid")}
        if not g0:
            return empty
        if self._uses_test_tables():
            return self._resolve_gadm_hierarchy_from_session(session, g0, g1, g2)
        country = self._remote_rows('SELECT "COUNTRY" AS name, "GID_0" AS gid FROM adm_0 WHERE "GID_0" = :g0 LIMIT 2', {"g0": g0})
        if len(country) != 1:
            raise ValueError("Invalid GADM level 0 selection")
        result = {**empty, "gadm0": country[0]["name"], "gadm0_gid": country[0]["gid"]}
        if g1:
            level1 = self._remote_rows('SELECT "NAME_1" AS name, "GID_1" AS gid FROM adm_1 WHERE "GID_1" = :g1 AND "GID_0" = :g0 LIMIT 2', {"g0": g0, "g1": g1})
            if len(level1) != 1:
                raise ValueError("Invalid GADM level 1 selection")
            result.update(gadm1=level1[0]["name"], gadm1_gid=level1[0]["gid"])
        if g2:
            clauses = ['"GID_2" = :g2', '"GID_0" = :g0']
            params: dict[str, Any] = {"g0": g0, "g2": g2}
            if g1:
                clauses.append('"GID_1" = :g1')
                params["g1"] = g1
            level2 = self._remote_rows('SELECT "NAME_2" AS name, "GID_2" AS gid, "GID_1" AS parent_gid FROM adm_2 WHERE ' + ' AND '.join(clauses) + ' LIMIT 2', params)
            if len(level2) != 1:
                raise ValueError("Invalid GADM level 2 selection")
            result.update(gadm2=level2[0]["name"], gadm2_gid=level2[0]["gid"])
            if not result["gadm1_gid"]:
                parent = self._remote_rows('SELECT "NAME_1" AS name, "GID_1" AS gid FROM adm_1 WHERE "GID_1" = :g1 LIMIT 2', {"g1": level2[0]["parent_gid"]})
                if len(parent) == 1:
                    result.update(gadm1=parent[0]["name"], gadm1_gid=parent[0]["gid"])
        return result

    @staticmethod
    def _resolve_gadm_hierarchy_from_session(session: Session, g0: str, g1: str | None, g2: str | None) -> dict[str, str | None]:
        row0 = session.execute(text('SELECT "COUNTRY", "GID_0" FROM adm_0 WHERE "GID_0" = :id LIMIT 2'), {"id": g0}).fetchall()
        if len(row0) != 1: raise ValueError("Invalid GADM level 0 selection")
        result: dict[str, str | None] = {"gadm0": row0[0][0], "gadm0_gid": row0[0][1], "gadm1": None, "gadm1_gid": None, "gadm2": None, "gadm2_gid": None}
        if g1:
            row1 = session.execute(text('SELECT "NAME_1", "GID_1" FROM adm_1 WHERE "GID_1" = :id AND "GID_0" = :g0 LIMIT 2'), {"id": g1, "g0": g0}).fetchall()
            if len(row1) != 1: raise ValueError("Invalid GADM level 1 selection")
            result.update(gadm1=row1[0][0], gadm1_gid=row1[0][1])
        if g2:
            row2 = session.execute(text('SELECT "NAME_2", "GID_2", "GID_1" FROM adm_2 WHERE "GID_2" = :id AND "GID_0" = :g0 LIMIT 2'), {"id": g2, "g0": g0}).fetchall()
            if len(row2) != 1: raise ValueError("Invalid GADM level 2 selection")
            result.update(gadm2=row2[0][0], gadm2_gid=row2[0][1])
            if not result["gadm1_gid"]:
                parent = session.execute(text('SELECT "NAME_1", "GID_1" FROM adm_1 WHERE "GID_1" = :id LIMIT 2'), {"id": row2[0][2]}).fetchall()
                if len(parent) == 1: result.update(gadm1=parent[0][0], gadm1_gid=parent[0][1])
        return result

    def geometry_ewkb(self, session: Session, source: Literal["gadm0", "gadm1", "gadm2", "iho"], identifier: str | int) -> bytes | None:
        if self._uses_test_tables():
            return None
        if source == "iho":
            sql, params = """
                SELECT ST_AsEWKB(ST_SimplifyPreserveTopology(d.geom, 0.01)) AS geometry
                FROM iho_sea_area, LATERAL ST_Dump(geometry) AS d(path, geom)
                WHERE id = :id
                ORDER BY ST_Area(d.geom::geography) DESC
                LIMIT 1
            """, {"id": identifier}
        else:
            table, column = {"gadm0": ("adm_0", '"GID_0"'), "gadm1": ("adm_1", '"GID_1"'), "gadm2": ("adm_2", '"GID_2"')}[source]
            sql, params = f"""
                SELECT ST_AsEWKB(ST_SimplifyPreserveTopology(d.geom, 0.01)) AS geometry
                FROM {table}, LATERAL ST_Dump(geometry) AS d(path, geom)
                WHERE {column} = :id
                ORDER BY ST_Area(d.geom::geography) DESC
                LIMIT 1
            """, {"id": identifier}
        rows = self._remote_rows(sql, params)
        return bytes(rows[0]["geometry"]) if rows and rows[0]["geometry"] is not None else None

    def coordinate_matches(self, longitude: float, latitude: float) -> CoordinateMatches:
        point = "ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)"
        params = {"longitude": longitude, "latitude": latitude}
        queries = [
            'SELECT "GID_0" AS gadm0_gid, "COUNTRY" AS gadm0, "GID_1" AS gadm1_gid, "NAME_1" AS gadm1, "GID_2" AS gadm2_gid, "NAME_2" AS gadm2 FROM adm_2 WHERE ST_Covers(geometry, ' + point + ') LIMIT 2',
            'SELECT "GID_0" AS gadm0_gid, "COUNTRY" AS gadm0, "GID_1" AS gadm1_gid, "NAME_1" AS gadm1, NULL::text AS gadm2_gid, NULL::text AS gadm2 FROM adm_1 WHERE ST_Covers(geometry, ' + point + ') LIMIT 2',
            'SELECT "GID_0" AS gadm0_gid, "COUNTRY" AS gadm0, NULL::text AS gadm1_gid, NULL::text AS gadm1, NULL::text AS gadm2_gid, NULL::text AS gadm2 FROM adm_0 WHERE ST_Covers(geometry, ' + point + ') LIMIT 2',
        ]
        gadm_rows: list[dict[str, Any]] = []
        for query in queries:
            gadm_rows = self._remote_rows(query, params)
            if gadm_rows: break
        if len(gadm_rows) == 1:
            row = gadm_rows[0]
            gadm0 = GeoOptionMatch(str(row["gadm0_gid"]), str(row["gadm0"]))
            gadm1 = GeoOptionMatch(str(row["gadm1_gid"]), str(row["gadm1"])) if row["gadm1_gid"] else None
            gadm2 = GeoOptionMatch(str(row["gadm2_gid"]), str(row["gadm2"])) if row["gadm2_gid"] else None
            gadm_status: GeoMatchStatus = "matched"
        else:
            gadm_status, gadm0, gadm1, gadm2 = ("ambiguous" if gadm_rows else "unmatched"), None, None, None
        iho_rows = self._remote_rows(f"SELECT id, name FROM iho_sea_area WHERE ST_Covers(geometry, {point}) LIMIT 2", params)
        iho_status: GeoMatchStatus = "matched" if len(iho_rows) == 1 else ("ambiguous" if iho_rows else "unmatched")
        iho = GeoOptionMatch(str(iho_rows[0]["id"]), str(iho_rows[0]["name"])) if len(iho_rows) == 1 else None
        return CoordinateMatches(gadm_status, gadm0, gadm1, gadm2, iho_status, iho)


geo_repository = GeoRepository()
