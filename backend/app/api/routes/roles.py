"""角色 API 路由。 / Roles API routes."""
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep, get_current_active_superuser
from app.schemas.response import ApiResponse
from app.schemas.role import UserRoleUpdate
from app.services import user_service

router = APIRouter(tags=["角色 / roles"])


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
