"""集合 API 路由（RBAC）。 / Collections API routes (RBAC)."""
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.api.deps import (
    ActiveManager,
    CanWriteProject,
    CurrentUser,
    CurrentUserOptional,
    SessionDep,
)
from app.api.responses import csv_response
from app.core.config import settings
from app.csv_import import attach_import_metadata, parse_import_upload
from app.enums.collection import CollectionSphere
from app.models import Project, User
from app.schemas.collection import (
    CollectionCreate,
    CollectionDetail,
    CollectionPublic,
    CollectionTaxonResponse,
    CollectionTaxonsSet,
    CollectionUpdate,
    CollectionViewResponse,
)
from app.schemas.option import CollectionOption
from app.schemas.response import PagedApiResponse, ApiResponse, api_success
from app.services import collection_service, permission_service
from app.services import tabular_import_service
from app.utils import parse_uuid

router = APIRouter(prefix="/collections", tags=["集合 / collections"])
router_views = APIRouter(tags=["集合 / collections"])


@router.post("/imports", summary="导入集合 / Import Collections")
async def import_collections(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int = Form(...),
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
) -> Any:
    """校验或原子导入集合。 / Validate or atomically import collections."""
    if not permission_service.has_resource_permission(
        session, current_user, "project", "write", project_id=project_id
    ):
        raise HTTPException(status_code=403, detail="No project:write permission")
    parsed = parse_import_upload(file.filename or "", await file.read())
    report = tabular_import_service.import_collections(
        session, parsed.text, current_user, project_id, dry_run=dry_run
    )
    return api_success(message="Import validation completed" if dry_run else "Import completed", data=attach_import_metadata(report, parsed, dry_run=dry_run))


@router_views.get("/collection-sphere-options", response_model=ApiResponse[list[str]], summary="获取领域选项(添加或者修改集合的时候用到) / Get Sphere Options")
def get_sphere_options() -> Any:
    """
    获取下拉菜单的领域选项。 / Get sphere options for dropdown menus.

    返回有效领域值的列表。 / Returns list of valid sphere values.
    """
    return api_success(data=[e.value for e in CollectionSphere])



@router_views.get("/collection-options", response_model=ApiResponse[list[CollectionOption]], summary="获取集合选项 / Get Collection Options")
def get_collection_options(
    session: SessionDep,
    current_user: CurrentUserOptional,
    project_id: Optional[int] = Query(default=None, description="通过项目 ID 筛选 / Filter by project ID"),
    name: Optional[str] = Query(default=None, description="通过名称搜索 / Search in name")
) -> Any:
    """
    获取下拉菜单的集合选项。 / Get collection options for dropdown menus.

    返回包含 ID、名称和 can_manage 标志的简化集合列表。 / Returns simplified collection list with id, name, and can_manage flag.
    - 未登录用户 (Unauthenticated)：必须传递 project_id，仅查看公开项目的公开集合，can_manage=False / Unauthenticated: must provide project_id, see public collections of public project only, can_manage=False
    - 管理员 (Admins)：查看所有集合，can_manage=True / Admins: see all collections, can_manage=True
    - 普通用户 (Regular users)：仅查看可访问的集合，can_manage 基于写入权限 / Regular users: see accessible collections only, can_manage based on write permission
    """
    data = collection_service.get_collection_options(session, current_user, project_id, name)
    return api_success(data=data)


@router.get("", response_model=PagedApiResponse[list[CollectionPublic]], summary="列出集合 / List Collections")
def list_collections(
    session: SessionDep,
    current_user: ActiveManager,
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=settings.DEFAULT_PAGE_LIMIT, ge=1, le=100, description="每页条目数 / Items per page"),
    project_id: Optional[int] = Query(default=None, description="通过项目 ID 筛选 / Filter by project ID"),
    collection_id: Optional[int] = Query(default=None, description="通过集合 ID 筛选（精确） / Filter by collection ID (exact)"),
    uuid: Optional[str] = Query(default=None, description="通过 UUID 筛选（精确） / Filter by UUID (exact)"),
    name: Optional[str] = Query(default=None, description="通过名称筛选（模糊） / Filter by name (fuzzy)"),
    sphere: Optional[str] = Query(default=None, description="通过领域筛选（模糊） / Filter by sphere (fuzzy)"),
    project_url: Optional[str] = Query(default=None, description="通过外部项目 URL 筛选（模糊） / Filter by external project URL (fuzzy)"),
    external_media_url: Optional[str] = Query(default=None, description="通过外部媒体 URL 筛选（模糊） / Filter by external media URL (fuzzy)"),
    doi: Optional[str] = Query(default=None, description="通过 DOI 筛选（模糊） / Filter by DOI (fuzzy)"),
    creator_id: Optional[int] = Query(default=None, description="通过创建者 ID 筛选（精确） / Filter by creator ID (exact)"),
    creator_name: Optional[str] = Query(default=None, description="通过创建者名称模糊筛选（大小写不敏感） / Fuzzy filter by creator name (case-insensitive)"),
    creation_date_from: Optional[datetime] = Query(default=None, description="通过创建起始日期筛选 / Filter by creation date (from)"),
    creation_date_to: Optional[datetime] = Query(default=None, description="通过创建截止日期筛选 / Filter by creation date (to)"),
    public_access: Optional[bool] = Query(default=None, description="通过公共访问权限筛选 / Filter by public access"),
    public_tags: Optional[bool] = Query(default=None, description="通过公共注释筛选 / Filter by public annotations"),
    taxon_name: Optional[str] = Query(default=None, description="通过分类群名称筛选（模糊） / Filter by taxon name (fuzzy)"),
    order_by: Optional[str] = Query(default="collection_id", description="排序字段：collection_id, name, doi, sphere, creator_name, creation_date, public_access, public_tags, taxon_name / Sort field: collection_id, name, doi, sphere, creator_name, creation_date, public_access, public_tags, taxon_name"),
    order_dir: Optional[str] = Query(default="asc", pattern="^(asc|desc)$", description="排序方向：asc 或 desc / Sort direction: asc or desc")
) -> Any:
    """
    列出所有带有分页和搜索功能的集合。 / List all collections with pagination and search.
    
    该接口仅限管理者使用。 / This endpoint is for managers only.
    - 仅查看当前用户具有管理（写）权限的集合。 / Only see collections the current user has management (write) permissions for.
    - 管理员将看到所有集合。 / Admins will see all collections.
    """
    filters = {
        k: v for k, v in {
            "project_id": project_id,
            "collection_id": collection_id,
            "uuid": parse_uuid(uuid),
            "name": name,
            "sphere": sphere,
            "project_url": project_url,
            "external_media_url": external_media_url,
            "doi": doi,
            "creator_id": creator_id,
            "creator_name": creator_name,
            "creation_date_from": creation_date_from,
            "creation_date_to": creation_date_to,
            "public_access": public_access,
            "public_tags": public_tags,
            "taxon_name": taxon_name,
        }.items() if v is not None
    }
    return collection_service.get_collections(
        session, current_user,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
        managed_only=True,
        **filters,
    )


@router.get("/exports", summary="导出集合 / Export Collections")
def export_collections(
    session: SessionDep,
    current_user: ActiveManager,
    project_id: int | None = Query(None, description="项目 ID / Project ID"),
    order_by: str = Query(default="collection_id", description="排序字段 / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向：asc 或 desc / Sort direction"),
):
    """
    以 CSV 格式导出集合。 / Export collections to CSV format.
    
    需要对该项目拥有 project:write 权限。 / Requires project:write permission on the project.
    """
    if project_id is None:
        raise HTTPException(status_code=400, detail="Missing required parameter: project_id")

    csv_content = collection_service.export_collections_csv(
        session,
        current_user,
        project_id=project_id,
        order_by=order_by,
        order_dir=order_dir,
    )
    
    return csv_response(csv_content, "collections.csv")


@router_views.get("/collection-overviews", response_model=ApiResponse[CollectionViewResponse], summary="集合视图数据 / Get Collection View Data")
def get_collection_view(
    session: SessionDep,
    current_user: CurrentUserOptional = None,
    project_id: int = Query(..., description="项目 ID / Project ID"),
    collection_id: int = Query(..., description="集合 ID / Collection ID"),
) -> Any:
    """
    获取集合视图页数据。 / Get collection view page data.

    返回字段包含：
    - 项目基础信息和项目图片地址 / project basics and project picture URL
    - 集合基础信息以及 sphere、external_media_url、project_url
      / collection basics plus sphere, external_media_url, project_url

    权限规则 / Permission rules:
    - 匿名用户：仅当 project.public=True 且 collection.public_access=True 时可访问
      / Anonymous: only when both project.public=True and collection.public_access=True
    - 登录用户：可访问匿名可访问范围；非公开时需 collection:read 权限
      / Authenticated: can access anonymous-visible scope; for private data requires collection:read
    - collection_id 必须属于 project_id，否则返回 400
      / collection_id must belong to project_id, otherwise returns 400
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    collection = collection_service.get_collection_with_relations(session, collection_id)

    is_public_scope = permission_service.can_access_collection(session, None, project_id, collection_id, "read")
    if not is_public_scope:
        if current_user is None:
            raise HTTPException(status_code=403, detail="Access denied")
        if not permission_service.can_access_collection(session, current_user, project_id, collection_id, "read"):
            raise HTTPException(status_code=403, detail="Access denied")

    data = collection_service.build_collection_view_data(project, collection)
    return api_success(data=data)


@router.get("/{collection_id}", response_model=ApiResponse[CollectionDetail], summary="获取集合 / Get Collection")
def get_collection(
    session: SessionDep,
    collection_id: int,
    current_user: CurrentUser,
) -> Any:
    """
    通过 ID 获取集合。 / Get a collection by ID.

    需要对该集合拥有 collection:write 权限。 / Requires collection:write permission on the collection.
    """
    collection = collection_service.get_collection(session, collection_id, current_user)
    detail = CollectionDetail.model_validate(collection)
    detail.project_ids = [pc.project_id for pc in collection.project_collections]
    detail.creator_name = collection.creator.name if collection.creator else ""
    return api_success(data=detail)


@router.post("", response_model=ApiResponse[None], status_code=201, summary="创建集合 / Create Collection")
def create_collection(
    session: SessionDep,
    collection_in: CollectionCreate,
    current_user: User = CanWriteProject,
    project_id: int = Query(..., description="项目 ID / Project ID")
) -> Any:
    """
    创建新集合。 / Create a new collection.

    需要对该项目拥有 project:write 权限。 / Requires project:write permission on the project.
    """
    collection_service.create_collection(session, collection_in, current_user, project_id=project_id)
    return api_success()


@router.patch(
    "/{collection_id}",
    response_model=ApiResponse[None],
    summary="更新集合 / Update Collection"
)
def update_collection(
    session: SessionDep,
    collection_id: int,
    collection_in: CollectionUpdate,
    current_user: CurrentUser,
) -> Any:
    """
    更新集合。 / Update a collection.

    需要对该集合拥有 collection:write 权限。 / Requires collection:write permission on the collection.
    """
    collection_service.update_collection(session, collection_id, collection_in, current_user)
    return api_success()


@router.delete("/{collection_id}", response_model=ApiResponse, summary="删除集合 / Delete Collection")
def delete_collection(
    session: SessionDep,
    collection_id: int,
    current_user: CurrentUser,
) -> ApiResponse:
    """
    删除集合。 / Delete a collection.

    需要对该集合任一关联项目拥有 project:write 权限。 / Requires project:write permission on any project linked to the collection.
    """
    return collection_service.delete_collection(session, collection_id, current_user)


@router.get("/{collection_id}/taxons", response_model=ApiResponse[list[CollectionTaxonResponse]], summary="获取集合分类群 / Get Collection Taxons")
def list_collection_taxons(
    session: SessionDep,
    collection_id: int,
    current_user: CurrentUser,
) -> Any:
    """
    获取与集合关联的所有分类群。 / Get all taxons associated with a collection.
    
    如果用户在任一项目路径上对该集合拥有读取权限，则可见。
    / Visible if the user has read access to the collection on any linked project path.
    """
    permission_service.require_any_collection_path_permission(
        session,
        current_user,
        "collection",
        "read",
        collection_id=collection_id,
    )
    taxons = collection_service.list_collection_taxons(session, collection_id, current_user)
    return api_success(data=taxons)


@router.put(
    "/{collection_id}/taxons",
    response_model=ApiResponse[None],
    summary="设置集合分类群 / Set Collection Taxons"
)
def update_collection_taxons(
    session: SessionDep,
    collection_id: int,
    taxons_in: CollectionTaxonsSet,
    current_user: CurrentUser,
) -> Any:
    """
    设置集合的所有分类群（批量替换）。 / Set all taxons for a collection (wholesale replace).
    
    需要在任一项目路径上拥有 collection:write 权限。
    / Requires collection:write permission on any linked project path.
    """
    permission_service.require_any_collection_path_permission(
        session,
        current_user,
        "collection",
        "write",
        collection_id=collection_id,
    )
    collection_service.update_collection_taxons(session, collection_id, taxons_in, current_user)
    return api_success()
