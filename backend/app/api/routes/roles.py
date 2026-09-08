"""角色 API 路由。 / Roles API routes."""
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import ActiveManager, SessionDep, get_current_active_superuser
from app.schemas.response import ApiResponse, api_success
from app.schemas.role import AccessRolePublic, UserRoleUpdate
from app.services import permission_config_service, user_service

router = APIRouter(tags=["角色 / roles"])


@router.get(
    "/roles",
    response_model=ApiResponse[list[AccessRolePublic]],
    summary="获取访问角色 / List access roles",
)
def list_access_roles(
    session: SessionDep,
    current_user: ActiveManager,
    kind: str = "access",
) -> Any:
    """获取可分配的项目和集合路径角色。 / List assignable project and collection roles."""
    if kind != "access":
        return api_success(data=[])
    return api_success(data=permission_config_service.list_access_roles(session))


@router.put(
    "/users/{user_id}/role-assignment",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=ApiResponse,
    summary="更新用户角色 / Update User Role"
)
def update_user_role(
    user_id: int,
    role_update: UserRoleUpdate,
    session: SessionDep
) -> Any:
    """
    更新用户角色（管理员切换）。 / Update a user's role (admin toggle).

    仅限管理员。 / Admin only.
    """
    return user_service.update_user_role(
        session=session,
        user_id=user_id,
        is_admin=role_update.is_admin
    )
