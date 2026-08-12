"""项目 API 路由（RBAC）。 / Projects API routes (RBAC)."""
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import (
    ActiveAdmin,
    ActiveManager,
    CanWriteProject,
    CurrentUserOptional,
    SessionDep,
)
from app.api.responses import csv_response
from app.core.config import settings
from app.models import User
from app.schemas.option import ProjectOption
from app.schemas.project import (
    ProjectCardPublic,
    ProjectCollectionLinkOptionsResponse,
    ProjectCollectionSyncRequest,
    ProjectCreate,
    ProjectDetail,
    ProjectPublic,
    ProjectUpdate,
)
from app.schemas.project_overview import ProjectOverviewResponse
from app.schemas.response import PagedApiResponse, ApiResponse, api_success
from app.services import permission_service, project_service, statistics_service
from app.utils import parse_uuid

router = APIRouter(prefix="/projects", tags=["项目 / projects"])
router_views = APIRouter(tags=["项目 / projects"])


@router_views.get("/project-options", response_model=ApiResponse[list[ProjectOption]], summary="获取项目选项 / Get Project Options")
def get_project_options(
    session: SessionDep,
    current_user: CurrentUserOptional,
    name: Optional[str] = Query(default=None, description="通过名称搜索 / Search in name")
) -> Any:
    """
    获取下拉菜单的项目选项。 / Get project options for dropdown menus.

    返回包含 ID、名称和 can_manage 标志的简化项目列表。 / Returns simplified project list with id, name, and can_manage flag.
    - 匿名用户 (Anonymous)：仅公开项目，can_manage=False / Anonymous: public projects only, can_manage=False
    - 普通用户 (Regular users)：公开项目 + 可访问项目，can_manage 基于写入权限 / Regular users: public + accessible projects, can_manage based on write permission
    - 管理员 (Admins)：所有项目，can_manage=True / Admins: all projects, can_manage=True
    """
    data = project_service.get_project_options(session, current_user, name)
    return api_success(data=data)


@router_views.get(
    "/project-directory-items",
    response_model=ApiResponse[list[ProjectCardPublic]],
    summary="获取项目卡片列表 / Get Project Cards",
)
def get_project_cards(
    session: SessionDep,
    current_user: CurrentUserOptional,
    name: Optional[str] = Query(default=None, description="通过名称搜索 / Search in name"),
) -> Any:
    """
    获取项目卡片列表（返回全部 active=true，按 project_id 升序）。 / Get project cards (all active=true, ordered by project_id asc).

    权限不用于过滤列表，统一返回全部 active 项目。 / Permission does not filter the list; all active projects are returned.
    权限信息通过 can_access 字段表达，用于前端控制跳转。 / Permission is exposed via can_access for frontend navigation control.
    """
    data = project_service.get_active_project_cards(session, current_user, name)
    return api_success(data=data)


@router.get("", response_model=PagedApiResponse[list[ProjectPublic]], summary="列出项目 / List Projects")
def list_projects(
    session: SessionDep,
    current_user: ActiveManager,
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=settings.DEFAULT_PAGE_LIMIT, ge=1, le=100, description="每页条目数 / Items per page"),
    name: Optional[str] = Query(default=None, description="通过名称搜索 / Search in name"),
    url: Optional[str] = Query(default=None, description="通过 URL 搜索 / Search in url"),
    project_id: Optional[int] = Query(default=None, description="通过项目 ID 筛选 / Filter by project ID"),
    uuid: Optional[str] = Query(default=None, description="通过 UUID 筛选 / Filter by UUID"),
    doi: Optional[str] = Query(default=None, description="通过 DOI 搜索 / Search in DOI"),
    creator_id: Optional[int] = Query(default=None, description="通过创建者 ID 筛选 / Filter by creator ID"),
    creator_name: Optional[str] = Query(default=None, description="通过创建者名称模糊筛选（大小写不敏感） / Fuzzy filter by creator name (case-insensitive)"),
    creation_date_from: Optional[datetime] = Query(default=None, description="从创建日期筛选 / Filter by creation date (from)"),
    creation_date_to: Optional[datetime] = Query(default=None, description="至创建日期筛选 / Filter by creation date (to)"),
    public: Optional[bool] = Query(default=None, description="通过公开状态筛选 / Filter by public status"),
    active: Optional[bool] = Query(default=None, description="通过活跃状态筛选 / Filter by active status"),
    order_by: Optional[str] = Query(default="project_id", description="排序字段：project_id, name, url, creation_date / Sort field: project_id, name, url, creation_date"),
    order_dir: Optional[str] = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction")
) -> Any:
    """
    列出所有带有分页 and 搜索功能的项目。 / List all projects with pagination and search.

    - 管理者/管理员 (Managers/Admins)：可以查看所有项目或他们拥有管理权限的项目。 / Managers/Admins: can see all projects or projects they have manage access to.
    - 普通用户 (Regular users)：禁止访问 (403)。 / Regular users: forbidden (403).
    
    搜索字段：name, url, project_id, uuid, doi, creator_id, creation_date, public, active / Search fields: name, url, project_id, uuid, doi, creator_id, creation_date, public, active
    """
    filters = {
        k: v for k, v in {
            "name": name,
            "url": url,
            "project_id": project_id,
            "uuid": parse_uuid(uuid),
            "doi": doi,
            "creator_id": creator_id,
            "creator_name": creator_name,
            "creation_date_from": creation_date_from,
            "creation_date_to": creation_date_to,
            "public": public,
            "active": active,
        }.items() if v is not None
    }
    return project_service.get_projects(
        session, current_user,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
        **filters,
    )


@router.get("/exports", summary="导出项目 / Export Projects")
def export_projects(
    session: SessionDep,
    current_user: ActiveManager,
    project_id: Optional[int] = Query(default=None, description="通过项目 ID 筛选 / Filter by project ID"),
    collection_id: Optional[int] = Query(default=None, description="通过集合 ID 筛选 / Filter by collection ID"),
    order_by: str = Query(default="project_id", description="排序字段 / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向：asc 或 desc / Sort direction"),
):
    """
    以 CSV 格式导出项目数据。 / Export project data to CSV format.

    - 仅限管理者/管理员。 / Managers/Admins only.
    - project_id 和 collection_id 是可选的筛选器。 / project_id and collection_id are optional filters.
    """
    csv_content = project_service.export_projects_csv(
        session, current_user,
        project_id=project_id,
        collection_id=collection_id,
        order_by=order_by,
        order_dir=order_dir,
    )

    return csv_response(csv_content, "projects.csv")


@router_views.get(
    "/project-overviews",
    response_model=ApiResponse[ProjectOverviewResponse],
    summary="获取项目/集合概览 / Get Project or Collection Summary",
)
def get_project_summary(
    session: SessionDep,
    current_user: CurrentUserOptional,
    project_id: int = Query(..., description="项目 ID（必填） / Project ID (required)"),
    collection_id: Optional[int] = Query(default=None, description="集合 ID（可选），传入后返回集合维度数据 / Collection ID (optional), returns collection-scoped data when provided"),
) -> Any:
    """
    获取项目或集合的概览数据（统计数字 + 贡献者列表）。 / Get overview data (stats + contributors) for a project or collection.

    统计字段语义 / Stats field semantics:
    - audios: audio 类型媒体数量 / Count of audio media
    - photos: photo 类型媒体数量 / Count of photo media

    权限规则 / Permission rules:
    - 未登录用户 (Anonymous)：只能访问 public=True 的项目或 public_access=True 的集合
    - 登录用户 (Authenticated)：需对目标项目/集合具备 read 权限

    当传入 collection_id 时 / When collection_id is provided:
    - collection_id 必须属于 project_id，否则返回 400 / collection_id must belong to project_id, otherwise 400
    - 返回集合维度的统计数据和贡献者 / Returns collection-scoped stats and contributors

    不传 collection_id 时 / When collection_id is not provided:
    - 返回项目维度的统计数据和贡献者 / Returns project-scoped stats and contributors

    贡献者列表 / Contributors list:
    - 创建者放在第一位 / Creator is placed first
    - 其他贡献者从 ProjectContributor/CollectionContributor 表查询 / Other contributors queried from contributor tables
    """
    if not permission_service.can_access_project(session, current_user, project_id, "read"):
        raise HTTPException(status_code=403, detail="Access denied")

    if collection_id is not None:
        if not permission_service.can_access_collection(session, current_user, project_id, collection_id, "read"):
            raise HTTPException(status_code=403, detail="Access denied")

    data = statistics_service.get_project_summary(session, project_id, collection_id)
    return api_success(data=data)


@router.get(
    "/{project_id}/collection-options",
    response_model=ApiResponse[ProjectCollectionLinkOptionsResponse],
    summary="获取项目关联集合弹窗数据 / Get Project Collection Link Options",
)
def get_project_collection_link_options(
    session: SessionDep,
    project_id: int,
    current_user: User = CanWriteProject,
    name: Optional[str] = Query(default=None, description="按集合名称搜索 / Search by collection name"),
    other_project_name: Optional[str] = Query(default=None, description="按其他项目名称搜索 / Search by other project name"),
) -> Any:
    """
    获取“关联集合”弹窗数据。 / Get grouped data for project-collection link dialog.

    分组规则 / Grouping rules:
    - 当前项目集合（默认 selected=true） / Current project collections (selected=true)
    - 其他可管理项目集合（剔除当前项目已有集合） / Other manageable projects (excluding current project's collections)
    - 不属于任何项目的集合 / Collections not linked to any project
    """
    data = project_service.get_project_collection_link_options(
        session,
        project_id,
        current_user,
        name=name,
        other_project_name=other_project_name,
    )
    return api_success(data=data)


@router.put(
    "/{project_id}/collections",
    response_model=ApiResponse[None],
    summary="全量同步项目集合关联 / Sync Project Collections",
)
def sync_project_collections(
    session: SessionDep,
    project_id: int,
    payload: ProjectCollectionSyncRequest,
    current_user: User = CanWriteProject,
) -> Any:
    """
    全量同步项目与集合关系。 / Fully sync project-collection links.

    以请求中的 collection_ids 作为最终状态：新增缺失关联，移除未勾选关联。
    / Treat request collection_ids as final state: add missing links and remove unchecked links.
    """
    project_service.sync_project_collections(
        session,
        project_id,
        current_user,
        payload.collection_ids,
    )
    return api_success()


@router.get("/{project_id}", response_model=ApiResponse[ProjectDetail], summary="获取项目 / Get Project")
def get_project(
    session: SessionDep,
    project_id: int,
    current_user: CurrentUserOptional
) -> Any:
    """
    通过 ID 获取项目。 / Get a project by ID.

    - 公开项目 (Public projects)：所有人可见 / Public projects: visible to everyone
    - 私有项目 (Private projects)：仅对拥有 project:read 权限的用户或管理员可见 / Private projects: visible to users with project:read permission or admins
    """
    project = project_service.get_project(session, project_id, current_user)
    p_dict = project.model_dump()
    p_dict["creator_name"] = project.creator.name if getattr(project, "creator", None) else ""

    detail = ProjectDetail(**ProjectPublic.model_validate(p_dict).model_dump())
    return api_success(data=detail)


@router.post(
    "",
    response_model=ApiResponse[dict[str, int]],
    status_code=201,
    summary="创建项目 / Create Project"
)
def create_project(
    session: SessionDep,
    project_in: ProjectCreate,
    current_user: ActiveAdmin
) -> Any:
    """
    创建新项目。 / Create a new project.

    仅限管理员。 / Admin only.
    """
    project_id = project_service.create_project(session, project_in, current_user)
    return api_success(data={"project_id": project_id})


@router.patch(
    "/{project_id}",
    response_model=ApiResponse[None],
    summary="更新项目 / Update Project"
)
def update_project(
    session: SessionDep,
    project_id: int,
    project_in: ProjectUpdate,
    _current_user: User = CanWriteProject
) -> Any:
    """
    更新项目。 / Update a project.

    需要对该项目拥有 project:write 权限。 / Requires project:write permission on the project.
    """
    project_service.update_project(session, project_id, project_in)
    return api_success()


@router.delete("/{project_id}", response_model=ApiResponse, summary="删除项目 / Delete Project")
def delete_project(
    session: SessionDep,
    project_id: int,
    current_user: ActiveAdmin
) -> ApiResponse:
    """
    删除项目。 / Delete a project.

    仅限管理员。 / Admin only.
    """
    return project_service.delete_project(session, project_id, current_user)
