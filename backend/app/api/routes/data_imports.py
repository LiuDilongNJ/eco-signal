"""离线数据导入 API 路由。 / Offline data import API routes."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, RedisDep, SessionDep
from app.schemas.data_import import (
    DataImportCreateRequest,
    DataImportCreateResponse,
    DataImportStatusResponse,
)
from app.schemas.response import ApiResponse, api_success
from app.services.data_import_service import data_import_service

router = APIRouter(prefix="/data-imports", tags=["离线数据导入 / data imports"])


@router.post("", response_model=ApiResponse[DataImportCreateResponse], summary="创建离线导入上传会话 / Create Offline Import Upload Session")
async def create_data_import(
    session: SessionDep,
    redis: RedisDep,
    current_user: CurrentUser,
    payload: DataImportCreateRequest,
) -> ApiResponse[DataImportCreateResponse]:
    """
    创建离线导入上传会话，并返回后续分块上传要使用的 batch_id。 /
    Create an offline import upload session and return the batch_id used by chunk upload.

    权限要求：当前用户必须对 project_id 拥有 project:write。 /
    Permission: current user must have project:write on the target project.
    """
    return api_success(
        data=await data_import_service.create_upload_session(session, redis, current_user, payload)
    )


@router.get("/{batch_id}", response_model=ApiResponse[DataImportStatusResponse], summary="获取离线导入状态 / Get Offline Import Status")
async def get_data_import(
    batch_id: str,
    session: SessionDep,
    redis: RedisDep,
    current_user: CurrentUser,
) -> ApiResponse[DataImportStatusResponse]:
    """
    查询离线导入状态、队列关联信息与导入结果摘要。 /
    Query the offline import status, queue linkage, and import summary.
    """
    return api_success(
        data=await data_import_service.get_status(session, redis, current_user, batch_id)
    )
