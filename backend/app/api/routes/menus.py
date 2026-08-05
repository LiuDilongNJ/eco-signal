"""菜单 API 路由。 / Menus API routes."""
from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, SessionDep
from app.repositories import permission_repository
from app.schemas.menu import MenuItemPublic
from app.schemas.response import ApiResponse, api_success
from app.services import menu_service

router = APIRouter(tags=["菜单 / menus"])


@router.get(
    "/current-user/menu-items",
    response_model=ApiResponse[list[MenuItemPublic]],
    summary="获取当前用户菜单项 / Get Current User Menu Items",
)
def get_current_user_menu_items(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int = Query(..., description="项目 ID / Project ID"),
    collection_id: int | None = Query(default=None, description="集合 ID / Collection ID"),
) -> Any:
    """
    查询当前用户在指定项目下的菜单可见性。 / Return current-user menu visibility scoped to the given project.
    """
    return api_success(
        data=menu_service.get_current_user_menu_items(
            session,
            current_user,
            permission_repository,
            project_id=project_id,
            collection_id=collection_id,
        )
    )
