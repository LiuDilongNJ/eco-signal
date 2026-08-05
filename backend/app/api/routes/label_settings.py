"""标签设置 API 路由。 / Label settings API routes."""
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep, get_current_active_superuser
from app.api.responses import csv_response
from app.models.user import User
from app.schemas.label import (
    LabelAdminCreateRequest,
    LabelAdminPublic,
    LabelAdminUpdateRequest,
)
from app.schemas.response import (
    PagedApiResponse,
    ApiResponse,
    ApiResponse,
    api_page,
    api_success,
)
from app.services import label_service

router = APIRouter(prefix="/label-settings", tags=["标签设置 / label settings"])


def _label_filters(
    *,
    label_id: int | None,
    name: str | None,
    type: str | None,
    creator_id: int | None,
    creator_name: str | None,
    creation_date_from: datetime | None,
    creation_date_to: datetime | None,
) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "label_id": label_id,
            "name": name,
            "type": type,
            "creator_id": creator_id,
            "creator_name": creator_name,
            "creation_date_from": creation_date_from,
            "creation_date_to": creation_date_to,
        }.items()
        if value is not None
    }


@router.get(
    "",
    response_model=PagedApiResponse[list[LabelAdminPublic]],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取标签设置列表 / List Label Settings",
)
def list_label_settings(
    session: SessionDep,
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数 / Page size"),
    label_id: Optional[int] = Query(default=None, description="标签 ID 精确筛选 / Filter by label ID (exact)"),
    name: Optional[str] = Query(default=None, description="名称模糊搜索 / Fuzzy search by name"),
    type: Optional[str] = Query(default=None, description="类型模糊筛选，如 private / public / Fuzzy filter by type"),
    creator_id: Optional[int] = Query(default=None, description="创建者 ID 精确筛选 / Filter by creator ID"),
    creator_name: Optional[str] = Query(default=None, description="创建者名称模糊筛选（大小写不敏感） / Fuzzy filter by creator name (case-insensitive)"),
    creation_date_from: Optional[datetime] = Query(default=None, description="创建日期起 / Creation date from"),
    creation_date_to: Optional[datetime] = Query(default=None, description="创建日期止 / Creation date to"),
    order_by: str = Query(default="label_id", description="排序字段 / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    """
    管理员分页查询所有标签设置。 / Admin-only paginated label settings list.
    """
    filters = _label_filters(
        label_id=label_id,
        name=name,
        type=type,
        creator_id=creator_id,
        creator_name=creator_name,
        creation_date_from=creation_date_from,
        creation_date_to=creation_date_to,
    )
    items, total = label_service.list_label_settings(
        session,
        page=page,
        page_size=page_size,
        filters=filters,
        order_by=order_by,
        order_dir=order_dir,
    )
    return api_page(data=items, total=total, page=page, page_size=page_size)


@router.get(
    "/exports",
    dependencies=[Depends(get_current_active_superuser)],
    summary="导出标签设置 / Export Label Settings",
)
def export_label_settings(
    session: SessionDep,
    label_id: Optional[int] = Query(default=None, description="标签 ID 精确筛选 / Filter by label ID (exact)"),
    name: Optional[str] = Query(default=None, description="名称模糊搜索 / Fuzzy search by name"),
    type: Optional[str] = Query(default=None, description="类型模糊筛选，如 private / public / Fuzzy filter by type"),
    creator_id: Optional[int] = Query(default=None, description="创建者 ID 精确筛选 / Filter by creator ID"),
    creator_name: Optional[str] = Query(default=None, description="创建者名称模糊筛选（大小写不敏感） / Fuzzy filter by creator name (case-insensitive)"),
    creation_date_from: Optional[datetime] = Query(default=None, description="创建日期起 / Creation date from"),
    creation_date_to: Optional[datetime] = Query(default=None, description="创建日期止 / Creation date to"),
    order_by: str = Query(default="label_id", description="排序字段 / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    """
    按筛选条件导出标签设置 CSV。 / Export filtered label settings as CSV.
    """
    filters = _label_filters(
        label_id=label_id,
        name=name,
        type=type,
        creator_id=creator_id,
        creator_name=creator_name,
        creation_date_from=creation_date_from,
        creation_date_to=creation_date_to,
    )
    csv_content = label_service.export_label_settings_csv(
        session,
        filters=filters,
        order_by=order_by,
        order_dir=order_dir,
    )
    return csv_response(csv_content, "label-settings.csv")


@router.post(
    "",
    response_model=ApiResponse[LabelAdminPublic],
    summary="创建标签设置 / Create Label Setting",
)
def create_label_setting(
    session: SessionDep,
    body: LabelAdminCreateRequest,
    current_user: User = Depends(get_current_active_superuser),
) -> Any:
    """
    管理员创建标签，可指定 private/public。 / Admin creates a label with explicit private/public type.
    """
    return api_success(data=label_service.create_label_setting(session, body, current_user))


@router.get(
    "/{label_id}",
    response_model=ApiResponse[LabelAdminPublic],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取标签设置详情 / Get Label Setting",
)
def get_label_setting(session: SessionDep, label_id: int) -> Any:
    """
    获取标签设置详情。 / Get label setting detail.
    """
    return api_success(data=label_service.get_label_setting(session, label_id))


@router.put(
    "/{label_id}",
    response_model=ApiResponse[LabelAdminPublic],
    dependencies=[Depends(get_current_active_superuser)],
    summary="更新标签设置 / Update Label Setting",
)
def update_label_setting(
    session: SessionDep,
    label_id: int,
    body: LabelAdminUpdateRequest,
) -> Any:
    """
    更新标签名称或类型。 / Update label name or type.
    """
    return api_success(data=label_service.update_label_setting(session, label_id, body))


@router.delete(
    "/{label_id}",
    response_model=ApiResponse,
    dependencies=[Depends(get_current_active_superuser)],
    summary="删除标签设置 / Delete Label Setting",
)
def delete_label_setting(session: SessionDep, label_id: int) -> Any:
    """
    删除普通标签；系统标签不可删除。 / Delete a regular label; system labels cannot be deleted.
    """
    label_service.delete_label_setting(session, label_id)
    return ApiResponse()
