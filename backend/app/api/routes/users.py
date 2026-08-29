"""用户 API 路由。 / Users API routes."""
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.api.deps import (
    ActiveManager,
    CurrentUser,
    SessionDep,
)
from app.api.responses import csv_response
from app.csv_import import attach_import_metadata, parse_import_upload
from app.core.config import settings
from app.repositories import permission_repository
from app.schemas import (
    AdminUpdatePassword,
    UpdatePassword,
    UserCreate,
    UserUpdate,
    UserUpdateMe,
)
from app.schemas.response import PagedApiResponse, ApiResponse, api_success
from app.schemas.user import (
    SetContributorRequest,
    CreatorOption,
    CurrentUserPublic,
    UserListPublic,
    UserPreferenceUpdate,
    UserPublic,
)
from app.services import permission_service, tabular_import_service, user_service

router = APIRouter(prefix="/users", tags=["用户 / users"])
router_views = APIRouter(tags=["用户 / users"])


@router.post("/imports", summary="导入用户 / Import Users")
async def import_users(
    session: SessionDep,
    current_user: ActiveManager,
    project_id: int = Form(...),
    collection_id: int | None = Form(None),
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
) -> Any:
    """校验或原子导入用户。 / Validate or atomically import users."""
    resource_type = "collection" if collection_id is not None else "project"
    if not permission_service.has_resource_permission(
        session,
        current_user,
        resource_type,
        "write",
        project_id=project_id,
        collection_id=collection_id,
    ):
        raise HTTPException(status_code=403, detail="No write permission on target scope")
    parsed = parse_import_upload(file.filename or "", await file.read())
    report = tabular_import_service.import_users(
        session,
        parsed.text,
        current_user,
        project_id,
        collection_id,
        dry_run=dry_run,
    )
    return api_success(message="Import validation completed" if dry_run else "Import completed", data=attach_import_metadata(report, parsed, dry_run=dry_run))


@router.get(
    "",
    response_model=PagedApiResponse[list[UserListPublic]],
    summary="列出用户 / List Users"
)
def list_users(
    session: SessionDep,
    current_user: ActiveManager,
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=settings.DEFAULT_PAGE_LIMIT, ge=1, le=100, description="每页条目数 / Items per page"),
    user_id: int | None = Query(default=None, description="通过 ID 搜索 / Search by ID"),
    username: str | None = Query(default=None, description="通过用户名搜索 / Search by username"),
    name: str | None = Query(default=None, description="通过姓名搜索 / Search by name"),
    email: str | None = Query(default=None, description="通过邮箱搜索 / Search by email"),
    orcid: str | None = Query(default=None, description="通过 ORCID 搜索 / Search by ORCID"),
    color: str | None = Query(default=None, description="通过颜色值模糊筛选（大小写不敏感） / Fuzzy filter by color hex value (case-insensitive)"),
    active: bool | None = Query(default=None, description="通过活跃状态筛选 / Filter by active status"),
    project_id: int | None = Query(default=None, description="通过项目 ID 筛选 / Filter by project ID"),
    collection_id: int | None = Query(default=None, description="通过集合 ID 筛选 / Filter by collection ID"),
    scope: Literal["current", "all"] = Query(default="current", description="范围模式：current=按 project_id/collection_id 过滤；all=仅用于 contrib 关联上下文，不作为筛选条件 / Scope mode: current=filter by project_id/collection_id; all=use as contrib context only"),
    contrib: str | None = Query(default=None, description="贡献者角色模糊筛选（需配合 project_id 或 collection_id 才生效）/ Fuzzy filter by contributor role (effective only with project_id or collection_id)"),
    order_by: str = Query(default="user_id", description="排序字段：user_id, username, name, email, orcid, active, contrib（仅在 project_id 或 collection_id 上下文生效） / Sort field: user_id, username, name, email, orcid, active, contrib (effective only with project_id or collection_id context)"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction")
) -> Any:
    """
    检索支持搜索和排序的用户。 / Retrieve users with search and sorting support.

    数据权限：管理员不受限；项目管理者仅可见自己管理项目下的用户；集合管理者仅可见自己所属集合下的用户。
    Data permission: Admin sees all; project managers see users in managed projects; collection managers see users in managed collections.
    """
    return user_service.list_users(
        session,
        current_user=current_user,
        page=page,
        page_size=page_size,
        user_id=user_id,
        username=username,
        name=name,
        email=email,
        orcid=orcid,
        color=color,
        active=active,
        project_id=project_id,
        collection_id=collection_id,
        scope=scope,
        contribution_role=contrib,
        order_by=order_by,
        order_dir=order_dir
    )


@router.get(
    "/creators",
    response_model=ApiResponse[list[CreatorOption]],
    summary="列出 Creator 候选用户 / List Creator candidates",
)
def list_creator_candidates(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int = Query(..., description="项目 ID / Project ID"),
    collection_id: int | None = Query(default=None, description="集合 ID / Collection ID"),
) -> Any:
    """返回媒体 Creator 候选用户。 / Return users eligible to be assigned as media creators."""
    return user_service.list_creator_options(
        session,
        current_user=current_user,
        project_id=project_id,
        collection_id=collection_id,
    )


@router.get(
    "/exports",
    summary="导出用户 / Export Users"
)
def export_users(
    session: SessionDep,
    current_user: ActiveManager,
    color: str | None = Query(default=None, description="颜色值模糊筛选（大小写不敏感） / Fuzzy filter by color hex value (case-insensitive)"),
    project_id: int | None = Query(default=None, description="项目 ID / Project ID"),
    collection_id: int | None = Query(default=None, description="集合 ID / Collection ID"),
    scope: Literal["current", "all"] = Query(
        default="current",
        description="范围模式：current=按 project_id/collection_id 过滤；all=仅用于贡献者关联上下文，不作为筛选条件 / Scope mode: current=filter by project_id/collection_id; all=use as contributor context only",
    ),
    order_by: str = Query(default="user_id", description="排序字段：user_id, username, name, email, orcid, active, contrib（仅在 project_id 或 collection_id 上下文生效） / Sort field: user_id, username, name, email, orcid, active, contrib (effective only with project_id or collection_id context)"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向：asc 或 desc / Sort direction"),
):
    """
    以 CSV 格式导出用户（数据权限与用户列表一致）。`current` 按项目/集合收窄结果，`all` 仅将其用于贡献者关联。 / Export users to CSV format (same data permission as list endpoint). `current` narrows results by project/collection, while `all` uses them only for contributor context.

    需要管理者权限。 / Requires manager permission.
    数据权限：管理员导出所有用户；项目管理者导出所管理项目下的用户；集合管理者导出所属集合下的用户。
    Data permission: Admin exports all; project managers export users in managed projects; collection managers export users in managed collections.
    """
    csv_content = user_service.export_users_csv(
        session,
        current_user=current_user,
        color=color,
        project_id=project_id,
        collection_id=collection_id,
        scope=scope,
        order_by=order_by,
        order_dir=order_dir,
    )

    return csv_response(csv_content, "users.csv")


@router.post(
    "",
    response_model=ApiResponse[None],
    summary="创建用户 / Create User"
)
def create_user(
    *,
    session: SessionDep,
    current_user: ActiveManager,
    user_in: UserCreate,
    project_id: int = Query(..., description="所属项目 ID（必填）/ Owning project ID (required)"),
    collection_id: int | None = Query(default=None, description="所属集合 ID（可选）/ Owning collection ID (optional)"),
) -> Any:
    """
    创建新用户，并自动绑定到指定项目或集合。 / Create a new user and bind them to a project or collection.

    权限规则 / Permission rules:
    - 若传递 collection_id：当前用户须具备该集合的写权限（collection:write），新用户将获得该集合读权限（collection:read）以及所属项目的读权限（project:read）。
      If collection_id provided: current user must have collection:write; new user gets collection:read and project:read.
    - 若未传递 collection_id：当前用户须具备该项目的写权限（project:write），新用户将获得该项目读权限（project:read）。
      If not: current user must have project:write; new user gets project:read.
    - 新用户始终为普通用户角色。 / New users are always created with the normal user role.
    """
    user_service.create_user(
        session,
        current_user=current_user,
        user_in=user_in,
        project_id=project_id,
        collection_id=collection_id,
    )
    return api_success()


@router_views.patch("/current-user", response_model=ApiResponse[None], summary="更新个人信息 / Update Me")
def update_user_me(
        *, session: SessionDep, user_in: UserUpdateMe, current_user: CurrentUser
) -> Any:
    """
    更新当前用户。 / Update own user.
    """
    user_service.update_user_me(session, user_in, current_user)
    return api_success()


@router_views.patch(
    "/current-user/preferences",
    response_model=ApiResponse[None],
    summary="更新个人偏好设置 / Update My Preferences"
)
def update_user_preference(
        *, session: SessionDep, pref_in: UserPreferenceUpdate, current_user: CurrentUser
) -> Any:
    """
    更新当前用户的偏好设置（FFT 大小、主题、语言等）。 / Update current user's preferences (FFT size, theme, language, etc.).

    - `fft`：声谱图默认 FFT 窗口大小，可选值：128 / 256 / 512 / 1024 / 2048 / 4096。 / Default FFT window size for spectrograms.
    - `theme`：界面主题（light / dark / auto）。 / Interface theme.
    - `language`：界面语言代码（如 zh / en）。 / Interface language code.
    - `timezone`：时区（如 Asia/Shanghai）。 / Timezone.
    - `notifications_enabled`：是否启用通知。 / Enable notifications.

    若用户尚无偏好记录，将自动创建。 / Creates the preference record if it does not exist yet.
    """
    user_service.update_user_preference(session, pref_in, current_user)
    return api_success()


@router_views.put("/current-user/password-credential", response_model=ApiResponse, summary="修改个人密码 / Update My Password")
def update_password_me(
        *, session: SessionDep, body: UpdatePassword, current_user: CurrentUser
) -> Any:
    """
    更新当前用户密码。 / Update own password.
    """
    return user_service.update_password_me(
        session, body.current_password, body.new_password, current_user
    )


@router_views.get("/current-user", response_model=ApiResponse[CurrentUserPublic], summary="获取当前用户 / Get Me")
def read_user_me(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int | None = Query(default=None, description="项目 ID（选填）/ Project ID (optional)"),
    collection_id: int | None = Query(default=None, description="集合 ID（选填）/ Collection ID (optional)"),
) -> Any:
    """
    获取当前用户。 / Get current user.
    """
    is_project_admin = permission_service.is_admin(current_user)
    if not is_project_admin:
        if project_id is not None:
            is_project_admin = permission_service.has_resource_permission(
                session,
                current_user,
                "project",
                "write",
                project_id=project_id,
            )
        elif current_user.user_id is not None:
            is_project_admin = bool(
                permission_repository.get_project_ids_with_write_permission(
                    session,
                    current_user.user_id,
                )
            )

    can_write_audio = False
    if project_id is not None:
        if collection_id is not None:
            can_write_audio = permission_service.has_resource_permission(
                session,
                current_user,
                "audio",
                "write",
                project_id=project_id,
                collection_id=collection_id,
            )
        elif permission_service.is_admin(current_user):
            can_write_audio = bool(
                permission_repository.get_project_collection_ids(session, project_id)
            )
        elif current_user.user_id is not None:
            can_write_audio = permission_repository.has_effective_collection_permission_in_project(
                session,
                current_user.user_id,
                "audio",
                "write",
                project_id,
            )

    data = CurrentUserPublic.model_validate(
        {
            **current_user.model_dump(),
            "preference": current_user.preference,
            "is_admin": permission_service.is_admin(current_user),
            "is_project_admin": is_project_admin,
            "can_write_audio": can_write_audio,
        }
    )
    return api_success(data=data)


@router.get("/{user_id}", response_model=ApiResponse[UserPublic], summary="获取特定用户 / Get User")
def read_user_by_id(
        user_id: int, session: SessionDep, current_user: CurrentUser
) -> Any:
    """
    通过 ID 获取特定用户。 / Get a specific user by id.
    
    管理者仅能查看其管理范围内的用户，普通用户仅能查看其自身。 / Managers can only view users within their scope, regular users can only view themselves.
    """
    user = user_service.get_user_by_id(session, user_id, current_user)
    return api_success(
        data=UserPublic.model_validate(
            {
                **user.model_dump(),
                "preference": user.preference,
                "is_admin": permission_service.is_admin(user),
            }
        )
    )


@router.patch(
    "/{user_id}",
    response_model=ApiResponse[None],
    summary="更新用户 / Update User"
)
def update_user(
        *,
        session: SessionDep,
        current_user: ActiveManager,
        user_id: int,
        user_in: UserUpdate,
) -> Any:
    """
    更新用户（此处不能更新密码）。 / Update a user (password cannot be updated here).
    
    管理者仅能更新其管理范围内的用户。 / Managers can only update users within their scope.
    """
    user_service.update_user(session, user_id, user_in, current_user)
    return api_success()


@router.put(
    "/{user_id}/password-credential",
    response_model=ApiResponse,
    summary="管理员/管理者重置用户密码 / Reset User Password"
)
def admin_update_user_password(
        *,
        session: SessionDep,
        current_user: ActiveManager,
        user_id: int,
        body: AdminUpdatePassword,
) -> Any:
    """
    更新用户密码。 / Update a user's password.
    
    管理者仅能重置其管理范围内的用户密码。 / Managers can only reset passwords for users within their scope.
    """
    return user_service.admin_update_password(session, user_id, body.new_password, current_user)


@router.delete(
    "/{user_id}",
    response_model=ApiResponse,
    summary="删除用户 / Delete User"
)
def delete_user(
        session: SessionDep, current_user: ActiveManager, user_id: int
) -> ApiResponse:
    """
    删除用户。 / Delete a user.
    
    管理者仅能删除其管理范围内的用户。 / Managers can only delete users within their scope.
    """
    return user_service.delete_user(session, user_id, current_user)


@router.put(
    "/{user_id}/contributors",
    response_model=ApiResponse,
    summary="设置用户贡献者角色 / Set User Contributor"
)
def set_user_contributor(
        *,
        session: SessionDep,
        current_user: ActiveManager,
        user_id: int,
        body: SetContributorRequest,
) -> Any:
    """
    将用户设置为项目或集合贡献者。 / Set a user as a project or collection contributor.
    
    如果提供了 collection_id，则设置集合贡献者（需具备写权限）。 / If collection_id, sets collection contributor (requires write permission).
    否则，根据 project_id 设置项目贡献者（需具备写权限）。 / Otherwise, sets project contributor (requires write permission).
    """
    return user_service.set_contributor(session, user_id, body, current_user)
