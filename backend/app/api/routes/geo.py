from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import SessionDep
from app.repositories.geo_repository import GeoDataUnavailableError
from app.schemas.geo import GeoOption, IucnOption
from app.schemas.response import PagedApiResponse, api_page
from app.services import geo_service

router = APIRouter(prefix="/geo", tags=["地理字典 / Geo Dictionary"])

@router.get(
    "/gadm",
    response_model=PagedApiResponse[list[GeoOption]],
    summary="获取 GADM 行政区划选项 / Get GADM administrative options",
)
def get_gadm_options(
    session: SessionDep,
    level: int = Query(..., description="行政级别: 0=国家, 1=省/州, 2=市/县 / Level 0=Country, 1=Province, 2=City"),
    parent_gid: str | None = Query(None, description="上级行政区 GID，用于联动过滤 / Parent GID for cascading filter"),
    search: str | None = Query(None, description="关键字模糊搜索 / Keyword search"),
    page: int = Query(1, ge=1, description="页码 / Page number"),
    page_size: int = Query(100, ge=1, le=100, description="每页条数 / Page size"),
) -> Any:
    """
    获取 GADM 全局行政区划选项。 / Get GADM administrative boundary options.

    支持关键字模糊搜索，支持通过 parent_gid (上级 GID) 进行下级联动查询。
    Supports keyword search and cascading filtering via parent GID.
    无需身份验证。 / No authentication required.
    """
    try:
        data, total = geo_service.get_gadm_options(
            session=session,
            level=level,
            parent_gid=parent_gid,
            search=search,
            page=page,
            page_size=page_size,
        )
    except GeoDataUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return api_page(data=data, total=total, page=page, page_size=page_size)


@router.get(
    "/iho",
    response_model=PagedApiResponse[list[GeoOption]],
    summary="获取 IHO 海域选项 / Get IHO Sea Area options",
)
def get_iho_options(
    session: SessionDep,
    search: str | None = Query(None, description="关键字模糊搜索 / Keyword search"),
    page: int = Query(1, ge=1, description="页码 / Page number"),
    page_size: int = Query(100, ge=1, le=100, description="每页条数 / Page size"),
) -> Any:
    """
    获取 IHO 全球海域选项。 / Get IHO globally sea area options.

    无需身份验证。 / No authentication required.
    """
    data, total = geo_service.get_iho_options(
        session=session,
        search=search,
        page=page,
        page_size=page_size,
    )
    return api_page(data=data, total=total, page=page, page_size=page_size)


@router.get(
    "/iucn-realms",
    response_model=PagedApiResponse[list[IucnOption]],
    summary="获取 IUCN 界别选项 / Get IUCN Realm options",
)
def get_iucn_realms(
    session: SessionDep,
    search: str | None = Query(None, description="关键字搜索 / Keyword search"),
    page: int = Query(1, ge=1, description="页码 / Page number"),
    page_size: int = Query(100, ge=1, le=100, description="每页条数 / Page size"),
) -> Any:
    """
    获取 IUCN 全球生态系统分类 Level 1 (Realm) 界别选项。
    Get IUCN Global Ecosystem Typology Level 1 (Realm) options.

    无需身份验证。 / No authentication required.
    """
    data, total = geo_service.get_iucn_realms(
        session=session,
        search=search,
        page=page,
        page_size=page_size,
    )
    return api_page(data=data, total=total, page=page, page_size=page_size)


@router.get(
    "/iucn-biomes",
    response_model=PagedApiResponse[list[IucnOption]],
    summary="获取 IUCN 群系选项 / Get IUCN Biome options",
)
def get_iucn_biomes(
    session: SessionDep,
    realm_id: int | None = Query(None, description="所属界别 ID / Parent Realm ID"),
    search: str | None = Query(None, description="关键字搜索 / Keyword search"),
    page: int = Query(1, ge=1, description="页码 / Page number"),
    page_size: int = Query(100, ge=1, le=100, description="每页条数 / Page size"),
) -> Any:
    """
    获取 IUCN 全球生态系统分类 Level 2 (Biome) 群系选项。
    Get IUCN Global Ecosystem Typology Level 2 (Biome) options.

    支持根据 realm_id (Level 1) 进行联动过滤。
    Supports cascading filtering by realm_id (Level 1).
    无需身份验证。 / No authentication required.
    """
    data, total = geo_service.get_iucn_biomes(
        session=session,
        realm_id=realm_id,
        search=search,
        page=page,
        page_size=page_size,
    )
    return api_page(data=data, total=total, page=page, page_size=page_size)


@router.get(
    "/iucn-functional-types",
    response_model=PagedApiResponse[list[IucnOption]],
    summary="获取 IUCN 功能组选项 / Get IUCN Functional Type options",
)
def get_iucn_functional_types(
    session: SessionDep,
    biome_id: int | None = Query(None, description="所属群系 ID / Parent Biome ID"),
    search: str | None = Query(None, description="关键字搜索 / Keyword search"),
    page: int = Query(1, ge=1, description="页码 / Page number"),
    page_size: int = Query(100, ge=1, le=100, description="每页条数 / Page size"),
) -> Any:
    """
    获取 IUCN 全球生态系统分类 Level 3 (Functional Group) 功能组选项。
    Get IUCN Global Ecosystem Typology Level 3 (Functional Group) options.

    支持根据 biome_id (Level 2) 进行联动过滤。
    Supports cascading filtering by biome_id (Level 2).
    无需身份验证。 / No authentication required.
    """
    data, total = geo_service.get_iucn_functional_types(
        session=session,
        biome_id=biome_id,
        search=search,
        page=page,
        page_size=page_size,
    )
    return api_page(data=data, total=total, page=page, page_size=page_size)
