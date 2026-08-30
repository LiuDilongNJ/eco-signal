"""站点 API 路由。 / Sites API routes."""
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, File, Form, Query, UploadFile

from app.api.deps import CurrentUser, CurrentUserOptional, SessionDep
from app.api.responses import csv_response
from app.csv_import import attach_import_metadata, parse_import_upload
from app.schemas.device import SiteOption
from app.schemas.response import ApiResponse, PagedApiResponse, api_success
from app.schemas.site import (
    IucnGetOptionsResponse,
    SiteCollectionSyncRequest,
    SiteCreate,
    SiteLinkOptionsResponse,
    SiteMapGeometryResponse,
    SitePublic,
    SiteUpdate,
)
from app.services import permission_service, site_service
from app.services import tabular_import_service
from app.utils import parse_range, parse_uuid

router = APIRouter(prefix="/sites", tags=["站点 / sites"])
router_views = APIRouter(tags=["站点 / sites"])


@router.post("/imports", summary="导入站点 / Import Sites")
async def import_sites(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int = Form(...),
    collection_id: int = Form(...),
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
) -> Any:
    """校验或原子导入站点。 / Validate or atomically import sites."""
    permission_service.require_collection_resource_permission(
        session,
        collection_id=collection_id,
        project_id=project_id,
        user=current_user,
        resource_type="site",
        action="write",
        denied_detail="No site:write permission on collection",
    )
    parsed = parse_import_upload(file.filename or "", await file.read())
    report = tabular_import_service.import_sites(
        session,
        parsed.text,
        current_user,
        project_id,
        collection_id,
        dry_run=dry_run,
    )
    return api_success(message="Import validation completed" if dry_run else "Import completed", data=attach_import_metadata(report, parsed, dry_run=dry_run))



@router_views.get(
    "/site-options",
    response_model=ApiResponse[list[SiteOption]],
    summary="获取站点选项 / Get Site Options",
)
def get_site_options(
    session: SessionDep,
    current_user: CurrentUserOptional,
    project_id: Optional[int] = Query(default=None, description="通过项目 ID 筛选 / Filter by project ID"),
    collection_id: Optional[int] = Query(default=None, description="通过集合 ID 筛选 / Filter by collection ID"),
    name: Optional[str] = Query(default=None, description="通过站点名称搜索 / Search by site name"),
) -> Any:
    """
    获取下拉菜单的站点选项。 / Get site options for dropdown menus.

    - 统一按站点主数据范围返回候选。 /
      Always returns candidates from the site master-data scope.
    - 传入 `project_id` / `collection_id` 时，使用与站点列表一致的可见性和权限范围。 /
      When `project_id` / `collection_id` is provided, uses the same visibility and permission scope as the site list.
    - `name` 仅匹配站点名称，不按媒体名称筛选。 /
      `name` only matches site names, not media names.
    """
    data = site_service.get_site_options(
        session,
        current_user,
        project_id=project_id,
        collection_id=collection_id,
        name=name,
    )
    return api_success(data=data)


@router_views.get(
    "/iucn-typology-options",
    response_model=ApiResponse[IucnGetOptionsResponse],
    summary="获取 IUCN GET 三级分类选项 / Get IUCN GET Typology Options",
)
def get_iucn_options(
    session: SessionDep,
    current_user: CurrentUserOptional,
    project_id: Optional[int] = Query(None, description="项目 ID（可选，用于按地图可见范围过滤） / Project ID (optional, filters by map-visible scope)"),
    collection_id: Optional[int] = Query(None, description="集合 ID（可选，需与项目路径匹配） / Collection ID (optional, must match the project path)"),
) -> Any:
    """
    获取 IUCN 全球生态系统分类三级联动选项（Realm > Biome > Functional Type）。
    Get IUCN Global Ecosystem Typology options as a three-level nested tree.

    - 不传范围参数时，返回全量 IUCN 树。
      Returns the full IUCN tree when no scope parameters are provided.
    - 传入 project_id / collection_id 时，仅返回当前地图可见站点实际使用到的节点。
      When project_id / collection_id is provided, returns only nodes used by currently visible map sites.
    - 匿名用户仅按 public 范围过滤；登录用户按可访问范围 + public 范围过滤。
      Anonymous users are filtered by public scope only; authenticated users use accessible + public scope.
    """
    if collection_id is not None:
        project_id = permission_service.resolve_collection_project_id(session, collection_id, project_id)

    result = site_service.get_iucn_options(
        session,
        current_user,
        project_id=project_id,
        collection_id=collection_id,
    )
    return api_success(data=result)


@router_views.get(
    "/site-map-items",
    response_model=None,
    summary="获取项目地图站点 / Get Project Map Sites",
)
def get_project_map_sites(
    session: SessionDep,
    current_user: CurrentUserOptional,
    project_id: int = Query(..., description="项目 ID（必填） / Project ID (required)"),
    collection_id: Optional[int] = Query(None, description="集合 ID（可选，按当前集合口径统计媒体） / Collection ID (optional, scope media stats)"),
    realm_id: Optional[int] = Query(None, description="Realm 筛选 / Filter by realm"),
    biome_id: Optional[int] = Query(None, description="Biome 筛选 / Filter by biome"),
    functional_type_id: Optional[int] = Query(None, description="Functional type 筛选 / Filter by functional type"),
    media_type: Literal["all", "audio", "photo"] = Query(default="all", description="媒体类型筛选：all / audio / photo / Filter by media type"),
) -> Any:
    """
    获取项目地图站点标记数据。 / Get map marker data for a project.

    - 默认返回轻量 markers（仅 point），媒体数量和 IUCN 分类。
      Returns lightweight markers (point-only), media count, and IUCN classes.
    - 详细 polygon geometry 通过 `/site-map-items/geometries` 按需获取。
      Detailed polygon geometry is fetched on demand via `/site-map-items/geometries`.
    - 支持 Realm/Biome/Functional Type 三级筛选。
      Supports three-level filtering by Realm/Biome/Functional Type.
    - 权限规则：匿名仅返回公开集合站点；登录用户返回可访问集合 + 公开集合。
      Permission: anonymous users get public collections only; authenticated users get accessible + public.
    """
    if collection_id is not None:
        permission_service.resolve_collection_project_id(session, collection_id, project_id)

    result = site_service.get_map_markers(
        session,
        current_user,
        project_id=project_id,
        collection_id=collection_id,
        realm_id=realm_id,
        biome_id=biome_id,
        functional_type_id=functional_type_id,
        media_type=media_type,
    )
    return api_success(data=result)


@router_views.get(
    "/site-map-items/geometries",
    response_model=ApiResponse[SiteMapGeometryResponse],
    summary="按需获取站点地图几何 / Get Site Map Geometries On Demand",
)
def get_project_map_site_geometries(
    session: SessionDep,
    current_user: CurrentUserOptional,
    project_id: int = Query(..., description="项目 ID（必填） / Project ID (required)"),
    site_ids: str = Query(..., description="站点 ID 列表（逗号分隔） / Site IDs (comma-separated)"),
    collection_id: Optional[int] = Query(None, description="集合 ID（可选） / Collection ID (optional)"),
) -> Any:
    """
    按需返回站点地图 geometry。/ Return map geometries for selected sites on demand.

    保持与地图接口一致的权限口径（公开集合 + 可访问集合）。
    Uses the same visibility scope as map markers endpoint.
    """
    if collection_id is not None:
        permission_service.resolve_collection_project_id(session, collection_id, project_id)

    parsed_site_ids = site_service.parse_map_site_ids(site_ids)
    result = site_service.get_map_geometries(
        session,
        current_user,
        project_id=project_id,
        site_ids=parsed_site_ids,
        collection_id=collection_id,
    )
    return api_success(data=result)



@router.post(
    "",
    response_model=ApiResponse[dict],
    status_code=201,
    summary="创建站点 / Create a Site",
)
def create_site(
    session: SessionDep,
    current_user: CurrentUser,
    data: SiteCreate,
) -> Any:
    """
    创建新站点并绑定到集合或项目。 / Create a new site and bind it to a collection or project.

    - 若提供 collection_id，将站点绑定到该集合（优先）。
      If collection_id is provided, binds to that specific collection (priority).
    - 若仅提供 project_id，将站点绑定到该项目下的所有集合。
      If only project_id is provided, binds to all collections under the project.
    - 经纬度为可选字段，仅在用户明确填写时入库，不自动从地理范围计算。
      Longitude/Latitude are optional and stored only when explicitly provided by the user.
    - 需要目标集合路径的 site:write 权限。
      Requires site:write permission on the target collection path.
    """
    site_service.create_site(session, data=data, current_user=current_user)
    return api_success(message="Site created successfully")



@router.get(
    "/exports",
    summary="导出站点 CSV / Export Sites to CSV",
)
def export_sites(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int = Query(..., description="项目 ID（必填）/ Project ID (required)"),
    collection_id: Optional[int] = Query(None, description="集合 ID / Collection ID"),
    order_by: str = Query(default="site_id", description="排序字段 / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向：asc 或 desc / Sort direction"),
):
    """
    导出站点数据为 CSV 文件。 / Export site data as a CSV file.

    使用与列表接口相同的权限和筛选规则。
    Uses the same permission and filtering rules as the list endpoint.
    """
    filters = {
        k: v for k, v in {
            "project_id": project_id,
            "collection_id": collection_id,
        }.items() if v is not None
    }
    csv_content = site_service.export_site_csv(
        session,
        current_user,
        order_by=order_by,
        order_dir=order_dir,
        **filters,
    )
    return csv_response(csv_content, "sites.csv")


@router.get(
    "",
    response_model=PagedApiResponse[list[SitePublic]],
    summary="获取站点列表 / List Sites",
)
def list_sites(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int = Query(..., description="项目 ID（必填）/ Project ID (required)"),
    collection_id: Optional[int] = Query(None, description="集合 ID / Collection ID"),
    name: Optional[str] = Query(None, description="站点名称（模糊）/ Site name (fuzzy)"),
    site_id: Optional[int] = Query(None, description="按站点 ID 精确筛选 / Filter by site ID (exact)"),
    uuid: Optional[str] = Query(None, description="按 UUID 精确筛选 / Filter by UUID (exact)"),
    latitude:           Optional[str] = Query(None, description="纬度区间 min,max / Latitude range min,max"),
    longitude:          Optional[str] = Query(None, description="经度区间 min,max / Longitude range min,max"),
    topography_m:       Optional[str] = Query(None, description="地形高度区间(m) min,max / Topography range (m) min,max"),
    freshwater_depth_m: Optional[str] = Query(None, description="水深区间(m) min,max / Freshwater depth range (m) min,max"),
    realm_id: Optional[int] = Query(None),
    biome_id: Optional[int] = Query(None),
    functional_type_id: Optional[int] = Query(None),
    gadm0: Optional[str] = Query(None, description="国家/地区名称模糊筛选 / Fuzzy filter by country or region name"),
    gadm1: Optional[str] = Query(None, description="省/州名称模糊筛选 / Fuzzy filter by province or state name"),
    gadm2: Optional[str] = Query(None, description="市/县名称模糊筛选 / Fuzzy filter by city or district name"),
    iho: Optional[str] = Query(None, description="海域名称模糊筛选 / Fuzzy filter by IHO sea area name"),
    realm_name: Optional[str] = Query(None, description="Realm 名称模糊筛选 / Fuzzy filter by realm name"),
    biome_name: Optional[str] = Query(None, description="Biome 名称模糊筛选 / Fuzzy filter by biome name"),
    functional_type_name: Optional[str] = Query(None, description="Functional type 名称模糊筛选 / Fuzzy filter by functional type name"),
    iho_id: Optional[int] = Query(None, description="海域选项 ID / IHO sea area ID"),
    gadm0_gid: Optional[str] = Query(None, description="国家/地区 GADM ID / Country GADM ID"),
    gadm1_gid: Optional[str] = Query(None, description="省/州 GADM ID / Province/state GADM ID"),
    gadm2_gid: Optional[str] = Query(None, description="市/县 GADM ID / City/district GADM ID"),
    creator_id: Optional[int] = Query(None),
    creator_name: Optional[str] = Query(None, description="创建者名称模糊筛选（大小写不敏感） / Fuzzy filter by creator name (case-insensitive)"),
    creation_date_from: Optional[datetime] = Query(None),
    creation_date_to: Optional[datetime] = Query(None),
    order_by: str = Query(default="site_id", description="排序字段：site_id, name, topography_m, freshwater_depth_m, creator_id, creation_date, realm_name, biome_name, functional_type_name / Order by field"),
    order_dir: str = Query(default="asc", description="排序方向 asc/desc / Order direction"),
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数 / Page size"),
) -> Any:
    """
    获取站点分页列表，支持多字段筛选和排序。
    Get a paginated list of sites with multi-field filtering and sorting.

    - 管理员可查看所有站点；普通用户只能查看有权限集合下的站点。
      Admins see all sites; regular users only see sites in their accessible collections.
    - project_id 为必填参数。 / project_id is required.
    """
    _lat_min,  _lat_max  = parse_range(latitude)
    _lng_min,  _lng_max  = parse_range(longitude)
    _topo_min, _topo_max = parse_range(topography_m)
    _fwd_min,  _fwd_max  = parse_range(freshwater_depth_m)

    filters = {
        k: v for k, v in {
            "project_id": project_id, "collection_id": collection_id,
            "name": name,
            "site_id": site_id,
            "uuid": parse_uuid(uuid),
            "latitude_min":         _lat_min,  "latitude_max":         _lat_max,
            "longitude_min":        _lng_min,  "longitude_max":        _lng_max,
            "topography_m_min":       _topo_min, "topography_m_max":       _topo_max,
            "freshwater_depth_m_min": _fwd_min,  "freshwater_depth_m_max": _fwd_max,
            "realm_id": realm_id, "biome_id": biome_id,
            "functional_type_id": functional_type_id,
            "gadm0": gadm0, "gadm1": gadm1, "gadm2": gadm2,
            "iho": iho,
            "realm_name": realm_name, "biome_name": biome_name, "functional_type_name": functional_type_name,
            "iho_id": iho_id, "gadm0_gid": gadm0_gid, "gadm1_gid": gadm1_gid, "gadm2_gid": gadm2_gid,
            "creator_id": creator_id,
            "creator_name": creator_name,
            "creation_date_from": creation_date_from,
            "creation_date_to": creation_date_to,
        }.items() if v is not None
    }
    result = site_service.list_sites(
        session, current_user,
        page=page, page_size=page_size,
        order_by=order_by, order_dir=order_dir,
        **filters,
    )
    return result


@router.get(
    "/{site_id}",
    response_model=ApiResponse[SitePublic],
    summary="获取站点详情 / Get Site Detail",
)
def get_site(
    session: SessionDep,
    current_user: CurrentUser,
    site_id: int,
    project_id: int | None = Query(None, description="项目 ID / Project ID"),
) -> Any:
    """
    获取指定站点的详细信息。 / Get detailed information for a specific site.

    需要对该站点所在集合有访问权限。
    Requires read access to at least one collection this site belongs to.
    """
    site = site_service.get_site(
        session, project_id=project_id, site_id=site_id, current_user=current_user
    )
    return api_success(data=site)


@router.patch(
    "/{site_id}",
    response_model=ApiResponse[dict],
    summary="更新站点 / Update Site",
)
def update_site(
    session: SessionDep,
    current_user: CurrentUser,
    site_id: int,
    data: SiteUpdate,
    project_id: int | None = Query(None, description="项目 ID / Project ID"),
) -> Any:
    """
    更新站点信息。 / Update site information.

    - 需要对该站点所在任意集合有 site:write 权限。
      Requires site:write permission on at least one collection this site belongs to.
    - 经纬度为可选字段，仅在用户明确填写时更新，不自动从地理范围重新计算。
      Longitude/Latitude are optional and only updated when explicitly provided by the user.
    """
    site_service.update_site(
        session, project_id=project_id, site_id=site_id, data=data, current_user=current_user
    )
    return api_success(message="Site updated successfully")


@router.get(
    "/{site_id}/collection-options",
    response_model=ApiResponse[SiteLinkOptionsResponse],
    summary="获取站点关联弹窗数据 / Get Site Link Options",
)
def get_site_link_options(
    session: SessionDep,
    current_user: CurrentUser,
    site_id: int,
    project_id: int = Query(..., description="当前项目 ID（必填） / Current project ID (required)"),
    name: Optional[str] = Query(default=None, description="按集合名称搜索 / Search by collection name"),
    other_project_name: Optional[str] = Query(default=None, description="按其他项目名称搜索 / Search by other project name"),
) -> Any:
    """
    获取站点 Link 弹窗初始化数据。 / Get grouped options for site link dialog.

    返回分组结构（当前项目、其他项目、未分配集合）及站点当前已选 IDs。
    Returns grouped options (current project, other projects, unassigned collections)
    plus current selected IDs for the target site.
    """
    data = site_service.get_site_link_options(
        session,
        site_id=site_id,
        current_user=current_user,
        project_id=project_id,
        name=name,
        other_project_name=other_project_name,
    )
    return api_success(data=data)


@router.put(
    "/collections",
    response_model=ApiResponse[None],
    summary="批量全量同步站点集合关联 / Batch Sync Site Collections",
)
def sync_site_collections(
    session: SessionDep,
    current_user: CurrentUser,
    payload: SiteCollectionSyncRequest,
    project_id: int = Query(..., description="当前项目 ID（必填） / Current project ID (required)"),
) -> Any:
    """
    全量同步多个站点在可管理范围内的集合与项目关系。
    / Fully sync collection and project links for multiple sites within manageable scope.
    """
    site_service.sync_site_collections(
        session,
        current_user=current_user,
        project_id=project_id,
        site_ids=payload.site_ids,
        collection_ids=payload.collection_ids,
        project_ids=payload.project_ids,
    )
    return api_success()


@router.delete(
    "/{site_id}",
    response_model=ApiResponse[dict],
    summary="删除站点 / Delete Site",
)
def delete_site(
    session: SessionDep,
    current_user: CurrentUser,
    site_id: int,
    project_id: int | None = Query(None, description="项目 ID / Project ID"),
) -> Any:
    """
    删除指定站点。 / Delete a specific site.

    - 需要当前项目路径下的 site:write 权限。 / Requires site:write on the current project path.
    - 若该站点有关联媒体，则无法删除（返回 409）。
      Returns 409 if the site still has associated media records.
    """
    site_service.delete_site(session, site_id=site_id, current_user=current_user, project_id=project_id)
    return api_success(data={"site_id": site_id})
