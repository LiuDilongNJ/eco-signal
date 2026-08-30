import json
from typing import Literal

from fastapi import HTTPException
from sqlmodel import Session, delete, select

from app.csv_export import CsvColumn, export_columns_csv
from app.models.collection import Collection
from app.models.media import Media
from app.models.project import Project, ProjectCollection
from app.models.site import IucnGet, Site, SiteCollection, SiteProject
from app.models.user import User
from app.repositories import permission_repository, project_repository
from app.repositories.collection_scope import resolve_project_collection_scope
from app.repositories.site_repository import site_repository
from app.schemas.device import SiteOption
from app.schemas.response import PagedApiResponse, api_page
from app.schemas.site import (
    IucnGetOption,
    IucnGetOptionsResponse,
    SiteCreate,
    SiteLinkOptionsResponse,
    SiteMapGeometryItem,
    SiteMapGeometryResponse,
    SiteMapLightGeometry,
    SiteMapLightMarker,
    SiteMapLightPoint,
    SitePublic,
    SiteUpdate,
)
from app.services import permission_service

_SITE_EXPORT_COLUMNS = [
    CsvColumn("site_id"), CsvColumn("uuid"), CsvColumn("name"),
    CsvColumn("latitude"), CsvColumn("longitude"), CsvColumn("topography_m"),
    CsvColumn("freshwater_depth_m"), CsvColumn("gadm0"),
    CsvColumn("gadm1"), CsvColumn("gadm2"), CsvColumn("iho"),
    CsvColumn("realm_name"), CsvColumn("biome_name"),
    CsvColumn("functional_type_name"), CsvColumn("creator_name"),
    CsvColumn("creator_id"), CsvColumn("creation_date"),
]

def _resolve_iucn_ids(
    session: Session,
    realm_id: int | None,
    biome_id: int | None,
    functional_type_id: int | None,
) -> tuple[int | None, int | None, int | None]:
    """Resolve IUCN GET IDs by lowest-level priority.

    The deepest level provided drives the final values; parent IDs are derived
    automatically from the iucn_get hierarchy, so inconsistent caller-supplied
    higher-level IDs are ignored.

    Priority: functional_type_id (level 3) > biome_id (level 2) > realm_id (level 1)

    Returns (realm_id, biome_id, functional_type_id).
    """
    if functional_type_id is not None:
        ft = session.exec(select(IucnGet).where(IucnGet.iucn_get_id == functional_type_id)).first()
        if ft is None or ft.level != 3:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid functional_type_id: {functional_type_id} does not exist or is not a Functional Type (level 3)",
            )
        biome = session.exec(select(IucnGet).where(IucnGet.iucn_get_id == ft.pid)).first()
        if biome is None:
            raise HTTPException(
                status_code=422,
                detail=f"Data error: functional_type {functional_type_id} has no parent biome",
            )
        realm = session.exec(select(IucnGet).where(IucnGet.iucn_get_id == biome.pid)).first()
        if realm is None:
            raise HTTPException(
                status_code=422,
                detail=f"Data error: biome {biome.iucn_get_id} has no parent realm",
            )
        return realm.iucn_get_id, biome.iucn_get_id, functional_type_id

    if biome_id is not None:
        biome = session.exec(select(IucnGet).where(IucnGet.iucn_get_id == biome_id)).first()
        if biome is None or biome.level != 2:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid biome_id: {biome_id} does not exist or is not a Biome (level 2)",
            )
        realm = session.exec(select(IucnGet).where(IucnGet.iucn_get_id == biome.pid)).first()
        if realm is None:
            raise HTTPException(
                status_code=422,
                detail=f"Data error: biome {biome_id} has no parent realm",
            )
        return realm.iucn_get_id, biome_id, None

    if realm_id is not None:
        realm = session.exec(select(IucnGet).where(IucnGet.iucn_get_id == realm_id)).first()
        if realm is None or realm.level != 1:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid realm_id: {realm_id} does not exist or is not a Realm (level 1)",
            )
        return realm_id, None, None

    return None, None, None


def _build_site_public(site: Site) -> SitePublic:
    """Convert a Site ORM object to SitePublic schema."""
    longitude = site.longitude
    latitude = site.latitude

    collection_ids = [sc.collection_id for sc in (site.site_collections or [])]

    realm_name = site.realm.name if site.realm else None
    biome_name = site.biome.name if site.biome else None
    functional_type_name = site.functional_type.name if site.functional_type else None

    return SitePublic(
        site_id=site.site_id,
        uuid=site.uuid,
        name=site.name,
        longitude=longitude,
        latitude=latitude,
        iho_longitude=None,
        iho_latitude=None,
        topography_m=site.topography_m,
        freshwater_depth_m=site.freshwater_depth_m,
        realm_id=site.realm_id,
        realm_name=realm_name,
        biome_id=site.biome_id,
        biome_name=biome_name,
        functional_type_id=site.functional_type_id,
        functional_type_name=functional_type_name,
        iho=site.iho,
        gadm0=site.gadm0,
        gadm1=site.gadm1,
        gadm2=site.gadm2,
        gadm0_gid=site.gadm0_gid,
        gadm1_gid=site.gadm1_gid,
        gadm2_gid=site.gadm2_gid,
        creator_id=site.creator_id,
        creator_name=site.creator.name if site.creator else None,
        creation_date=site.creation_date,
        collection_ids=collection_ids,
    )


def _site_visibility(user: User | None) -> tuple[Literal["all", "public", "accessible"], int | None]:
    if user is None:
        return "public", None
    if permission_service.is_admin(user):
        return "all", None
    return "accessible", user.user_id


def _query_visible_sites(
    session: Session,
    user: User | None,
    *,
    filters: dict,
    page: int = 1,
    page_size: int | None = 20,
    order_by: str = "site_id",
    order_dir: str = "asc",
    include_total: bool = True,
) -> tuple[list[Site], int]:
    visibility, user_id = _site_visibility(user)
    skip = (page - 1) * page_size if page_size is not None else 0

    # Resolve the permission scope once so the list and count queries share it.
    filters = dict(filters)
    project_id = filters.get("project_id")
    if project_id is not None and filters.get("scoped_collection_ids") is None:
        filters["scoped_collection_ids"] = resolve_project_collection_scope(
            session,
            project_id=project_id,
            collection_id=filters.get("collection_id"),
            user_id=None if visibility == "all" else user_id,
            resource_type="site",
            action="read",
            is_admin=visibility == "all",
        )

    records = site_repository.list_filtered(
        session,
        visibility=visibility,
        user_id=user_id,
        skip=skip,
        limit=page_size,
        order_by=order_by,
        order_dir=order_dir,
        **filters,
    )
    total = (
        site_repository.count_filtered(
            session,
            visibility=visibility,
            user_id=user_id,
            **filters,
        )
        if include_total
        else len(records)
    )
    return records, total


def _first_project_id_for_collection(session: Session, collection_id: int) -> int | None:
    return session.exec(
        select(ProjectCollection.project_id)
        .where(ProjectCollection.collection_id == collection_id)
        .order_by(ProjectCollection.project_id)
    ).first()


def _resolve_site_project_id(session: Session, site: Site) -> int | None:
    collection_ids = [sc.collection_id for sc in (site.site_collections or [])]
    if not collection_ids:
        return None
    return session.exec(
        select(ProjectCollection.project_id)
        .where(ProjectCollection.collection_id.in_(collection_ids))
        .order_by(ProjectCollection.project_id)
    ).first()


def create_site(
    session: Session,
    data: SiteCreate,
    current_user: User,
    *,
    commit: bool = True,
) -> SitePublic:
    """Create a new site and bind it to collections.

    If collection_id is provided, binds to that single collection.
    If only project_id is provided, binds to ALL collections under that project.

    Permission: requires site:write on the target collection path.
    """
    data, collection_ids, requested_project_ids = validate_site_create(session, data, current_user)

    site = site_repository.create_site(session, data=data, creator_id=current_user.user_id, commit=False)
    site_repository.bind_to_collections(session, site_id=site.site_id, collection_ids=collection_ids, commit=False)
    if requested_project_ids:
        site_repository.bind_to_projects(session, site_id=site.site_id, project_ids=requested_project_ids)
    if commit:
        session.commit()
    else:
        session.flush()
    site = site_repository.get_site_with_relations(session, site.site_id)
    return _build_site_public(site)


def validate_site_create(session: Session, data: SiteCreate, current_user: User) -> tuple[SiteCreate, list[int], list[int]]:
    """Validate and normalize a site creation without persisting it."""
    data = data.model_copy(deep=True)
    requested_project_ids: list[int] = []
    if data.collection_id:
        if data.project_id is None:
            data.project_id = _first_project_id_for_collection(session, data.collection_id)
        if data.project_id is None:
            raise HTTPException(status_code=400, detail="Missing required parameter: project_id")
        # Verify permission on this specific collection
        if not permission_service.has_resource_permission(
            session, current_user, resource_type="site", action="write",
            project_id=data.project_id,
            collection_id=data.collection_id,
        ):
            raise HTTPException(status_code=403, detail="No site:write permission on the target collection")
        collection_ids = [data.collection_id]
    else:
        # project_id only — bind to all collections in that project
        collection_ids = list(
            session.exec(
                select(ProjectCollection.collection_id).where(
                    ProjectCollection.project_id == data.project_id
                )
            ).all()
        )
        if not collection_ids:
            raise HTTPException(status_code=404, detail="Project has no collections")
        disallowed_collection_ids = [
            collection_id
            for collection_id in collection_ids
            if not permission_service.has_resource_permission(
                session,
                current_user,
                resource_type="site",
                action="write",
                project_id=data.project_id,
                collection_id=collection_id,
            )
        ]
        if disallowed_collection_ids:
            raise HTTPException(
                status_code=403,
                detail=f"No site:write permission on collection(s): {disallowed_collection_ids}",
            )
        requested_project_ids = [data.project_id]

    data.realm_id, data.biome_id, data.functional_type_id = _resolve_iucn_ids(
        session, data.realm_id, data.biome_id, data.functional_type_id
    )
    return data, collection_ids, requested_project_ids


def list_sites(
    session: Session,
    current_user: User,
    *,
    page: int = 1,
    page_size: int = 20,
    order_by: str = "site_id",
    order_dir: str = "asc",
    **filters,
) -> PagedApiResponse:
    """Get a paginated list of sites."""
    items, total = _query_visible_sites(
        session,
        current_user,
        filters=filters,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
    )
    site_list = [_build_site_public(s) for s in items]
    return api_page(data=site_list, total=total, page=page, page_size=page_size)


def get_site_options(
    session: Session,
    user: User | None = None,
    *,
    project_id: int | None = None,
    collection_id: int | None = None,
    name: str | None = None,
) -> list[SiteOption]:
    if collection_id is not None and project_id is not None:
        permission_service.resolve_collection_project_id(
            session,
            collection_id,
            project_id,
        )

    visibility, user_id = _site_visibility(user)
    rows = site_repository.get_options(
        session,
        project_id=project_id,
        collection_id=collection_id,
        name=name,
        visibility=visibility,
        user_id=user_id,
    )
    return [SiteOption(**row) for row in rows]


def _parse_geojson(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None


def _build_marker_geometry(row: dict, *, include_polygons: bool = True) -> dict:
    """Build the geometry dict for map markers."""
    marker_lon = row.get("raw_longitude", row.get("longitude"))
    marker_lat = row.get("raw_latitude", row.get("latitude"))
    has_point = marker_lon is not None and marker_lat is not None
    point = (
        {"latitude": marker_lat, "longitude": marker_lon}
        if has_point
        else None
    )

    if not include_polygons:
        return {"point": point}

    loc_geojson = _parse_geojson(row.get("location_json"))
    location = (
        {
            "coordinates": loc_geojson.get("coordinates"),
            "center": {
                "latitude": row["location_center_lat"],
                "longitude": row["location_center_lon"],
            },
        }
        if loc_geojson is not None
        else None
    )

    iho_geojson = _parse_geojson(row.get("location_iho_json"))
    location_iho = (
        {
            "coordinates": iho_geojson.get("coordinates"),
            "center": {
                "latitude": row["location_iho_center_lat"],
                "longitude": row["location_iho_center_lon"],
            },
        }
        if iho_geojson is not None
        else None
    )

    return {
        "point": point,
        "point_source": (
            "coordinates" if has_point
            else "gadm" if location is not None
            else "iho" if location_iho is not None
            else None
        ),
        "location": location,
        "location_iho": location_iho,
    }


def _build_site_map_light_marker(row: dict) -> SiteMapLightMarker:
    marker_lon = row.get("longitude")
    marker_lat = row.get("latitude")
    point = (
        SiteMapLightPoint(latitude=marker_lat, longitude=marker_lon)
        if marker_lat is not None and marker_lon is not None
        else None
    )
    return SiteMapLightMarker(
        site_id=row["site_id"],
        name=row.get("name") or "",
        geometry=SiteMapLightGeometry(point=point, point_source=row.get("point_source")),
        media_count=row["media_count"],
        realm_id=row.get("realm_id"),
        realm_name=row.get("realm_name"),
        biome_id=row.get("biome_id"),
        functional_type_id=row.get("functional_type_id"),
    )


def _build_site_map_light_marker_dict(row: dict) -> dict:
    marker_lon = row.get("longitude")
    marker_lat = row.get("latitude")
    point = (
        {"latitude": marker_lat, "longitude": marker_lon}
        if marker_lat is not None and marker_lon is not None
        else None
    )
    return {
        "site_id": row["site_id"],
        "name": row.get("name") or "",
        "geometry": {"point": point, "point_source": row.get("point_source")},
        "media_count": row["media_count"],
        "realm_id": row.get("realm_id"),
        "realm_name": row.get("realm_name"),
        "biome_id": row.get("biome_id"),
        "functional_type_id": row.get("functional_type_id"),
    }


def _build_map_center(rows: list[dict]) -> dict | None:
    """Build the map center from resolved coordinates."""
    if not rows:
        return None

    resolved_lats = [row.get("resolved_lat", row.get("latitude")) for row in rows]
    resolved_lons = [row.get("resolved_lon", row.get("longitude")) for row in rows]
    resolved_lats = [value for value in resolved_lats if value is not None]
    resolved_lons = [value for value in resolved_lons if value is not None]
    if not resolved_lats or not resolved_lons:
        return None
    return {
        "latitude": (min(resolved_lats) + max(resolved_lats)) / 2,
        "longitude": (min(resolved_lons) + max(resolved_lons)) / 2,
    }


def get_map_markers(
    session: Session,
    current_user: User | None,
    *,
    project_id: int,
    collection_id: int | None = None,
    realm_id: int | None = None,
    biome_id: int | None = None,
    functional_type_id: int | None = None,
    media_type: str = "all",
 ) -> dict:
    """Get map markers for a project with optional IUCN filters."""
    visibility, user_id = _site_visibility(current_user)
    rows = site_repository.get_map_markers(
        session,
        project_id=project_id,
        user_id=user_id,
        is_admin=visibility == "all",
        collection_id=collection_id,
        realm_id=realm_id,
        biome_id=biome_id,
        functional_type_id=functional_type_id,
        media_type=media_type,
    )
    return {
        "markers": [_build_site_map_light_marker_dict(row) for row in rows],
        "center": _build_map_center(rows),
        "count": len(rows),
    }


def _build_iucn_tree_from_nodes(
    all_nodes: list[IucnGet],
    *,
    included_ids: set[int] | None = None,
    usage_rows: list[tuple[int | None, int | None, int | None]] | None = None,
) -> IucnGetOptionsResponse:
    """Build a three-level IUCN tree, optionally pruning to included node ids."""
    node_map: dict[int, IucnGetOption] = {
        n.iucn_get_id: IucnGetOption(id=n.iucn_get_id, name=n.name, children=[])
        for n in all_nodes
    }

    realms: list[IucnGetOption] = []
    for node in all_nodes:
        if included_ids is not None and node.iucn_get_id not in included_ids:
            continue
        if node.level == 1:
            realms.append(node_map[node.iucn_get_id])
        elif node.level in {2, 3}:
            parent = node_map.get(node.pid)
            if parent and (included_ids is None or node.pid in included_ids):
                parent.children.append(node_map[node.iucn_get_id])

    if usage_rows is not None:
        missing_biomes = {realm for realm, biome, _ in usage_rows if realm is not None and biome is None}
        missing_types = {biome for _, biome, group in usage_rows if biome is not None and group is None}
        for realm in realms:
            for biome in realm.children:
                if biome.id in missing_types:
                    biome.children.append(IucnGetOption(id=0, name="No selected", children=[]))
            if realm.id in missing_biomes:
                realm.children.append(IucnGetOption(id=0, name="No selected", children=[]))
        if any(realm is None for realm, _, _ in usage_rows):
            realms.append(IucnGetOption(id=0, name="No selected", children=[]))

    return IucnGetOptionsResponse(realms=realms)


def _collect_included_iucn_ids(
    all_nodes: list[IucnGet],
    usage_rows: list[tuple[int | None, int | None, int | None]],
) -> set[int]:
    """Expand used IUCN tuples to the node ids required to keep parent chains."""
    by_id = {node.iucn_get_id: node for node in all_nodes}
    included_ids: set[int] = set()

    for realm_id, biome_id, functional_type_id in usage_rows:
        if realm_id is not None and realm_id in by_id:
            included_ids.add(realm_id)

        if biome_id is not None and biome_id in by_id:
            biome = by_id[biome_id]
            included_ids.add(biome_id)
            if biome.pid in by_id:
                included_ids.add(biome.pid)

        if functional_type_id is not None and functional_type_id in by_id:
            functional_type = by_id[functional_type_id]
            included_ids.add(functional_type_id)
            if functional_type.pid in by_id:
                biome = by_id[functional_type.pid]
                included_ids.add(biome.iucn_get_id)
                if biome.pid in by_id:
                    included_ids.add(biome.pid)

    return included_ids


def parse_map_site_ids(site_ids: str | None) -> list[int]:
    """Parse comma-separated map site IDs."""
    if not site_ids:
        raise HTTPException(
            status_code=400,
            detail="site_ids is required and must be a comma-separated list of integers",
        )

    parsed_ids: list[int] = []
    for raw in site_ids.split(","):
        token = raw.strip()
        if not token:
            continue
        if not token.isdigit():
            raise HTTPException(
                status_code=400,
                detail="site_ids must be a comma-separated list of integers",
            )
        parsed_ids.append(int(token))
    if not parsed_ids:
        raise HTTPException(
            status_code=400,
            detail="site_ids must include at least one integer",
        )
    return sorted(set(parsed_ids))


def get_map_geometries(
    session: Session,
    current_user: User | None,
    *,
    project_id: int,
    site_ids: list[int],
    collection_id: int | None = None,
) -> SiteMapGeometryResponse:
    """Get geometry payload for selected map sites."""
    visibility, user_id = _site_visibility(current_user)
    rows = site_repository.get_map_geometries(
        session,
        project_id=project_id,
        site_ids=site_ids,
        user_id=user_id,
        is_admin=visibility == "all",
        collection_id=collection_id,
    )
    items = [
        SiteMapGeometryItem(
            site_id=row["site_id"],
            geometry=_build_marker_geometry(row, include_polygons=True),
        )
        for row in rows
    ]
    return SiteMapGeometryResponse(items=items, count=len(items))


def get_site(session: Session, project_id: int | None, site_id: int, current_user: User) -> SitePublic:
    """Get a single site by ID with permission check."""
    site = site_repository.get_site_with_relations(session, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    if project_id is None:
        project_id = _resolve_site_project_id(session, site)
    if project_id is None:
        raise HTTPException(status_code=403, detail="No permission to access this site")

    # Check that the user has access to at least one of its collections
    if not permission_service.is_admin(current_user):
        collection_ids = [
            sc.collection_id
            for sc in (site.site_collections or [])
            if permission_repository.is_project_collection_linked(session, project_id, sc.collection_id)
        ]
        has_access = any(
            permission_service.has_resource_permission(
                session, current_user, resource_type="site", action="read",
                project_id=project_id,
                collection_id=cid
            )
            for cid in collection_ids
        )
        if not has_access:
            raise HTTPException(status_code=403, detail="No permission to access this site")

    return _build_site_public(site)


def get_site_link_options(
    session: Session,
    site_id: int,
    current_user: User,
    *,
    project_id: int,
    name: str | None = None,
    other_project_name: str | None = None,
) -> SiteLinkOptionsResponse:
    """Get grouped link options for the site link dialog."""
    site = site_repository.get_site_with_relations(session, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    project = project_repository.get(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    selected_collection_ids = sorted({sc.collection_id for sc in (site.site_collections or [])})
    selected_project_ids = sorted({sp.project_id for sp in (site.site_projects or [])})

    if not permission_service.is_admin(current_user):
        has_site_read = any(
            permission_service.has_resource_permission(
                session,
                current_user,
                resource_type="site",
                action="read",
                collection_id=cid,
            )
            for cid in selected_collection_ids
        )

        can_write_project = permission_service.has_resource_permission(
            session,
            current_user,
            resource_type="project",
            action="write",
            project_id=project_id,
        )
        can_manage_project_collections = permission_service.has_resource_permission(
            session,
            current_user,
            resource_type="collection",
            action="write",
            project_id=project_id,
        )
        if not can_write_project and not can_manage_project_collections:
            raise HTTPException(status_code=403, detail="No write permission on target project")
        if selected_collection_ids and not has_site_read:
            raise HTTPException(status_code=403, detail="No permission to access this site")

    current_collection_ids = set(project_repository.get_project_collection_ids(session, project_id))
    manageable_user_id = None if permission_service.is_admin(current_user) else current_user.user_id

    current_rows = project_repository.get_manageable_project_collection_rows(
        session,
        user_id=manageable_user_id,
        exclude_project_id=None,
        collection_name=name,
        project_name=None,
    )
    current_collections: list[dict] = []
    for pid, _pname, cid, cname in current_rows:
        if pid != project_id:
            continue
        current_collections.append(
            {
                "collection_id": cid,
                "name": cname,
                "selected": cid in selected_collection_ids,
            }
        )

    other_rows = project_repository.get_manageable_project_collection_rows(
        session,
        user_id=manageable_user_id,
        exclude_project_id=project_id,
        collection_name=name,
        project_name=other_project_name,
    )

    duplicates_map: dict[int, set[int]] = {}
    for pid, _pname, cid, _cname in other_rows:
        if cid in current_collection_ids:
            continue
        duplicates_map.setdefault(cid, set()).add(pid)

    other_projects_map: dict[int, dict] = {}
    for pid, pname, cid, cname in other_rows:
        if cid in current_collection_ids:
            continue
        if pid not in other_projects_map:
            other_projects_map[pid] = {
                "project_id": pid,
                "project_name": pname,
                "collections": [],
            }
        other_projects_map[pid]["collections"].append(
            {
                "collection_id": cid,
                "name": cname,
                "selected": cid in selected_collection_ids,
                "duplicate_project_ids": sorted(duplicates_map.get(cid, set())),
            }
        )
    other_projects = list(other_projects_map.values())

    manageable_collection_ids: list[int] | None = None
    if not permission_service.is_admin(current_user):
        manageable_collection_ids = permission_repository.get_accessible_collection_ids(
            session,
            current_user.user_id,
            resource_type="collection",
            action="write",
        )
    unassigned = project_repository.get_unassigned_collections(
        session,
        collection_ids=manageable_collection_ids,
        name=name,
    )
    unassigned_collections = [
        {
            "collection_id": c.collection_id,
            "name": c.name,
            "selected": c.collection_id in selected_collection_ids,
        }
        for c in unassigned
        if c.collection_id not in current_collection_ids
    ]

    return SiteLinkOptionsResponse.model_validate(
        {
            "current_project": {
                "project_id": project.project_id,
                "project_name": project.name,
                "collections": current_collections,
            },
            "other_projects": other_projects,
            "unassigned_collections": unassigned_collections,
            "selected_collection_ids": selected_collection_ids,
            "selected_project_ids": selected_project_ids,
        }
    )


def update_site(session: Session, project_id: int | None, site_id: int, data: SiteUpdate, current_user: User) -> SitePublic:
    """Update a site. Requires site:write on at least one of its collections."""
    site = site_repository.get_site_with_relations(session, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    if project_id is None:
        project_id = _resolve_site_project_id(session, site)
    if project_id is None:
        raise HTTPException(status_code=403, detail="No site:write permission on this site")

    if not permission_service.is_admin(current_user):
        collection_ids = [
            sc.collection_id
            for sc in (site.site_collections or [])
            if permission_repository.is_project_collection_linked(session, project_id, sc.collection_id)
        ]
        has_write = any(
            permission_service.has_resource_permission(
                session, current_user, resource_type="site", action="write",
                project_id=project_id,
                collection_id=cid
            )
            for cid in collection_ids
        )
        if not has_write:
            raise HTTPException(status_code=403, detail="No site:write permission on this site")

    # Only resolve IUCN hierarchy when the client actually sent at least one IUCN field.
    # Without this guard, an unrelated PATCH (e.g. only "name") would supply None for
    # all three fields and silently wipe the stored classification.
    _iucn_keys = {"realm_id", "biome_id", "functional_type_id"}
    if _iucn_keys & data.model_fields_set:
        data.realm_id, data.biome_id, data.functional_type_id = _resolve_iucn_ids(
            session, data.realm_id, data.biome_id, data.functional_type_id
        )

    site = site_repository.update_site(session, db_obj=site, data=data)
    site = site_repository.get_site_with_relations(session, site_id)
    return _build_site_public(site)


def sync_site_collections(
    session: Session,
    current_user: User,
    project_id: int,
    site_ids: list[int],
    collection_ids: list[int],
    project_ids: list[int] | None = None,
) -> None:
    """Sync manageable collection and project bindings across multiple sites."""
    normalized_site_ids = sorted(set(site_ids))
    requested_collection_ids = sorted(set(collection_ids))
    requested_project_ids = sorted(set(project_ids or []))

    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    existing_site_ids = set(
        session.exec(select(Site.site_id).where(Site.site_id.in_(normalized_site_ids))).all()
    )
    missing_site_ids = sorted(set(normalized_site_ids) - existing_site_ids)
    if missing_site_ids:
        raise HTTPException(status_code=404, detail=f"Site(s) not found: {missing_site_ids}")

    existing_collection_ids = set(
        session.exec(
            select(Collection.collection_id).where(
                Collection.collection_id.in_(requested_collection_ids)
            )
        ).all()
    )
    missing_collection_ids = sorted(set(requested_collection_ids) - existing_collection_ids)
    if missing_collection_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Collection(s) not found: {missing_collection_ids}",
        )

    existing_project_ids = set(
        session.exec(
            select(Project.project_id).where(Project.project_id.in_(requested_project_ids))
        ).all()
    )
    missing_project_ids = sorted(set(requested_project_ids) - existing_project_ids)
    if missing_project_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Project(s) not found: {missing_project_ids}",
        )

    project_site_collection_rows = session.exec(
        select(SiteCollection.site_id, SiteCollection.collection_id)
        .join(
            ProjectCollection,
            ProjectCollection.collection_id == SiteCollection.collection_id,
        )
        .where(
            ProjectCollection.project_id == project_id,
            SiteCollection.site_id.in_(normalized_site_ids),
        )
    ).all()
    site_collection_ids_in_current_project = {
        site_id: set() for site_id in normalized_site_ids
    }
    for site_id, collection_id in project_site_collection_rows:
        site_collection_ids_in_current_project[site_id].add(collection_id)

    outside_current_project_site_ids = sorted(
        site_id
        for site_id, linked_collection_ids in site_collection_ids_in_current_project.items()
        if not linked_collection_ids
    )
    if outside_current_project_site_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Site(s) are not linked to project {project_id}: {outside_current_project_site_ids}",
        )

    all_project_collection_rows = session.exec(
        select(ProjectCollection.project_id, ProjectCollection.collection_id)
    ).all()
    project_collection_map: dict[int, set[int]] = {}
    collection_project_map: dict[int, set[int]] = {}
    for linked_project_id, linked_collection_id in all_project_collection_rows:
        project_collection_map.setdefault(linked_project_id, set()).add(linked_collection_id)
        collection_project_map.setdefault(linked_collection_id, set()).add(linked_project_id)

    if permission_service.is_admin(current_user):
        manageable_collection_ids = set(
            session.exec(select(Collection.collection_id)).all()
        )
        manageable_project_ids = set(
            session.exec(select(Project.project_id)).all()
        )
    else:
        site_write_scopes = set(permission_repository.get_effective_collection_scopes(
            session,
            current_user.user_id,
            resource_type="site",
            action="write",
        ))
        manageable_collection_ids = {collection_id for _, collection_id in site_write_scopes}
        manageable_project_ids = {
            candidate_project_id
            for candidate_project_id, candidate_collection_ids in project_collection_map.items()
            if candidate_collection_ids
            and all(
                (candidate_project_id, candidate_collection_id) in site_write_scopes
                for candidate_collection_id in candidate_collection_ids
            )
        }

        inaccessible_site_ids = sorted(
            site_id
            for site_id, linked_collection_ids in site_collection_ids_in_current_project.items()
            if not any(
                (project_id, linked_collection_id) in site_write_scopes
                for linked_collection_id in linked_collection_ids
            )
        )
        if inaccessible_site_ids:
            raise HTTPException(
                status_code=403,
                detail=f"No site:write permission on site(s): {inaccessible_site_ids}",
            )

        disallowed_collection_ids = sorted(
            collection_id
            for collection_id in requested_collection_ids
            if not any(
                (candidate_project_id, collection_id) in site_write_scopes
                for candidate_project_id in collection_project_map.get(collection_id, set())
            )
        )
        if disallowed_collection_ids:
            raise HTTPException(
                status_code=403,
                detail=f"No site:write permission on collection(s): {disallowed_collection_ids}",
            )

        disallowed_project_ids = sorted(set(requested_project_ids) - manageable_project_ids)
        if disallowed_project_ids:
            raise HTTPException(
                status_code=403,
                detail=f"No site:write permission on project(s): {disallowed_project_ids}",
            )

    site_repository.sync_collection_and_project_links(
        session,
        site_ids=normalized_site_ids,
        managed_collection_ids=manageable_collection_ids,
        requested_collection_ids=requested_collection_ids,
        managed_project_ids=manageable_project_ids,
        requested_project_ids=requested_project_ids,
    )
    session.commit()


def delete_site(session: Session, site_id: int, current_user: User, project_id: int | None = None) -> None:
    """Delete a site.

    Requires site:write on at least one project-local collection path.
    Deletion is blocked if the site has any associated media records.
    """
    site = site_repository.get_site_with_relations(session, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    if not permission_service.is_admin(current_user):
        collection_ids = [sc.collection_id for sc in (site.site_collections or [])]
        if not permission_service.has_resource_permission_on_any_collection_path(
            session,
            current_user,
            collection_ids,
            "site",
            "write",
            project_id=project_id,
        ):
            raise HTTPException(status_code=403, detail="No site:write permission on this site")

    # Block deletion if any media is still linked to this site
    has_media = session.exec(
        select(Media).where(Media.site_id == site_id)
    ).first()
    if has_media:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete site: it still has associated media records. "
                   "Please unlink all media before deleting."
        )

    # Remove link-table rows before deleting the parent site so SQLAlchemy
    # never tries to null out a PK-backed FK on in-session relationship rows.
    session.exec(delete(SiteCollection).where(SiteCollection.site_id == site_id))
    session.exec(delete(SiteProject).where(SiteProject.site_id == site_id))
    session.exec(delete(Site).where(Site.site_id == site_id))
    session.commit()


def export_site_csv(
    session: Session,
    current_user: User,
    order_by: str = "site_id",
    order_dir: str = "asc",
    **filters,
) -> str:
    """Export sites as a CSV string."""
    items, _ = _query_visible_sites(
        session,
        current_user,
        filters=filters,
        page=1,
        page_size=100000,
        order_by=order_by,
        order_dir=order_dir,
        include_total=False,
    )
    site_list = [_build_site_public(s) for s in items]

    return export_columns_csv(_SITE_EXPORT_COLUMNS, site_list)


def get_iucn_options(
    session: Session,
    current_user: User | None = None,
    *,
    project_id: int | None = None,
    collection_id: int | None = None,
) -> IucnGetOptionsResponse:
    """Return IUCN GET typology as a three-level nested option tree.

    Structure: realms (level 1) → biomes (level 2) → functional types (level 3)
    """
    all_nodes = session.exec(
        select(IucnGet).order_by(IucnGet.level, IucnGet.pid, IucnGet.iucn_get_id)
    ).all()
    if project_id is None and collection_id is None:
        return _build_iucn_tree_from_nodes(all_nodes)

    resolved_project_id = project_id
    if collection_id is not None:
        resolved_project_id = permission_service.resolve_collection_project_id(
            session,
            collection_id,
            project_id,
        )
    if resolved_project_id is None:
        return _build_iucn_tree_from_nodes(all_nodes)

    visibility, user_id = _site_visibility(current_user)
    usage_rows = site_repository.get_visible_iucn_usage(
        session,
        project_id=resolved_project_id,
        collection_id=collection_id,
        user_id=user_id,
        is_admin=visibility == "all",
    )
    included_ids = _collect_included_iucn_ids(all_nodes, usage_rows)
    return _build_iucn_tree_from_nodes(
        all_nodes,
        included_ids=included_ids,
        usage_rows=usage_rows,
    )
