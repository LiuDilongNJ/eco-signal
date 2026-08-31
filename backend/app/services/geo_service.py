from sqlmodel import Session

from app.repositories.geo_repository import geo_repository
from app.schemas.geo import (
    CoordinateGadmMatch,
    CoordinateGeoOption,
    CoordinateIhoMatch,
    CoordinateMatchesResponse,
    GeoOption,
    IucnOption,
)


def get_gadm_options(
    session: Session,
    level: int,
    parent_gid: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[GeoOption], int]:
    """Get GADM boundaries mapped as simple string names, supporting ST_Intersects hierarchical matching."""
    rows, total = geo_repository.get_gadm_options(
        session,
        level=level,
        parent_gid=parent_gid,
        search=search,
        page=page,
        page_size=page_size,
    )
    return [GeoOption(gid=row[0], name=row[1]) for row in rows if row[1]], total


def get_iho_options(
    session: Session,
    search: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[GeoOption], int]:
    rows, total = geo_repository.get_iho_options(
        session,
        search=search,
        page=page,
        page_size=page_size,
    )
    return [GeoOption(gid=str(row[0]), name=row[1]) for row in rows if row[1]], total


def get_iucn_realms(
    session: Session,
    search: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[IucnOption], int]:
    # IUCN level 1 is Realm
    items, total = geo_repository.get_iucn_options(
        session,
        level=1,
        search=search,
        page=page,
        page_size=page_size,
    )
    return [IucnOption(id=item.iucn_get_id, name=item.name) for item in items], total


def get_iucn_biomes(
    session: Session,
    realm_id: int | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[IucnOption], int]:
    # IUCN level 2 is Biome, pid links to Realm (level 1)
    items, total = geo_repository.get_iucn_options(
        session,
        level=2,
        parent_id=realm_id,
        search=search,
        page=page,
        page_size=page_size,
    )
    return [IucnOption(id=item.iucn_get_id, name=item.name) for item in items], total


def get_iucn_functional_types(
    session: Session,
    biome_id: int | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[IucnOption], int]:
    # IUCN level 3 is Functional Type, pid links to Biome (level 2)
    items, total = geo_repository.get_iucn_options(
        session,
        level=3,
        parent_id=biome_id,
        search=search,
        page=page,
        page_size=page_size,
    )
    return [IucnOption(id=item.iucn_get_id, name=item.name) for item in items], total


def get_coordinate_matches(longitude: float, latitude: float) -> CoordinateMatchesResponse:
    match = geo_repository.coordinate_matches(longitude, latitude)

    def option(value):
        return CoordinateGeoOption(gid=value.gid, name=value.name) if value else None

    return CoordinateMatchesResponse(
        gadm=CoordinateGadmMatch(
            status=match.gadm_status,
            gadm0=option(match.gadm0),
            gadm1=option(match.gadm1),
            gadm2=option(match.gadm2),
        ),
        iho=CoordinateIhoMatch(status=match.iho_status, option=option(match.iho)),
    )
