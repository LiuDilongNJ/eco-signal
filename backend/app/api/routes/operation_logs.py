"""操作日志 API 路由。 / Operation log API routes."""
from datetime import date, datetime, time
from typing import Optional

from fastapi import APIRouter, Query

from app.api.deps import ActiveAdmin, SessionDep
from app.schemas.operation_log import OperationLogRead
from app.schemas.response import PagedApiResponse, api_page
from app.services.operation_log_service import operation_log_service

router = APIRouter()


def _date_start(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.min)


def _date_end(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.max)


@router.get(
    "",
    response_model=PagedApiResponse[list[OperationLogRead]],
    summary="获取操作日志列表 / List Operation Logs",
)
def read_operation_logs(
    session: SessionDep,
    _current_user: ActiveAdmin,
    log_id: Optional[int] = Query(None, description="Filter by log ID"),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    username: Optional[str] = Query(None, description="Filter by username"),
    action: Optional[str] = Query(None, description="Fuzzy filter by action (e.g., create, update, delete)"),
    resource_type: Optional[str] = Query(None, description="Fuzzy filter by resource type (e.g., project, user)"),
    description: Optional[str] = Query(None, description="Filter by description"),
    status_code: Optional[str] = Query(None, description="Fuzzy filter by status code"),
    search: Optional[str] = Query(None, description="Search in description, action or resource_type"),
    date_from: date | None = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: date | None = Query(None, description="Filter to date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    order_by: str = Query("log_id", description="Field to sort by"),
    order_dir: str = Query("asc", description="Sort direction (asc/desc)"),
) -> dict:
    """
    获取系统操作日志。/ Retrieve system operation logs.

    仅管理员可访问。/ Admin only.
    """
    filters = {
        "log_id": log_id,
        "user_id": user_id,
        "username": username,
        "action": action,
        "resource_type": resource_type,
        "description": description,
        "status_code": status_code,
        "search": search,
        "date_from": _date_start(date_from),
        "date_to": _date_end(date_to),
    }
    # Remove None values
    filters = {k: v for k, v in filters.items() if v is not None}

    items, total = operation_log_service.get_logs(
        session,
        filters=filters,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
    )
    
    # Map username if needed - doing it in memory is fine for typical pagination sizes
    results = []
    for item in items:
        # Pydantic reading from attributes will catch username if present
        # Actually in SQLAlchemy, `item.user` is a relationship and we can just expose `item.user.username` 
        # via schema if we set it locally.
        read_obj = OperationLogRead.model_validate(item)
        if item.user:
            read_obj.username = item.user.username
        results.append(read_obj)

    return api_page(data=results, total=total, page=page, page_size=page_size)
