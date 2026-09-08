"""角色 API 路由。 / Roles API routes."""
from typing import Any

from fastapi import APIRouter

from app.api.deps import ActiveManager, SessionDep
from app.schemas.response import ApiResponse, api_success
from app.schemas.role import AccessRolePublic
from app.services import permission_config_service

router = APIRouter(tags=["角色 / roles"])


@router.get(
    "/roles",
    response_model=ApiResponse[list[AccessRolePublic]],
    summary="获取访问角色 / List access roles",
)
def list_access_roles(
    session: SessionDep,
    _current_user: ActiveManager,
    kind: str = "access",
) -> Any:
    """获取可分配的项目和集合路径角色。 / List assignable project and collection roles."""
    if kind != "access":
        return api_success(data=[])
    return api_success(data=permission_config_service.list_access_roles(session))
