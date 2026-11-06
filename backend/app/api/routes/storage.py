"""存储状态接口 / Storage status API."""

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
    summary="获取文件系统容量 / Get filesystem capacity",
)
def read_storage_status(_current_user: ActiveAdmin) -> ApiResponse[StorageStatus]:
    """仅管理员可读；不授予公开访问。 / Administrators only; no public access."""
    try:
        return api_success(data=get_storage_status())
    except StorageStatusUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
