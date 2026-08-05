"""权限 API 路由；项目与集合范围用户权限。 / Permissions at project and collection scope."""
from typing import Any

from fastapi import APIRouter

from app.api.deps import (
    ActiveManager,
    SessionDep,
)
from app.schemas.permission import (
    UserPermissionConfig,
    UserPermissionSyncRequest,
)
from app.schemas.response import ApiResponse, api_success
from app.services import permission_service

user_permissions_router = APIRouter(tags=["权限 / permissions"])


@user_permissions_router.get(
    "/users/{user_id}/permission-configuration",
    response_model=ApiResponse[UserPermissionConfig],
    summary="获取用户权限配置快照 / Get User Permission Config"
)
def get_user_permission_config(
    session: SessionDep,
    user_id: int,
    current_user: ActiveManager,
) -> Any:
    """
    获取用于渲染权限配置页面的完整数据快照。 / Get a complete data snapshot for rendering the permission config page.

    返回所有项目及其集合的树形结构，节点同时包含可编辑的 stored_permissions
    与只读的 effective_permissions。
    / Returns the project tree with editable stored_permissions and read-only
    effective_permissions.

    需要管理者权限。 / Requires manager permission.
    """
    data = permission_service.get_user_permission_config(session, user_id, current_user)
    return api_success(data=UserPermissionConfig(**data))


@user_permissions_router.put(
    "/users/{user_id}/permissions",
    response_model=ApiResponse[None],
    summary="同步用户权限 / Sync User Permissions"
)
def sync_user_permissions_global(
    session: SessionDep,
    user_id: int,
    request: UserPermissionSyncRequest,
    current_user: ActiveManager,
) -> Any:
    """
    统一同步用户权限。 / Unified user permission sync.

    - is_admin：设置/取消管理员角色（仅管理员可操作）。 / Set/unset admin role (admin only).
    - projects：按项目树批量同步项目级和项目内集合级权限。
      / Batch sync project and project-local collection permissions using the tree payload.

    管理者仅能修改其拥有写权限的项目/集合范围。 / Managers can only modify scopes where they have write permission.
    """
    permission_service.sync_user_permissions_global(
        session, user_id, request, current_user
    )
    return api_success(message="Permissions synced successfully")
