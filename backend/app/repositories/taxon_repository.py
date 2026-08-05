import itertools
from datetime import UTC, datetime
from functools import lru_cache
from time import monotonic
from typing import Any

from sqlalchemy import (
    String,
    bindparam,
    case,
    column,
    create_engine,
    literal,
    text,
    values,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, func, or_, select

from app.core.config import settings
from app.models.annotation import Annotation
from app.models.taxon import SoundClassification, Taxon, TaxonSoundType
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
    apply_pagination,
)
from app.schemas.taxon import TaxonCreate, TaxonImportRow, TaxonRank, TaxonUpdate

_TAXON_FILTER_SPECS: list[FilterSpec] = [
    ("taxon_id", Taxon.taxon_id, FilterOp.EQ),
    ("cached_scientific_name", Taxon.cached_scientific_name, FilterOp.LIKE),
    ("cached_common_name", Taxon.cached_common_name, FilterOp.LIKE),
    ("taxonomy_source", Taxon.taxonomy_source, FilterOp.EQ),
    ("col_class_id", Taxon.col_class_id, FilterOp.EQ),
    ("col_order_id", Taxon.col_order_id, FilterOp.EQ),
    ("creation_date", Taxon.creation_date, FilterOp.DATE_RANGE),
    ("last_synced", Taxon.last_synced, FilterOp.DATE_RANGE),
]

_TAXON_SORT_FIELDS: dict[str, Any] = {
    "taxon_id": Taxon.taxon_id,
    "scientific_name": Taxon.cached_scientific_name,
    "common_name": Taxon.cached_common_name,
    "creation_date": Taxon.creation_date,
    "taxonomy_source": Taxon.taxonomy_source,
    "col_class_id": Taxon.col_class_id,
    "col_order_id": Taxon.col_order_id,
    "last_synced": Taxon.last_synced,
}

_HIERARCHY_RANKS = ("species", "genus", "family", "order", "class")
_HIERARCHY_KEY_TO_RANK = {
    f"col_{rank}_name": rank for rank in _HIERARCHY_RANKS
}
_HIERARCHY_FILTER_KEYS = set(_HIERARCHY_KEY_TO_RANK)
_HIERARCHY_SORT_KEYS = _HIERARCHY_FILTER_KEYS

_REMOTE_COLUMNS = (
    "col_species_id",
    "cached_scientific_name",
    "cached_common_name",
    "col_genus_id",
    "col_family_id",
    "col_order_id",
    "col_class_id",
    "taxonomy_source",
    "imported_at",
)

_RANK_COLUMN_MAP: dict[TaxonRank, tuple[str, str]] = {
    "class": ("col_class_id", "col_class_name"),
    "order": ("col_order_id", "col_order_name"),
    "family": ("col_family_id", "col_family_name"),
    "genus": ("col_genus_id", "col_genus_name"),
    "species": ("col_species_id", "cached_scientific_name"),
}


def _hierarchy_remote_name_column(rank: str) -> str:
    return _RANK_COLUMN_MAP[rank][1]  # type: ignore[index]


_OPTION_CACHE_TTL_SECONDS = 300
_option_cache: dict[tuple[Any, ...], tuple[float, list[dict[str, str]], int]] = {}

# Keep IN-clause bind params well under the PostgreSQL wire-protocol limit (65535).
_IMPORT_IN_CLAUSE_BATCH = 30_000


def _get_geo_db_url() -> str:
    import os

    geo_host = os.getenv("GEO_DB_SERVER", "geo_db")
    geo_port = os.getenv("GEO_DB_PORT", "5432")
    geo_db_name = os.getenv("GEO_DB_NAME", "geo_db")
    return (
        f"postgresql+psycopg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{geo_host}:{geo_port}/{geo_db_name}"
    )


@lru_cache(maxsize=1)
def _get_geo_engine():
    return create_engine(_get_geo_db_url(), pool_pre_ping=True)


class RemoteTaxonLookupError(Exception):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class TaxonRepository:
    def _use_direct_geo_lookup(self) -> bool:
        return not settings.POSTGRES_DB.endswith("_test")

    def _fetch_geo_rows(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with _get_geo_engine().connect() as conn:
            return [dict(row) for row in conn.execute(text(sql), params).mappings().all()]

    def _fetch_geo_scalar(self, sql: str, params: dict[str, Any]) -> int:
        with _get_geo_engine().connect() as conn:
            return int(conn.execute(text(sql), params).scalar_one())

    def _get_cached_option_page(self, cache_key: tuple[Any, ...]) -> tuple[list[dict[str, str]], int] | None:
        cached = _option_cache.get(cache_key)
        if cached is None:
            return None
        expires_at, rows, total = cached
        if expires_at <= monotonic():
            _option_cache.pop(cache_key, None)
            return None
        return rows, total

    def _set_cached_option_page(self, cache_key: tuple[Any, ...], rows: list[dict[str, str]], total: int) -> None:
        _option_cache[cache_key] = (monotonic() + _OPTION_CACHE_TTL_SECONDS, rows, total)

    def _remote_table_available(self, session: Session) -> bool:
        stmt = text("SELECT to_regclass('public.geo_col_xr_taxon_species') IS NOT NULL")
        return bool(session.execute(stmt).scalar_one())

    def _rows_from_remote_search(
        self,
        session: Session,
        q: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        where_sql = ""
        if q:
            params["term"] = f"%{q}%"
            where_sql = "WHERE cached_scientific_name ILIKE :term OR cached_common_name ILIKE :term"

        sql = text(
            f"""
            SELECT {", ".join(_REMOTE_COLUMNS)}
            FROM geo_col_xr_taxon_species
            {where_sql}
            ORDER BY cached_scientific_name ASC, col_species_id ASC
            LIMIT :limit OFFSET :offset
            """
        )
        rows = session.execute(sql, params).mappings().all()
        return [dict(r) for r in rows]

    def _bridge_local_taxon_ids(
        self,
        session: Session,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not rows:
            return rows

        species_ids = [r["col_species_id"] for r in rows if r.get("col_species_id")]
        if not species_ids:
            return rows

        existing = session.exec(select(Taxon).where(Taxon.col_species_id.in_(species_ids))).all()
        existing_map = {t.col_species_id: t for t in existing if t.col_species_id}

        created = False
        for row in rows:
            species_id = row.get("col_species_id")
            if not species_id:
                continue
            taxon = existing_map.get(species_id)
            if taxon is None:
                imported_at = row.get("imported_at")
                if not isinstance(imported_at, datetime):
                    imported_at = datetime.now(UTC)
                taxon = Taxon(
                    col_species_id=species_id,
                    col_genus_id=row.get("col_genus_id"),
                    col_family_id=row.get("col_family_id"),
                    col_order_id=row.get("col_order_id"),
                    col_class_id=row.get("col_class_id"),
                    cached_scientific_name=row.get("cached_scientific_name"),
                    cached_common_name=row.get("cached_common_name"),
                    taxonomy_source=row.get("taxonomy_source") or "CatalogueOfLife-XR",
                    last_synced=imported_at,
                    creation_date=datetime.now(UTC),
                )
                session.add(taxon)
                existing_map[species_id] = taxon
                created = True

        if created:
            session.commit()
            for taxon in existing_map.values():
                if taxon.taxon_id is None:
                    session.refresh(taxon)

        for row in rows:
            species_id = row.get("col_species_id")
            taxon = existing_map.get(species_id) if species_id else None
            row["taxon_id"] = taxon.taxon_id if taxon else None
            row["creation_date"] = row.get("imported_at") or datetime.now(UTC)
            row["last_synced"] = row.get("imported_at")
        return rows

    def _ensure_remote_taxon_dictionary(self, session: Session) -> None:
        if self._use_direct_geo_lookup():
            try:
                self._fetch_geo_rows("SELECT 1 FROM public.col_xr_taxon_species LIMIT 1", {})
                return
            except Exception as exc:
                raise RemoteTaxonLookupError("XR taxon dictionary is unavailable", status_code=503) from exc

        if not self._remote_table_available(session):
            raise RemoteTaxonLookupError("XR taxon dictionary is unavailable", status_code=503)

    def _resolve_lowest_col_match(self, session: Session, lowest_col_id: str) -> dict[str, Any]:
        self._ensure_remote_taxon_dictionary(session)
        source_table = "col_xr_taxon_species" if self._use_direct_geo_lookup() else "geo_col_xr_taxon_species"
        sql = text(
            f"""
            SELECT *
            FROM (
                SELECT DISTINCT
                    'species' AS matched_rank,
                    col_species_id AS lowest_col_id,
                    cached_scientific_name AS lowest_name,
                    col_species_id,
                    col_class_id,
                    col_order_id,
                    col_family_id,
                    col_genus_id
                FROM {source_table}
                WHERE col_species_id = :lowest_col_id

                UNION ALL

                SELECT DISTINCT
                    'genus' AS matched_rank,
                    col_genus_id AS lowest_col_id,
                    col_genus_name AS lowest_name,
                    NULL AS col_species_id,
                    col_class_id,
                    col_order_id,
                    col_family_id,
                    col_genus_id
                FROM {source_table}
                WHERE col_genus_id = :lowest_col_id

                UNION ALL

                SELECT DISTINCT
                    'family' AS matched_rank,
                    col_family_id AS lowest_col_id,
                    col_family_name AS lowest_name,
                    NULL AS col_species_id,
                    col_class_id,
                    col_order_id,
                    col_family_id,
                    NULL AS col_genus_id
                FROM {source_table}
                WHERE col_family_id = :lowest_col_id

                UNION ALL

                SELECT DISTINCT
                    'order' AS matched_rank,
                    col_order_id AS lowest_col_id,
                    col_order_name AS lowest_name,
                    NULL AS col_species_id,
                    col_class_id,
                    col_order_id,
                    NULL AS col_family_id,
                    NULL AS col_genus_id
                FROM {source_table}
                WHERE col_order_id = :lowest_col_id

                UNION ALL

                SELECT DISTINCT
                    'class' AS matched_rank,
                    col_class_id AS lowest_col_id,
                    col_class_name AS lowest_name,
                    NULL AS col_species_id,
                    col_class_id,
                    NULL AS col_order_id,
                    NULL AS col_family_id,
                    NULL AS col_genus_id
                FROM {source_table}
                WHERE col_class_id = :lowest_col_id
            ) AS resolved
            """
        )
        if self._use_direct_geo_lookup():
            rows = self._fetch_geo_rows(str(sql), {"lowest_col_id": lowest_col_id})
        else:
            rows = [dict(row) for row in session.execute(sql, {"lowest_col_id": lowest_col_id}).mappings().all()]
        if not rows:
            raise RemoteTaxonLookupError(f"Unknown lowest_col_id: {lowest_col_id}", status_code=400)

        unique_rows = {
            (
                row["matched_rank"],
                row["lowest_col_id"],
                row["lowest_name"],
                row["col_species_id"],
                row["col_class_id"],
                row["col_order_id"],
                row["col_family_id"],
                row["col_genus_id"],
            )
            for row in rows
        }
        if len(unique_rows) != 1:
            raise RemoteTaxonLookupError(
                f"Ambiguous lowest_col_id in XR dictionary: {lowest_col_id}",
                status_code=400,
            )

        return dict(rows[0])

    def _build_taxon_values_from_lowest(self, session: Session, lowest_col_id: str) -> dict[str, Any]:
        resolved = self._resolve_lowest_col_match(session, lowest_col_id)
        return {
            "col_species_id": resolved.get("col_species_id"),
            "col_class_id": resolved.get("col_class_id"),
            "col_order_id": resolved.get("col_order_id"),
            "col_family_id": resolved.get("col_family_id"),
            "col_genus_id": resolved.get("col_genus_id"),
            "cached_scientific_name": resolved.get("lowest_name"),
        }

    def ensure_import_dictionary(self, session: Session) -> None:
        """Probe remote dictionary availability once per import instead of per row."""
        self._ensure_remote_taxon_dictionary(session)

    def prefetch_import_candidates(
        self,
        session: Session,
        binomials: set[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch all COL candidates for the given binomials in one grouped query.

        Returns a mapping of normalized binomial (lower/trim) to its candidate rows,
        replacing one remote lookup per CSV row with a single batched lookup.
        """
        grouped: dict[str, list[dict[str, Any]]] = {}
        keys = {value.strip().casefold() for value in binomials if value and value.strip()}
        if not keys:
            return grouped
        source_table = (
            "col_xr_taxon_species"
            if self._use_direct_geo_lookup()
            else "geo_col_xr_taxon_species"
        )
        rank_columns = {
            "species": "cached_scientific_name",
            "genus": "col_genus_name",
            "family": "col_family_name",
            "order": "col_order_name",
            "class": "col_class_name",
        }
        selects: list[str] = []
        for rank, name_column in rank_columns.items():
            included_ranks = {
                "species": {"species", "genus", "family", "order", "class"},
                "genus": {"genus", "family", "order", "class"},
                "family": {"family", "order", "class"},
                "order": {"order", "class"},
                "class": {"class"},
            }[rank]
            values = {
                "species": (
                    "col_species_id" if "species" in included_ranks else "NULL"
                ),
                "genus": "col_genus_id" if "genus" in included_ranks else "NULL",
                "family": "col_family_id" if "family" in included_ranks else "NULL",
                "order": "col_order_id" if "order" in included_ranks else "NULL",
                "class": "col_class_id" if "class" in included_ranks else "NULL",
            }
            names = {
                "genus": "col_genus_name" if "genus" in included_ranks else "NULL",
                "family": "col_family_name" if "family" in included_ranks else "NULL",
                "order": "col_order_name" if "order" in included_ranks else "NULL",
                "class": "col_class_name" if "class" in included_ranks else "NULL",
            }
            selects.append(
                f"""
                SELECT DISTINCT
                    '{rank}' AS matched_rank,
                    lower(trim({name_column})) AS matched_key,
                    {name_column} AS lowest_name,
                    {values['species']} AS col_species_id,
                    {values['genus']} AS col_genus_id,
                    {values['family']} AS col_family_id,
                    {values['order']} AS col_order_id,
                    {values['class']} AS col_class_id,
                    {names['genus']} AS col_genus_name,
                    {names['family']} AS col_family_name,
                    {names['order']} AS col_order_name,
                    {names['class']} AS col_class_name
                FROM {source_table}
                WHERE lower(trim({name_column})) IN :binomials
                """
            )
        stmt = text(" UNION ALL ".join(selects)).bindparams(
            bindparam("binomials", expanding=True)
        )
        use_geo = self._use_direct_geo_lookup()
        for batch in itertools.batched(sorted(keys), _IMPORT_IN_CLAUSE_BATCH):
            params = {"binomials": list(batch)}
            if use_geo:
                with _get_geo_engine().connect() as conn:
                    rows = [dict(row) for row in conn.execute(stmt, params).mappings().all()]
            else:
                rows = [dict(row) for row in session.execute(stmt, params).mappings().all()]
            for row in rows:
                grouped.setdefault(row["matched_key"], []).append(row)
        return grouped

    def match_import_taxon(
        self,
        row: TaxonImportRow,
        candidates_by_binomial: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Resolve a single import row to one unambiguous COL lineage from prefetched candidates."""
        candidates = candidates_by_binomial.get(row.binomial.strip().casefold(), [])
        if not candidates:
            raise RemoteTaxonLookupError(f"Unknown binomial: {row.binomial}")

        constraints = {
            "col_genus_name": row.genus,
            "col_family_name": row.family,
            "col_order_name": row.taxon_order,
            "col_class_name": row.taxon_class,
        }
        matching = [
            candidate
            for candidate in candidates
            if all(
                expected is None
                or (
                    candidate.get(field) is not None
                    and str(candidate[field]).strip().casefold()
                    == expected.casefold()
                )
                for field, expected in constraints.items()
            )
        ]
        if not matching:
            raise RemoteTaxonLookupError(
                f"Taxonomic hierarchy does not match binomial: {row.binomial}"
            )
        unique = {
            (
                candidate["matched_rank"],
                candidate.get("col_species_id"),
                candidate.get("col_genus_id"),
                candidate.get("col_family_id"),
                candidate.get("col_order_id"),
                candidate.get("col_class_id"),
                candidate["lowest_name"],
            ): candidate
            for candidate in matching
        }
        if len(unique) != 1:
            raise RemoteTaxonLookupError(f"Ambiguous binomial: {row.binomial}")
        candidate = next(iter(unique.values()))
        lowest_id = candidate[f"col_{candidate['matched_rank']}_id"]
        return {
            "col_species_id": candidate.get("col_species_id"),
            "col_genus_id": candidate.get("col_genus_id"),
            "col_family_id": candidate.get("col_family_id"),
            "col_order_id": candidate.get("col_order_id"),
            "col_class_id": candidate.get("col_class_id"),
            "cached_scientific_name": candidate["lowest_name"],
            "cached_common_name": row.common_name,
            "taxonomy_source": row.source,
            "lowest_col_id": lowest_id,
        }

    def create_imported_taxons(
        self,
        session: Session,
        rows: list[dict[str, Any]],
    ) -> None:
        try:
            session.add_all(
                [
                    Taxon(
                        **{
                            key: value
                            for key, value in row.items()
                            if key != "lowest_col_id"
                        }
                    )
                    for row in rows
                ]
            )
            session.commit()
        except Exception:
            session.rollback()
            raise

    def _extract_lowest_col_id(self, payload: dict[str, Any]) -> str:
        for field in ("col_species_id", "col_genus_id", "col_family_id", "col_order_id", "col_class_id"):
            value = payload.get(field)
            if value:
                return value
        raise RemoteTaxonLookupError(
            "One of col_species_id, col_genus_id, col_family_id, col_order_id, or col_class_id is required",
            status_code=400,
        )

    def get_hierarchy_options(
        self,
        session: Session,
        rank: TaxonRank,
        page: int = 1,
        page_size: int = 20,
        class_id: str | None = None,
        order_id: str | None = None,
        family_id: str | None = None,
        genus_id: str | None = None,
        q: str | None = None,
    ) -> tuple[list[dict[str, str]], int]:
        self._ensure_remote_taxon_dictionary(session)
        cache_key = ("taxon_options", rank, class_id, order_id, family_id, genus_id, q or "", page, page_size)
        cached = self._get_cached_option_page(cache_key)
        if cached is not None:
            return cached

        id_col, name_col = _RANK_COLUMN_MAP[rank]
        conditions = [f"{id_col} IS NOT NULL", f"{name_col} IS NOT NULL", f"{name_col} <> ''"]
        params: dict[str, Any] = {}

        if rank in {"order", "family", "genus", "species"} and class_id:
            params["class_id"] = class_id
            conditions.append("col_class_id = :class_id")
        if rank in {"family", "genus", "species"} and order_id:
            params["order_id"] = order_id
            conditions.append("col_order_id = :order_id")
        if rank in {"genus", "species"} and family_id:
            params["family_id"] = family_id
            conditions.append("col_family_id = :family_id")
        if rank == "species" and genus_id:
            params["genus_id"] = genus_id
            conditions.append("col_genus_id = :genus_id")
        if q:
            params["q"] = f"%{q}%"
            conditions.append(f"{name_col} ILIKE :q")

        where_sql = f"WHERE {' AND '.join(conditions)}"
        if self._use_direct_geo_lookup():
            total = self._fetch_geo_scalar(
                f"""
                SELECT COUNT(*)
                FROM (
                    SELECT DISTINCT {id_col}, {name_col}
                    FROM col_xr_taxon_species
                    {where_sql}
                ) AS options
                """,
                params,
            )
            data_params = dict(params)
            data_params["limit"] = page_size
            data_params["offset"] = (page - 1) * page_size
            rows = self._fetch_geo_rows(
                f"""
                SELECT DISTINCT {id_col} AS id, {name_col} AS name
                FROM col_xr_taxon_species
                {where_sql}
                ORDER BY name ASC, id ASC
                LIMIT :limit OFFSET :offset
                """,
                data_params,
            )
        else:
            total_sql = text(
                f"""
                SELECT COUNT(*)
                FROM (
                    SELECT DISTINCT {id_col}, {name_col}
                    FROM geo_col_xr_taxon_species
                    {where_sql}
                ) AS options
                """
            )
            total = int(session.execute(total_sql, params).scalar_one())
            data_params = dict(params)
            data_params["limit"] = page_size
            data_params["offset"] = (page - 1) * page_size
            data_sql = text(
                f"""
                SELECT DISTINCT {id_col} AS id, {name_col} AS name
                FROM geo_col_xr_taxon_species
                {where_sql}
                ORDER BY name ASC, id ASC
                LIMIT :limit OFFSET :offset
                """
            )
            rows = [dict(row) for row in session.execute(data_sql, data_params).mappings().all()]

        result = [{"id": row["id"], "name": row["name"]} for row in rows]
        self._set_cached_option_page(cache_key, result, total)
        return result, total

    def search(
        self,
        session: Session,
        q: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[Taxon] | list[dict[str, Any]]:
        if self._remote_table_available(session):
            try:
                remote_rows = self._rows_from_remote_search(
                    session=session,
                    q=q,
                    limit=limit,
                    offset=offset,
                )
                return self._bridge_local_taxon_ids(session=session, rows=remote_rows)
            except SQLAlchemyError:
                pass

        stmt = select(Taxon)
        if q:
            search_term = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Taxon.cached_scientific_name.ilike(search_term),
                    Taxon.cached_common_name.ilike(search_term),
                )
            )
        stmt = stmt.order_by(
            Taxon.cached_scientific_name,
            Taxon.taxon_id,
        ).offset(offset).limit(limit)
        return list(session.exec(stmt).all())

    def get_all_sound_classifications(self, session: Session) -> list[SoundClassification]:
        stmt = select(SoundClassification).order_by(
            SoundClassification.soundscape_component,
            SoundClassification.sound_type,
        )
        return list(session.exec(stmt).all())

    def get_taxon_sound_types(
        self,
        session: Session,
        taxon_class: str | None = None,
        taxon_order: str | None = None,
    ) -> list[TaxonSoundType]:
        stmt = select(TaxonSoundType).order_by(TaxonSoundType.name)
        if taxon_order:
            stmt = stmt.where(TaxonSoundType.taxon_order == taxon_order)
        elif taxon_class:
            stmt = stmt.where(TaxonSoundType.taxon_class == taxon_class)
        return list(session.exec(stmt).all())

    def _fetch_hierarchy_names(
        self,
        session: Session,
        ids_by_rank: dict[str, set[str]],
        name_filters: dict[str, str] | None = None,
    ) -> dict[str, dict[str, str]]:
        """Fetch canonical hierarchy names only for IDs used by local taxons."""
        maps = {rank: {} for rank in _HIERARCHY_RANKS}
        active_ranks = [rank for rank in _HIERARCHY_RANKS if ids_by_rank.get(rank)]
        if not active_ranks:
            return maps

        source_table = (
            "col_xr_taxon_species"
            if self._use_direct_geo_lookup()
            else "geo_col_xr_taxon_species"
        )
        params: dict[str, Any] = {}
        clauses: list[str] = []
        for rank in active_ranks:
            id_column = f"col_{rank}_id"
            name_column = _hierarchy_remote_name_column(rank)
            ids_key = f"{rank}_ids"
            params[ids_key] = sorted(ids_by_rank[rank])
            name_filter_sql = ""
            if name_filters and name_filters.get(rank):
                filter_key = f"{rank}_name_filter"
                params[filter_key] = f"%{name_filters[rank]}%"
                name_filter_sql = f"WHERE resolved.hierarchy_name ILIKE :{filter_key}"
            # id -> name is 1:1 in the taxonomy dictionary, so a per-id LIMIT 1 index
            # lookup returns the same name as MIN(name) while avoiding a full aggregate
            # scan over the large hierarchy classes (e.g. class/order with ~1M rows).
            clauses.append(
                f"""
                SELECT * FROM (
                    SELECT '{rank}' AS rank,
                           ids.hierarchy_id AS hierarchy_id,
                           lookup.hierarchy_name AS hierarchy_name
                    FROM unnest(CAST(:{ids_key} AS varchar[])) AS ids(hierarchy_id)
                    CROSS JOIN LATERAL (
                        SELECT {name_column} AS hierarchy_name
                        FROM {source_table}
                        WHERE {id_column} = ids.hierarchy_id
                          AND {name_column} IS NOT NULL
                        LIMIT 1
                    ) AS lookup
                ) AS resolved
                {name_filter_sql}
                """
            )

        sql = " UNION ALL ".join(clauses)
        try:
            if self._use_direct_geo_lookup():
                rows = self._fetch_geo_rows(sql, params)
            else:
                if not self._remote_table_available(session):
                    raise RemoteTaxonLookupError(
                        "XR taxon dictionary is unavailable", status_code=503
                    )
                rows = [
                    dict(row)
                    for row in session.execute(text(sql), params).mappings().all()
                ]
        except RemoteTaxonLookupError:
            raise
        except Exception as exc:
            if not self._use_direct_geo_lookup():
                session.rollback()
            raise RemoteTaxonLookupError(
                "XR taxon dictionary is unavailable", status_code=503
            ) from exc

        for row in rows:
            maps[row["rank"]][row["hierarchy_id"]] = row["hierarchy_name"]
        return maps

    def _distinct_hierarchy_ids(
        self,
        session: Session,
        stmt: Any,
        rank: str,
    ) -> set[str]:
        id_column = getattr(Taxon, f"col_{rank}_id")
        id_stmt = (
            stmt.with_only_columns(id_column)
            .where(id_column.is_not(None))
            .order_by(None)
            .distinct()
        )
        return {value for value in session.exec(id_stmt).all() if value}

    def _apply_hierarchy_name_filters(
        self,
        session: Session,
        stmt: Any,
        filters: dict[str, Any],
    ) -> Any:
        if any(filters.get(key) for key in _HIERARCHY_FILTER_KEYS):
            self._ensure_remote_taxon_dictionary(session)
        for key, rank in _HIERARCHY_KEY_TO_RANK.items():
            term = filters.get(key)
            if not term:
                continue
            local_ids = self._distinct_hierarchy_ids(session, stmt, rank)
            if not local_ids:
                return stmt.where(Taxon.taxon_id == -1)
            maps = self._fetch_hierarchy_names(
                session,
                {rank: local_ids},
                {rank: term},
            )
            matching_ids = set(maps[rank])
            if not matching_ids:
                return stmt.where(Taxon.taxon_id == -1)
            stmt = stmt.where(
                getattr(Taxon, f"col_{rank}_id").in_(matching_ids)
            )
        return stmt

    def _apply_list_ordering(
        self,
        stmt: Any,
        order_by: str,
        order_dir: str,
        hierarchy_maps: dict[str, dict[str, str]],
    ) -> Any:
        sort_fields = dict(_TAXON_SORT_FIELDS)
        if order_by in _HIERARCHY_SORT_KEYS:
            rank = _HIERARCHY_KEY_TO_RANK[order_by]
            rank_map = hierarchy_maps[rank]
            if rank_map:
                lookup = values(
                    column("hierarchy_id", String),
                    column("hierarchy_name", String),
                    name=f"{rank}_name_lookup",
                ).data(sorted(rank_map.items()))
                stmt = stmt.outerjoin(
                    lookup,
                    getattr(Taxon, f"col_{rank}_id") == lookup.c.hierarchy_id,
                )
                sort_fields[order_by] = lookup.c.hierarchy_name
            else:
                sort_fields[order_by] = literal(None)
        return apply_ordering(
            stmt,
            order_by,
            order_dir,
            sort_fields,
            Taxon.cached_scientific_name,
            Taxon.taxon_id,
        )

    def _hierarchy_maps_for_sort(
        self,
        session: Session,
        stmt: Any,
        order_by: str,
    ) -> dict[str, dict[str, str]]:
        maps = {rank: {} for rank in _HIERARCHY_RANKS}
        if order_by not in _HIERARCHY_SORT_KEYS:
            return maps
        self._ensure_remote_taxon_dictionary(session)
        rank = _HIERARCHY_KEY_TO_RANK[order_by]
        local_ids = self._distinct_hierarchy_ids(session, stmt, rank)
        return self._fetch_hierarchy_names(session, {rank: local_ids})

    def _enrich_taxons(
        self,
        session: Session,
        taxons: list[Taxon],
        preloaded_maps: dict[str, dict[str, str]] | None = None,
        complete_ranks: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        local_rows = [taxon.model_dump() for taxon in taxons]
        maps = {
            rank: dict((preloaded_maps or {}).get(rank, {}))
            for rank in _HIERARCHY_RANKS
        }
        complete_ranks = complete_ranks or set()
        ids_to_fetch = {
            rank: {
                value for row in local_rows if (value := row.get(f"col_{rank}_id"))
            }
            for rank in _HIERARCHY_RANKS
            if rank not in complete_ranks
        }
        try:
            fetched = self._fetch_hierarchy_names(session, ids_to_fetch)
        except RemoteTaxonLookupError:
            fetched = {rank: {} for rank in _HIERARCHY_RANKS}
        for rank in _HIERARCHY_RANKS:
            maps[rank].update(fetched.get(rank, {}))

        result: list[dict[str, Any]] = []
        for item in local_rows:
            enriched_names = {
                f"col_{rank}_name": maps[rank].get(item.get(f"col_{rank}_id"))
                for rank in _HIERARCHY_RANKS
            }
            if item.get("col_species_id") and not enriched_names.get("col_species_name"):
                enriched_names["col_species_name"] = item.get("cached_scientific_name")
            item.update(enriched_names)
            result.append(item)
        return result

    def _local_taxon_query(self, filters: dict[str, Any]) -> Any:
        stmt = apply_filters(select(Taxon), filters, _TAXON_FILTER_SPECS)
        if filters.get("q"):
            term = f"%{filters['q']}%"
            stmt = stmt.where(
                or_(
                    Taxon.cached_scientific_name.ilike(term),
                    Taxon.cached_common_name.ilike(term),
                )
            )
        return stmt

    def list_taxons(
        self,
        session: Session,
        page: int = 1,
        page_size: int = 20,
        filters: dict | None = None,
        order_by: str = "scientific_name",
        order_dir: str = "asc",
    ) -> tuple[list[Taxon] | list[dict[str, Any]], int]:
        filters = filters or {}
        base_stmt = self._local_taxon_query(filters)
        base_stmt = self._apply_hierarchy_name_filters(session, base_stmt, filters)
        total = session.exec(select(func.count()).select_from(base_stmt.subquery())).one()
        if total == 0:
            return [], 0
        hierarchy_maps = self._hierarchy_maps_for_sort(
            session, base_stmt, order_by
        )
        stmt = self._apply_list_ordering(
            base_stmt,
            order_by,
            order_dir,
            hierarchy_maps,
        )
        taxons = list(session.exec(apply_pagination(stmt, page, page_size)).all())
        sorted_rank = (
            {_HIERARCHY_KEY_TO_RANK[order_by]}
            if order_by in _HIERARCHY_SORT_KEYS
            else set()
        )
        return self._enrich_taxons(
            session,
            taxons,
            preloaded_maps=hierarchy_maps,
            complete_ranks=sorted_rank,
        ), total

    def export_taxons(
        self,
        session: Session,
        filters: dict | None = None,
        order_by: str = "scientific_name",
        order_dir: str = "asc",
    ) -> list[Taxon] | list[dict[str, Any]]:
        filters = filters or {}
        base_stmt = self._apply_hierarchy_name_filters(
            session,
            self._local_taxon_query(filters),
            filters,
        )
        hierarchy_maps = self._hierarchy_maps_for_sort(
            session, base_stmt, order_by
        )
        stmt = self._apply_list_ordering(
            base_stmt,
            order_by,
            order_dir,
            hierarchy_maps,
        )
        taxons = list(session.exec(stmt).all())
        sorted_rank = (
            {_HIERARCHY_KEY_TO_RANK[order_by]}
            if order_by in _HIERARCHY_SORT_KEYS
            else set()
        )
        return self._enrich_taxons(
            session,
            taxons,
            preloaded_maps=hierarchy_maps,
            complete_ranks=sorted_rank,
        )

    def get_by_id(self, session: Session, taxon_id: int) -> Taxon | None:
        return session.get(Taxon, taxon_id)

    def get_detail_by_id(
        self,
        session: Session,
        taxon_id: int,
    ) -> dict[str, Any] | None:
        taxon = self.get_by_id(session, taxon_id)
        if taxon is None:
            return None
        return self._enrich_taxons(session, [taxon])[0]

    def has_lowest_col_id(self, session: Session, lowest_col_id: str, exclude_id: int | None = None) -> bool:
        stored_lowest_id = case(
            (Taxon.col_species_id.is_not(None), Taxon.col_species_id),
            (Taxon.col_genus_id.is_not(None), Taxon.col_genus_id),
            (Taxon.col_family_id.is_not(None), Taxon.col_family_id),
            (Taxon.col_order_id.is_not(None), Taxon.col_order_id),
            (Taxon.col_class_id.is_not(None), Taxon.col_class_id),
            else_=None,
        )
        stmt = select(func.count()).select_from(Taxon).where(
            func.lower(stored_lowest_id) == lowest_col_id.casefold()
        )
        if exclude_id is not None:
            stmt = stmt.where(Taxon.taxon_id != exclude_id)
        return session.exec(stmt).one() > 0

    def get_existing_lowest_col_ids(self, session: Session, ids: set[str]) -> set[str]:
        """Return the subset of (casefolded) lowest COL ids already stored, in one query."""
        found: set[str] = set()
        normalized = {value.casefold() for value in ids}
        if not normalized:
            return found
        stored_lowest_id = case(
            (Taxon.col_species_id.is_not(None), Taxon.col_species_id),
            (Taxon.col_genus_id.is_not(None), Taxon.col_genus_id),
            (Taxon.col_family_id.is_not(None), Taxon.col_family_id),
            (Taxon.col_order_id.is_not(None), Taxon.col_order_id),
            (Taxon.col_class_id.is_not(None), Taxon.col_class_id),
            else_=None,
        )
        for batch in itertools.batched(sorted(normalized), _IMPORT_IN_CLAUSE_BATCH):
            stmt = select(func.lower(stored_lowest_id)).select_from(Taxon).where(
                func.lower(stored_lowest_id).in_(batch)
            )
            found.update(session.exec(stmt).all())
        return found

    def create(self, session: Session, data: TaxonCreate) -> Taxon:
        payload = data.model_dump()
        lowest_col_id = self._extract_lowest_col_id(payload)
        if self.has_lowest_col_id(session, lowest_col_id):
            raise RemoteTaxonLookupError("Taxon already exists", status_code=409)
        values = self._build_taxon_values_from_lowest(session, lowest_col_id)
        taxon = Taxon(
            **values,
            cached_common_name=data.cached_common_name,
            taxonomy_source=data.taxonomy_source or "CatalogueOfLife-XR",
        )
        session.add(taxon)
        session.commit()
        session.refresh(taxon)
        return taxon

    def update(self, session: Session, taxon: Taxon, data: TaxonUpdate) -> Taxon:
        changes = data.model_dump(exclude_unset=True)
        lowest_col_id = None
        for field in ("col_species_id", "col_genus_id", "col_family_id", "col_order_id", "col_class_id"):
            value = changes.pop(field, None)
            if value and lowest_col_id is None:
                lowest_col_id = value

        if lowest_col_id:
            if self.has_lowest_col_id(session, lowest_col_id, exclude_id=taxon.taxon_id):
                raise RemoteTaxonLookupError("Taxon already exists", status_code=409)
            for field, value in self._build_taxon_values_from_lowest(session, lowest_col_id).items():
                setattr(taxon, field, value)
        for field, value in changes.items():
            setattr(taxon, field, value)
        session.add(taxon)
        session.commit()
        session.refresh(taxon)
        return taxon

    def is_referenced(self, session: Session, taxon_id: int) -> bool:
        count = session.exec(
            select(func.count()).select_from(Annotation).where(Annotation.taxon_id == taxon_id)
        ).one()
        return count > 0

    def delete(self, session: Session, taxon: Taxon) -> None:
        session.delete(taxon)
        session.commit()


taxon_repository = TaxonRepository()
