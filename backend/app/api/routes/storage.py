"""Container storage status API route."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ActiveAdmin
from app.schemas.response import ApiResponse, api_success
from app.schemas.storage import StorageStatus
from app.services.storage_service import (
    StorageStatusUnavailableError,
    get_storage_status,
)

router = APIRouter(tags=["系统管理 / system"])


@router.get(
    "/storage",
    response_model=ApiResponse[StorageStatus],
    summary="获取后端容器磁盘状态 / Get backend container storage status",
)
def read_storage_status(_current_user: ActiveAdmin) -> ApiResponse[StorageStatus]:
    """Return the backend container root filesystem capacity for administrators."""
    try:
        return api_success(data=get_storage_status())
    except StorageStatusUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
