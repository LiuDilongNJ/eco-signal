import time
from dataclasses import dataclass
from typing import Any, Literal, Optional

from sqlalchemy import case, false, func, literal, or_, text
from sqlalchemy.orm import aliased, selectinload
from sqlmodel import Session, select

from app.core.exceptions import AppValidationError
from app.models.media import Media, MediaCollection
from app.models.project import ProjectCollection
from app.models.site import IucnGet, Site, SiteCollection, SiteProject
from app.models.user import User
from app.repositories.base import BaseRepository
from app.repositories.collection_scope import resolve_project_collection_scope
from app.repositories.geo_repository import GeoDataUnavailableError, geo_repository
from app.repositories.permission_repository import permission_repository
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
)
from app.schemas.site import SiteCreate, SiteUpdate

# Declarative filter specs.
# Special filters (project/collection subqueries, PostGIS coordinate ranges,
# iho_id name-lookup) are handled manually in _apply_filters.
_FILTER_SPECS: list[FilterSpec] = [
    # Exact matches
    ("site_id",            Site.site_id,            FilterOp.EQ),
    ("uuid",               Site.uuid,               FilterOp.EQ),
    ("realm_id",           Site.realm_id,           FilterOp.EQ),
    ("biome_id",           Site.biome_id,           FilterOp.EQ),
    ("functional_type_id", Site.functional_type_id, FilterOp.EQ),
    ("creator_id",         Site.creator_id,         FilterOp.EQ),
    ("gadm0_gid",          Site.gadm0_gid,          FilterOp.EQ),
    ("gadm1_gid",          Site.gadm1_gid,          FilterOp.EQ),
    ("gadm2_gid",          Site.gadm2_gid,          FilterOp.EQ),
    # Fuzzy matches
    ("name",  Site.name,  FilterOp.LIKE),
    ("gadm0", Site.gadm0, FilterOp.LIKE),
    ("gadm1", Site.gadm1, FilterOp.LIKE),
    ("gadm2", Site.gadm2, FilterOp.LIKE),
    ("iho", Site.iho, FilterOp.LIKE),
    # Numeric ranges
    ("topography_m",       Site.topography_m,       FilterOp.RANGE),
    ("freshwater_depth_m", Site.freshwater_depth_m, FilterOp.RANGE),
    # Date range
    ("creation_date", Site.creation_date, FilterOp.DATE_RANGE),
]

_SORT_FIELDS: dict[str, Any] = {
    "site_id":            Site.site_id,
    "name":               Site.name,
    "topography_m":       Site.topography_m,
    "freshwater_depth_m": Site.freshwater_depth_m,
    "creator_id":         Site.creator_id,
    "creation_date":      Site.creation_date,
    "uuid":               Site.uuid,
    "latitude":           Site.latitude,
    "longitude":          Site.longitude,
    "iho":                Site.iho,
    "gadm0":              Site.gadm0,
    "gadm1":              Site.gadm1,
    "gadm2":              Site.gadm2,
    "realm_id":           Site.realm_id,
    "biome_id":           Site.biome_id,
    "functional_type_id": Site.functional_type_id,
    "creator_name":       None,  # Handled in _apply_ordering
    "realm_name":         None,  # Handled in _apply_ordering
    "biome_name":         None,  # Handled in _apply_ordering
    "functional_type_name": None, # Handled in _apply_ordering
}

_MAP_MARKERS_CACHE_TTL_SECONDS = 30.0
_MAP_MARKERS_CACHE: dict[tuple[Any, ...], tuple[float, list[dict[str, Any]]]] = {}


class SiteRepository(BaseRepository[Site, SiteCreate, SiteUpdate]):
    """Repository for Site entity operations."""

    def __init__(self):
        super().__init__(Site)

    # Geo lookup helpers

    @staticmethod
    def _normalize_text(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized if normalized else None

    @staticmethod
    def _select_source_from_coords(lon: Optional[float], lat: Optional[float]) -> bool:
        return lon is not None and lat is not None

    def _validate_geo_inputs(
        self,
        *,
        longitude: Optional[float],
        latitude: Optional[float],
        gadm0_gid: Optional[str],
        gadm1_gid: Optional[str],
        gadm2_gid: Optional[str],
        iho_id: Optional[int],
    ) -> None:
        has_manual = self._select_source_from_coords(longitude, latitude)
        has_iho = iho_id is not None
        has_gadm = gadm0_gid is not None

        if (longitude is None) != (latitude is None):
            raise AppValidationError("longitude and latitude must be provided together")
        if (gadm1_gid or gadm2_gid) and not gadm0_gid:
            raise AppValidationError("gadm0_gid is required when gadm1_gid or gadm2_gid is provided")
        if not any([has_manual, has_iho, has_gadm]):
            raise AppValidationError("At least one of coordinates, GADM, or IHO must be provided")

    def _lookup_iho_name_by_id(self, session: Session, iho_id: Optional[int]) -> Optional[str]:
        if iho_id is None:
            return None
        option = geo_repository.resolve_iho(session, iho_id)
        if option is None:
            raise AppValidationError(f"Invalid IHO id: {iho_id}")
        return option.name

    def _lookup_iho_id_by_name(self, session: Session, iho_name: Optional[str]) -> Optional[int]:
        if not iho_name:
            return None
        return geo_repository.resolve_iho_id_by_name(session, iho_name)

    def _resolve_adm_hierarchy_by_gids(
        self,
        session: Session,
        gadm0_gid: Optional[str],
        gadm1_gid: Optional[str],
        gadm2_gid: Optional[str],
    ) -> dict[str, Optional[str]]:
        """
        Resolve ADM_0/1/2 GID values to canonical names.

        Returns normalized cache fields:
        - gadm0/gadm1/gadm2
        - gadm0_gid/gadm1_gid/gadm2_gid
        """
        try:
            return geo_repository.resolve_gadm_hierarchy(session, gadm0_gid, gadm1_gid, gadm2_gid)
        except GeoDataUnavailableError:
            raise
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc

    def _set_location_iho_shape(self, session: Session, site_id: int, iho_id: int) -> None:
        geometry = geo_repository.geometry_ewkb(session, "iho", iho_id)
        if geometry is not None:
            session.execute(
                text("UPDATE site SET location_iho = ST_GeomFromEWKB(:geometry) WHERE site_id = :id"),
                {"geometry": geometry, "id": site_id},
            )
            return
        session.execute(
            text(
                """
                UPDATE site
                SET location_iho = (
                    SELECT ST_SimplifyPreserveTopology(d.geom, 0.01)
                    FROM iho_sea_area,
                         LATERAL ST_Dump(geometry) AS d(path, geom)
                    WHERE id = :iho_id
                    ORDER BY ST_Area(d.geom::geography) DESC
                    LIMIT 1
                )
                WHERE site_id = :id
                """
            ),
            {"iho_id": iho_id, "id": site_id},
        )

    @staticmethod
    def _has_map_geometry_clause():
        """A site is mappable when it has manual coordinates or stored geometry."""
        return or_(
            (Site.longitude.is_not(None) & Site.latitude.is_not(None)),
            Site.location.is_not(None),
            Site.location_iho.is_not(None),
        )

    def _clear_location_iho(self, session: Session, site_id: int) -> None:
        session.execute(
            text(
                """
                UPDATE site
                SET location_iho = NULL
                WHERE site_id = :id
                """
            ),
            {"id": site_id},
        )

    def _clear_location(self, session: Session, site_id: int) -> None:
        session.execute(
            text("UPDATE site SET location = NULL WHERE site_id = :id"),
            {"id": site_id},
        )

    def _set_location_from_adm(self, session: Session, site_id: int, adm_meta: dict[str, Optional[str]]) -> None:
        source: str | None = None
        identifier: str | None = None
        if adm_meta.get("gadm2_gid"):
            source, identifier = "gadm2", adm_meta["gadm2_gid"]
        elif adm_meta.get("gadm1_gid"):
            source, identifier = "gadm1", adm_meta["gadm1_gid"]
        elif adm_meta.get("gadm0_gid"):
            source, identifier = "gadm0", adm_meta["gadm0_gid"]
        if source and identifier:
            geometry = geo_repository.geometry_ewkb(session, source, identifier)  # type: ignore[arg-type]
            if geometry is not None:
                session.execute(
                    text("UPDATE site SET location = ST_GeomFromEWKB(:geometry) WHERE site_id = :id"),
                    {"geometry": geometry, "id": site_id},
                )
                return
        if adm_meta.get("gadm2_gid"):
            sql = """
                UPDATE site
                SET location = (
                    SELECT ST_SimplifyPreserveTopology(d.geom, 0.01)
                    FROM adm_2,
                         LATERAL ST_Dump(geometry) AS d(path, geom)
                    WHERE "GID_2" = :gid
                    ORDER BY ST_Area(d.geom::geography) DESC
                    LIMIT 1
                )
                WHERE site_id = :id
            """
            gid = adm_meta["gadm2_gid"]
        elif adm_meta.get("gadm1_gid"):
            sql = """
                UPDATE site
                SET location = (
                    SELECT ST_SimplifyPreserveTopology(d.geom, 0.01)
                    FROM adm_1,
                         LATERAL ST_Dump(geometry) AS d(path, geom)
                    WHERE "GID_1" = :gid
                    ORDER BY ST_Area(d.geom::geography) DESC
                    LIMIT 1
                )
                WHERE site_id = :id
            """
            gid = adm_meta["gadm1_gid"]
        elif adm_meta.get("gadm0_gid"):
            sql = """
                UPDATE site
                SET location = (
                    SELECT ST_SimplifyPreserveTopology(d.geom, 0.01)
                    FROM adm_0,
                         LATERAL ST_Dump(geometry) AS d(path, geom)
                    WHERE "GID_0" = :gid
                    ORDER BY ST_Area(d.geom::geography) DESC
                    LIMIT 1
                )
                WHERE site_id = :id
            """
            gid = adm_meta["gadm0_gid"]
        else:
            return
        session.execute(text(sql), {"gid": gid, "id": site_id})

    def resolve_analysis_coordinates(self, session: Session, site_id: int) -> tuple[Optional[float], Optional[float]]:
        """
        Resolve coordinates for AI analysis with priority:
        manual lon/lat > ST_PointOnSurface(location) > ST_PointOnSurface(location_iho) > None.
        """
        row = session.execute(
            text(
                """
                SELECT
                    COALESCE(longitude, ST_X(ST_PointOnSurface(location)), ST_X(ST_PointOnSurface(location_iho))),
                    COALESCE(latitude,  ST_Y(ST_PointOnSurface(location)), ST_Y(ST_PointOnSurface(location_iho)))
                FROM site
                WHERE site_id = :id
                """
            ),
            {"id": site_id},
        ).first()
        if not row:
            return None, None
        return row[0], row[1]

    def _sync_cached_coordinates(
        self, session: Session, site_id: int, *, longitude: Optional[float], latitude: Optional[float]
    ) -> None:
        """Write cached longitude/latitude exactly as provided by the user.

        Only stores coordinates when the user explicitly provides them.
        No automatic fallback from geometry centroids.
        """
        session.execute(
            text(
                """
                UPDATE site
                SET longitude = :lon, latitude = :lat
                WHERE site_id = :id
                """
            ),
            {"lon": longitude, "lat": latitude, "id": site_id},
        )


    def _apply_location_geometry(
        self,
        session: Session,
        site_id: int,
        *,
        longitude: Optional[float],
        latitude: Optional[float],
        iho_id: Optional[int],
        adm_meta: dict[str, Optional[str]],
    ) -> None:
        """Set location/location_iho geometry and write cached lon/lat columns.

        - location   : GADM polygon at the finest provided level (gadm2 > gadm1 > gadm0), or NULL
        - location_iho: IHO polygon, or NULL
        - longitude/latitude: manual coordinates, stored independently from geometries
        """
        has_gadm = adm_meta.get("gadm0_gid") is not None
        has_iho = iho_id is not None

        if has_gadm:
            self._set_location_from_adm(session, site_id, adm_meta)
        else:
            self._clear_location(session, site_id)

        if has_iho:
            self._set_location_iho_shape(session, site_id, iho_id)
        else:
            self._clear_location_iho(session, site_id)

        self._sync_cached_coordinates(session, site_id, longitude=longitude, latitude=latitude)

    # Create / Update with geometry & geo lookup

    def create_site(
        self,
        session: Session,
        *,
        data: SiteCreate,
        creator_id: int,
        commit: bool = True,
    ) -> Site:
        """Create a new Site record and resolve location source by geo selection rules."""
        gadm0_gid = self._normalize_text(data.gadm0_gid)
        gadm1_gid = self._normalize_text(data.gadm1_gid)
        gadm2_gid = self._normalize_text(data.gadm2_gid)
        longitude = data.longitude
        latitude = data.latitude
        iho_id = data.iho_id

        self._validate_geo_inputs(
            longitude=longitude,
            latitude=latitude,
            gadm0_gid=gadm0_gid,
            gadm1_gid=gadm1_gid,
            gadm2_gid=gadm2_gid,
            iho_id=iho_id,
        )

        iadm_meta = self._resolve_adm_hierarchy_by_gids(session, gadm0_gid, gadm1_gid, gadm2_gid)
        iho_name = self._lookup_iho_name_by_id(session, iho_id)

        site = Site(
            name=data.name,
            creator_id=creator_id,
            topography_m=data.topography_m,
            freshwater_depth_m=data.freshwater_depth_m,
            realm_id=data.realm_id,
            biome_id=data.biome_id,
            functional_type_id=data.functional_type_id,
            iho=iho_name,
            gadm0=iadm_meta["gadm0"],
            gadm1=iadm_meta["gadm1"],
            gadm2=iadm_meta["gadm2"],
            gadm0_gid=iadm_meta["gadm0_gid"],
            gadm1_gid=iadm_meta["gadm1_gid"],
            gadm2_gid=iadm_meta["gadm2_gid"],
        )
        session.add(site)
        session.flush()

        self._apply_location_geometry(
            session,
            site.site_id,
            longitude=longitude,
            latitude=latitude,
            iho_id=iho_id,
            adm_meta=iadm_meta,
        )
        if commit:
            session.commit()
        else:
            session.flush()
        session.refresh(site)
        return site

    def update_site(self, session: Session, *, db_obj: Site, data: SiteUpdate) -> Site:
        """Update a Site record and resolve location source by geo selection rules."""
        update_data = data.model_dump(exclude_unset=True)
        if "gadm0_gid" in update_data:
            update_data["gadm0_gid"] = self._normalize_text(update_data["gadm0_gid"])
        if "gadm1_gid" in update_data:
            update_data["gadm1_gid"] = self._normalize_text(update_data["gadm1_gid"])
        if "gadm2_gid" in update_data:
            update_data["gadm2_gid"] = self._normalize_text(update_data["gadm2_gid"])

        geo_keys = {"longitude", "latitude", "iho_id", "gadm0_gid", "gadm1_gid", "gadm2_gid"}
        geo_changed = any(k in update_data for k in geo_keys)

        longitude = update_data.get("longitude", db_obj.longitude)
        latitude = update_data.get("latitude", db_obj.latitude)
        gadm0_gid = update_data.get("gadm0_gid", db_obj.gadm0_gid)
        gadm1_gid = update_data.get("gadm1_gid", db_obj.gadm1_gid)
        gadm2_gid = update_data.get("gadm2_gid", db_obj.gadm2_gid)
        iho_id = update_data.get("iho_id") if "iho_id" in update_data else self._lookup_iho_id_by_name(session, db_obj.iho)

        if geo_changed:
            self._validate_geo_inputs(
                longitude=longitude,
                latitude=latitude,
                gadm0_gid=gadm0_gid,
                gadm1_gid=gadm1_gid,
                gadm2_gid=gadm2_gid,
                iho_id=iho_id,
            )
            iadm_meta = self._resolve_adm_hierarchy_by_gids(session, gadm0_gid, gadm1_gid, gadm2_gid)
            iho_name = self._lookup_iho_name_by_id(session, iho_id)
        else:
            iadm_meta = {
                "gadm0": db_obj.gadm0,
                "gadm1": db_obj.gadm1,
                "gadm2": db_obj.gadm2,
                "gadm0_gid": db_obj.gadm0_gid,
                "gadm1_gid": db_obj.gadm1_gid,
                "gadm2_gid": db_obj.gadm2_gid,
            }
            iho_name = db_obj.iho

        # Update scalar fields; skip iho_id (virtual) and lon/lat (always managed by _sync_cached_coordinates)
        _geo_computed = {"iho_id", "longitude", "latitude"}
        for key, value in update_data.items():
            if key in _geo_computed:
                continue
            setattr(db_obj, key, value)

        db_obj.iho = iho_name
        db_obj.gadm0 = iadm_meta["gadm0"]
        db_obj.gadm1 = iadm_meta["gadm1"]
        db_obj.gadm2 = iadm_meta["gadm2"]
        db_obj.gadm0_gid = iadm_meta["gadm0_gid"]
        db_obj.gadm1_gid = iadm_meta["gadm1_gid"]
        db_obj.gadm2_gid = iadm_meta["gadm2_gid"]

        if geo_changed:
            self._apply_location_geometry(
                session,
                db_obj.site_id,
                longitude=longitude,
                latitude=latitude,
                iho_id=iho_id,
                adm_meta={
                    "gadm0_gid": db_obj.gadm0_gid,
                    "gadm1_gid": db_obj.gadm1_gid,
                    "gadm2_gid": db_obj.gadm2_gid,
                },
            )

        session.add(db_obj)
        session.commit()
        session.refresh(db_obj)
        return db_obj

    # Collection binding

    def bind_to_collections(
        self,
        session: Session,
        *,
        site_id: int,
        collection_ids: list[int],
        commit: bool = True,
    ) -> None:
        """Bind a site to one or more collections (replaces existing bindings)."""
        # Remove existing bindings
        existing = session.exec(
            select(SiteCollection).where(SiteCollection.site_id == site_id)
        ).all()
        for sc in existing:
            session.delete(sc)

        # Insert new bindings
        for cid in collection_ids:
            session.add(SiteCollection(site_id=site_id, collection_id=cid))
        if commit:
            session.commit()
        else:
            session.flush()

    def bind_to_projects(
        self, session: Session, *, site_id: int, project_ids: list[int]
    ) -> None:
        """Bind a site to one or more projects (replaces existing bindings)."""
        existing = session.exec(
            select(SiteProject).where(SiteProject.site_id == site_id)
        ).all()
        for sp in existing:
            session.delete(sp)

        for pid in project_ids:
            session.add(SiteProject(site_id=site_id, project_id=pid))
        session.flush()

    def sync_collection_and_project_links(
        self,
        session: Session,
        *,
        site_ids: list[int],
        managed_collection_ids: set[int],
        requested_collection_ids: list[int],
        managed_project_ids: set[int],
        requested_project_ids: list[int],
    ) -> None:
        """Replace only the manageable site collection and project links in batch."""
        if managed_collection_ids:
            existing_collection_links = session.exec(
                select(SiteCollection).where(
                    SiteCollection.site_id.in_(site_ids),
                    SiteCollection.collection_id.in_(managed_collection_ids),
                )
            ).all()
            for link in existing_collection_links:
                session.delete(link)

        if managed_project_ids:
            existing_project_links = session.exec(
                select(SiteProject).where(
                    SiteProject.site_id.in_(site_ids),
                    SiteProject.project_id.in_(managed_project_ids),
                )
            ).all()
            for link in existing_project_links:
                session.delete(link)

        for site_id in site_ids:
            for collection_id in requested_collection_ids:
                session.add(SiteCollection(site_id=site_id, collection_id=collection_id))
            for project_id in requested_project_ids:
                session.add(SiteProject(site_id=site_id, project_id=project_id))

        session.flush()

    def add_project_linked_sites_to_collections(
        self,
        session: Session,
        *,
        project_id: int,
        collection_ids: list[int],
    ) -> None:
        """Ensure project-linked sites are available in newly-added project collections."""
        if not collection_ids:
            return

        linked_site_ids = list(
            session.exec(
                select(SiteProject.site_id).where(SiteProject.project_id == project_id)
            ).all()
        )
        if not linked_site_ids:
            return

        existing_pairs = set(
            session.exec(
                select(SiteCollection.site_id, SiteCollection.collection_id).where(
                    SiteCollection.site_id.in_(linked_site_ids),
                    SiteCollection.collection_id.in_(collection_ids),
                )
            ).all()
        )

        for site_id in linked_site_ids:
            for collection_id in collection_ids:
                if (site_id, collection_id) in existing_pairs:
                    continue
                session.add(SiteCollection(site_id=site_id, collection_id=collection_id))
        session.flush()

    # Filtering helpers

    def _apply_filters(self, session: Session, query, filters: dict):
        """Apply all supported filter conditions to a query."""
        scoped_collection_ids = filters.get("scoped_collection_ids")
        if scoped_collection_ids is not None:
            if not scoped_collection_ids:
                return query.where(false())
            query = query.where(
                Site.site_collections.any(
                    SiteCollection.collection_id.in_(scoped_collection_ids)
                )
            )
        elif filters.get("project_id"):
            query = query.where(
                Site.site_collections.any(
                    SiteCollection.collection_id.in_(
                        select(ProjectCollection.collection_id).where(
                            ProjectCollection.project_id == filters["project_id"]
                        )
                    )
                )
            )

        if filters.get("collection_id") and scoped_collection_ids is None:
            query = query.where(
                Site.site_collections.any(
                    SiteCollection.collection_id == filters["collection_id"]
                )
            )

        # PostGIS coordinate ranges: prefer cached columns with PostGIS fallback
        if filters.get("longitude_min") is not None:
            query = query.where(
                func.coalesce(Site.longitude, func.ST_X(func.ST_PointOnSurface(Site.location))) >= filters["longitude_min"]
            )
        if filters.get("longitude_max") is not None:
            query = query.where(
                func.coalesce(Site.longitude, func.ST_X(func.ST_PointOnSurface(Site.location))) <= filters["longitude_max"]
            )
        if filters.get("latitude_min") is not None:
            query = query.where(
                func.coalesce(Site.latitude, func.ST_Y(func.ST_PointOnSurface(Site.location))) >= filters["latitude_min"]
            )
        if filters.get("latitude_max") is not None:
            query = query.where(
                func.coalesce(Site.latitude, func.ST_Y(func.ST_PointOnSurface(Site.location))) <= filters["latitude_max"]
            )

        # iho_id requires a reverse-lookup to get the IHO name
        if filters.get("iho_id") is not None:
            name = self._lookup_iho_name_by_id(session, filters["iho_id"])
            query = query.where(Site.iho == name) if name else query.where(False)

        if filters.get("creator_name"):
            query = query.outerjoin(User, Site.creator_id == User.user_id)
            query = query.where(User.name.ilike(f"%{filters['creator_name']}%"))

        if filters.get("realm_name"):
            realm_alias = aliased(IucnGet)
            query = query.outerjoin(realm_alias, Site.realm).where(
                realm_alias.name.ilike(f"%{filters['realm_name']}%")
            )
        if filters.get("biome_name"):
            biome_alias = aliased(IucnGet)
            query = query.outerjoin(biome_alias, Site.biome).where(
                biome_alias.name.ilike(f"%{filters['biome_name']}%")
            )
        if filters.get("functional_type_name"):
            functional_type_alias = aliased(IucnGet)
            query = query.outerjoin(functional_type_alias, Site.functional_type).where(
                functional_type_alias.name.ilike(f"%{filters['functional_type_name']}%")
            )

        # Standard declarative filters
        query = apply_filters(query, filters, _FILTER_SPECS)
        return query

    def _apply_ordering(self, query, order_by: str, order_dir: str):
        """Apply ordering to a query."""
        if order_by in {"realm_name", "biome_name", "functional_type_name", "creator_name"}:
            from app.models.site import IucnGet

            if order_by == "realm_name":
                rel = Site.realm
            elif order_by == "biome_name":
                rel = Site.biome
            elif order_by == "functional_type_name":
                rel = Site.functional_type
            else:
                alias = aliased(User)
                query = query.outerjoin(alias, Site.creator_id == alias.user_id)
                col = alias.name
                desc = order_dir.lower() == "desc"
                return query.order_by(col.desc() if desc else col.asc()).order_by(Site.site_id.asc())

            alias = aliased(IucnGet)
            query = query.outerjoin(alias, rel)
            col = alias.name
            desc = order_dir.lower() == "desc"
            return query.order_by(col.desc() if desc else col.asc()).order_by(Site.site_id.asc())

        return apply_ordering(
            query, order_by, order_dir,
            _SORT_FIELDS, Site.site_id,
            tie_break_col=Site.site_id,
        )

    def _load_relations(self, query):
        """Eagerly load relationships needed for SitePublic serialization."""
        return (
            query
            .options(selectinload(Site.realm))
            .options(selectinload(Site.biome))
            .options(selectinload(Site.functional_type))
            .options(selectinload(Site.creator))
            .options(selectinload(Site.site_collections))
            .options(selectinload(Site.site_projects))
        )

    def _apply_visibility_scope(
        self,
        session: Session,
        query,
        filters: dict,
        *,
        visibility: Literal["all", "public", "accessible"],
        user_id: int | None = None,
    ):
        filters = dict(filters)
        # Callers may pre-resolve the scope once so list and count share it.
        if filters.get("scoped_collection_ids") is not None:
            return query, filters
        project_id = filters.get("project_id")
        collection_id = filters.get("collection_id")

        if project_id is None:
            return query, filters

        filters["scoped_collection_ids"] = resolve_project_collection_scope(
            session,
            project_id=project_id,
            collection_id=collection_id,
            user_id=None if visibility == "all" else user_id,
            resource_type="site",
            action="read",
            is_admin=visibility == "all",
        )
        return query, filters

    def _build_filtered_query(
        self,
        session: Session,
        *,
        filters: dict,
        visibility: Literal["all", "public", "accessible"] = "all",
        user_id: int | None = None,
        count: bool = False,
        skip: int = 0,
        limit: int | None = 100,
        order_by: str = "site_id",
        order_dir: str = "asc",
    ):
        query = (
            select(func.count(Site.site_id.distinct())).select_from(Site)
            if count
            else select(Site)
        )
        query, scoped_filters = self._apply_visibility_scope(
            session,
            query,
            filters,
            visibility=visibility,
            user_id=user_id,
        )
        query = self._apply_filters(session, query, scoped_filters)

        if count:
            return query

        query = self._apply_ordering(query, order_by, order_dir)
        query = self._load_relations(query)
        if limit is not None:
            query = query.offset(skip).limit(limit)
        elif skip:
            query = query.offset(skip)
        return query

    def list_filtered(
        self,
        session: Session,
        *,
        visibility: Literal["all", "public", "accessible"] = "all",
        user_id: int | None = None,
        skip: int = 0,
        limit: int | None = 100,
        order_by: str = "site_id",
        order_dir: str = "asc",
        **filters,
    ) -> list[Site]:
        query = self._build_filtered_query(
            session,
            filters=filters,
            visibility=visibility,
            user_id=user_id,
            skip=skip,
            limit=limit,
            order_by=order_by,
            order_dir=order_dir,
        )
        return list(session.exec(query).all())

    def count_filtered(
        self,
        session: Session,
        *,
        visibility: Literal["all", "public", "accessible"] = "all",
        user_id: int | None = None,
        **filters,
    ) -> int:
        query = self._build_filtered_query(
            session,
            filters=filters,
            visibility=visibility,
            user_id=user_id,
            count=True,
        )
        return session.exec(query).one()

    def get_options(
        self,
        session: Session,
        *,
        project_id: int | None = None,
        collection_id: int | None = None,
        name: str | None = None,
        visibility: Literal["all", "public", "accessible"] = "all",
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        query = select(Site.site_id, Site.name).distinct()
        query, scoped_filters = self._apply_visibility_scope(
            session,
            query,
            {
                "project_id": project_id,
                "collection_id": collection_id,
                "name": name,
            },
            visibility=visibility,
            user_id=user_id,
        )
        query = self._apply_filters(
            session,
            query,
            scoped_filters,
        )
        rows = session.exec(
            query.order_by(Site.name.asc(), Site.site_id.asc())
        ).all()
        return [{"site_id": row[0], "name": row[1] or ""} for row in rows]

    def _map_geometry_exprs(self, *, include_geojson: bool = True) -> dict[str, Any]:
        resolved = self._resolved_map_coordinate_exprs()
        location_center_lon = func.ST_X(func.ST_PointOnSurface(Site.location))
        location_center_lat = func.ST_Y(func.ST_PointOnSurface(Site.location))
        location_iho_center_lon = func.ST_X(func.ST_PointOnSurface(Site.location_iho))
        location_iho_center_lat = func.ST_Y(func.ST_PointOnSurface(Site.location_iho))

        location_json = (
            func.ST_AsGeoJSON(Site.location) if include_geojson else literal(None)
        )
        location_iho_json = (
            func.ST_AsGeoJSON(Site.location_iho) if include_geojson else literal(None)
        )

        return {
            "location_json": location_json,
            "location_center_lon": location_center_lon,
            "location_center_lat": location_center_lat,
            "location_iho_json": location_iho_json,
            "location_iho_center_lon": location_iho_center_lon,
            "location_iho_center_lat": location_iho_center_lat,
            "resolved_lon": resolved["resolved_lon"],
            "resolved_lat": resolved["resolved_lat"],
        }

    @staticmethod
    def _resolved_map_coordinate_exprs() -> dict[str, Any]:
        location_center_lon = func.ST_X(func.ST_PointOnSurface(Site.location))
        location_center_lat = func.ST_Y(func.ST_PointOnSurface(Site.location))
        location_iho_center_lon = func.ST_X(func.ST_PointOnSurface(Site.location_iho))
        location_iho_center_lat = func.ST_Y(func.ST_PointOnSurface(Site.location_iho))
        return {
            "resolved_lon": func.coalesce(
                Site.longitude,
                location_center_lon,
                location_iho_center_lon,
            ),
            "resolved_lat": func.coalesce(
                Site.latitude,
                location_center_lat,
                location_iho_center_lat,
            ),
        }

    def _media_count_subquery(self, collection_ids: list[int], media_type: str = "all"):
        collection_match = (
            select(literal(1))
            .select_from(MediaCollection)
            .where(MediaCollection.media_id == Media.media_id)
            .where(MediaCollection.collection_id.in_(collection_ids))
            .exists()
        )
        query = (
            select(
                Media.site_id.label("site_id"),
                func.count(Media.media_id).label("media_count"),
            )
            .where(Media.site_id.is_not(None))
            .where(collection_match)
        )
        if media_type != "all":
            query = query.where(Media.media_type == media_type)
        return query.group_by(Media.site_id).subquery()

    @dataclass(frozen=True)
    class _MapScopes:
        visible_collection_ids: list[int]
        media_collection_ids: list[int]
        use_project_site_scope: bool

    def _resolve_map_scopes(
        self,
        session: Session,
        *,
        project_id: int,
        collection_id: int | None,
        user_id: int | None,
        is_admin: bool,
    ) -> _MapScopes:
        """Resolve site visibility scope and audio counting scope for the map."""
        project_collection_ids = list(
            session.exec(
                select(ProjectCollection.collection_id).where(
                    ProjectCollection.project_id == project_id
                )
            ).all()
        )
        if not project_collection_ids:
            return self._MapScopes(
                visible_collection_ids=[],
                media_collection_ids=[],
                use_project_site_scope=False,
            )

        project_collection_set = set(project_collection_ids)
        full_project_collection_set = set(project_collection_ids)
        if collection_id is not None:
            if collection_id not in project_collection_set:
                return self._MapScopes(
                    visible_collection_ids=[],
                    media_collection_ids=[],
                    use_project_site_scope=False,
                )
            project_collection_set = {collection_id}

        has_project_site_scope = collection_id is None and session.exec(
            select(literal(1))
            .select_from(SiteProject)
            .where(SiteProject.project_id == project_id)
            .limit(1)
        ).first() is not None

        if is_admin:
            scoped_ids = sorted(project_collection_set)
            return self._MapScopes(
                visible_collection_ids=scoped_ids,
                media_collection_ids=scoped_ids,
                use_project_site_scope=(
                    collection_id is None
                    and has_project_site_scope
                    and project_collection_set == full_project_collection_set
                ),
            )

        public_collection_ids = {
            candidate_collection_id
            for _, candidate_collection_id in permission_repository.get_public_collection_scopes(
                session,
                project_id=project_id,
            )
        }

        def _resolve_ids(resource_type: str) -> list[int]:
            allowed_ids: set[int] = set()
            if user_id is not None:
                allowed_ids.update(
                    permission_repository.get_accessible_project_collection_ids(
                        session,
                        user_id,
                        project_id=project_id,
                        resource_type=resource_type,
                        action="read",
                    )
                )
            allowed_ids.update(public_collection_ids)
            return sorted(project_collection_set & allowed_ids)

        visible_collection_ids = _resolve_ids("site")
        if not visible_collection_ids:
            return self._MapScopes(
                visible_collection_ids=[],
                media_collection_ids=[],
                use_project_site_scope=False,
            )

        media_collection_ids = _resolve_ids("audio")
        use_project_site_scope = (
            collection_id is None
            and has_project_site_scope
            and set(visible_collection_ids) == full_project_collection_set
        )
        return self._MapScopes(
            visible_collection_ids=visible_collection_ids,
            media_collection_ids=media_collection_ids,
            use_project_site_scope=use_project_site_scope,
        )

    @staticmethod
    def _apply_map_filters(
        query,
        *,
        realm_id: int | None,
        biome_id: int | None,
        functional_type_id: int | None,
    ):
        """Apply IUCN filters to the map query."""
        for column, value in (
            (Site.realm_id, realm_id),
            (Site.biome_id, biome_id),
            (Site.functional_type_id, functional_type_id),
        ):
            if value is not None:
                query = query.where(column.is_(None) if value == 0 else column == value)
        return query

    def _build_map_marker_query_light(
        self,
        *,
        project_id: int,
        visible_collection_ids: list[int],
        media_count_subquery,
        coord: dict[str, Any],
        realm,
        use_project_site_scope: bool,
    ):
        base_columns = [
            Site.site_id.label("site_id"),
            Site.name.label("name"),
            coord["resolved_lat"].label("latitude"),
            coord["resolved_lon"].label("longitude"),
            case(
                ((Site.longitude.is_not(None) & Site.latitude.is_not(None)), literal("coordinates")),
                (Site.location.is_not(None), literal("gadm")),
                (Site.location_iho.is_not(None), literal("iho")),
                else_=literal(None),
            ).label("point_source"),
            Site.realm_id.label("realm_id"),
            realm.name.label("realm_name"),
            Site.biome_id.label("biome_id"),
            Site.functional_type_id.label("functional_type_id"),
            func.coalesce(media_count_subquery.c.media_count, 0).label("media_count"),
        ]
        if use_project_site_scope:
            return (
                select(*base_columns)
                .select_from(SiteProject)
                .join(Site, Site.site_id == SiteProject.site_id)
                .join(media_count_subquery, media_count_subquery.c.site_id == Site.site_id)
                .outerjoin(realm, realm.iucn_get_id == Site.realm_id)
                .where(SiteProject.project_id == project_id)
                .where(self._has_map_geometry_clause())
            )

        visibility_exists = (
            select(literal(1))
            .select_from(SiteCollection)
            .where(SiteCollection.site_id == Site.site_id)
            .where(SiteCollection.collection_id.in_(visible_collection_ids))
            .exists()
        )
        return (
            select(*base_columns)
            .join(media_count_subquery, media_count_subquery.c.site_id == Site.site_id)
            .outerjoin(realm, realm.iucn_get_id == Site.realm_id)
            .where(visibility_exists)
            .where(self._has_map_geometry_clause())
        )

    def _map_row_to_dict(self, row) -> dict[str, Any]:
        data = dict(row._mapping)
        data["media_count"] = int(data["media_count"] or 0)
        if "collection_ids" in data:
            data["collection_ids"] = sorted(
                int(collection_id)
                for collection_id in (data["collection_ids"] or [])
                if collection_id is not None
            )
        return data

    def get_map_markers(
        self,
        session: Session,
        *,
        project_id: int,
        user_id: Optional[int] = None,
        is_admin: bool = False,
        collection_id: Optional[int] = None,
        realm_id: Optional[int] = None,
        biome_id: Optional[int] = None,
        functional_type_id: Optional[int] = None,
        media_type: str = "all",
    ) -> list[dict[str, Any]]:
        """Get lightweight site markers for project map with media counts."""
        scopes = self._resolve_map_scopes(
            session,
            project_id=project_id,
            collection_id=collection_id,
            user_id=user_id,
            is_admin=is_admin,
        )
        if not scopes.visible_collection_ids:
            return []
        if not scopes.media_collection_ids:
            return []

        cache_key = (
            project_id,
            collection_id,
            realm_id,
            biome_id,
            functional_type_id,
            media_type,
            tuple(scopes.visible_collection_ids),
            tuple(scopes.media_collection_ids),
            scopes.use_project_site_scope,
        )
        now = time.monotonic()
        cached_entry = _MAP_MARKERS_CACHE.get(cache_key)
        if cached_entry and cached_entry[0] > now:
            return [marker.copy() for marker in cached_entry[1]]
        if cached_entry and cached_entry[0] <= now:
            _MAP_MARKERS_CACHE.pop(cache_key, None)

        realm = aliased(IucnGet)
        media_count_subquery = self._media_count_subquery(scopes.media_collection_ids, media_type=media_type)
        query = self._build_map_marker_query_light(
            project_id=project_id,
            visible_collection_ids=scopes.visible_collection_ids,
            media_count_subquery=media_count_subquery,
            coord=self._resolved_map_coordinate_exprs(),
            realm=realm,
            use_project_site_scope=scopes.use_project_site_scope,
        )
        query = self._apply_map_filters(
            query,
            realm_id=realm_id,
            biome_id=biome_id,
            functional_type_id=functional_type_id,
        )
        rows = session.exec(query.order_by(Site.site_id.asc())).all()
        markers = [self._map_row_to_dict(row) for row in rows]
        _MAP_MARKERS_CACHE[cache_key] = (
            now + _MAP_MARKERS_CACHE_TTL_SECONDS,
            markers,
        )
        return [marker.copy() for marker in markers]

    def get_visible_iucn_usage(
        self,
        session: Session,
        *,
        project_id: int,
        user_id: Optional[int] = None,
        is_admin: bool = False,
        collection_id: Optional[int] = None,
    ) -> list[tuple[int | None, int | None, int | None]]:
        """Return distinct IUCN usage tuples for sites visible in the map scope."""
        scopes = self._resolve_map_scopes(
            session,
            project_id=project_id,
            collection_id=collection_id,
            user_id=user_id,
            is_admin=is_admin,
        )
        if not scopes.visible_collection_ids:
            return []
        if not scopes.media_collection_ids:
            return []

        media_count_subquery = self._media_count_subquery(scopes.media_collection_ids)

        if scopes.use_project_site_scope:
            query = (
                select(
                    Site.realm_id,
                    Site.biome_id,
                    Site.functional_type_id,
                )
                .distinct()
                .select_from(SiteProject)
                .join(Site, Site.site_id == SiteProject.site_id)
                .join(media_count_subquery, media_count_subquery.c.site_id == Site.site_id)
                .where(SiteProject.project_id == project_id)
                .where(self._has_map_geometry_clause())
            )
        else:
            visibility_exists = (
                select(literal(1))
                .select_from(SiteCollection)
                .where(SiteCollection.site_id == Site.site_id)
                .where(SiteCollection.collection_id.in_(scopes.visible_collection_ids))
                .exists()
            )
            query = (
                select(
                    Site.realm_id,
                    Site.biome_id,
                    Site.functional_type_id,
                )
                .distinct()
                .select_from(Site)
                .join(media_count_subquery, media_count_subquery.c.site_id == Site.site_id)
                .where(visibility_exists)
                .where(self._has_map_geometry_clause())
            )

        rows = session.exec(query).all()
        return [
            (row[0], row[1], row[2])
            for row in rows
        ]

    def get_map_geometries(
        self,
        session: Session,
        *,
        project_id: int,
        site_ids: list[int],
        user_id: Optional[int] = None,
        is_admin: bool = False,
        collection_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Get geometry payload for selected site IDs within current visibility scope."""
        if not site_ids:
            return []
        scopes = self._resolve_map_scopes(
            session,
            project_id=project_id,
            collection_id=collection_id,
            user_id=user_id,
            is_admin=is_admin,
        )
        if not scopes.visible_collection_ids:
            return []

        geo = self._map_geometry_exprs(include_geojson=True)
        query = (
            select(
                Site.site_id.label("site_id"),
                Site.longitude.label("raw_longitude"),
                Site.latitude.label("raw_latitude"),
                geo["location_json"].label("location_json"),
                geo["location_center_lon"].label("location_center_lon"),
                geo["location_center_lat"].label("location_center_lat"),
                geo["location_iho_json"].label("location_iho_json"),
                geo["location_iho_center_lon"].label("location_iho_center_lon"),
                geo["location_iho_center_lat"].label("location_iho_center_lat"),
            )
            .join(SiteCollection, SiteCollection.site_id == Site.site_id)
            .where(SiteCollection.collection_id.in_(scopes.visible_collection_ids))
            .where(Site.site_id.in_(site_ids))
            .where(self._has_map_geometry_clause())
            .group_by(
                Site.site_id,
                Site.longitude,
                Site.latitude,
                geo["location_json"],
                geo["location_center_lon"],
                geo["location_center_lat"],
                geo["location_iho_json"],
                geo["location_iho_center_lon"],
                geo["location_iho_center_lat"],
            )
            .order_by(Site.site_id.asc())
        )
        rows = session.exec(query).all()
        return [dict(row._mapping) for row in rows]

    def get_site_with_relations(self, session: Session, site_id: int) -> Optional[Site]:
        """Get a single site with all relationships loaded."""
        query = select(Site).where(Site.site_id == site_id)
        query = self._load_relations(query)
        return session.exec(query).first()


# Singleton instance
site_repository = SiteRepository()
