"""工具 API 路由。 / Utils API routes."""
from fastapi import APIRouter

from app.schemas.response import ApiResponse

router = APIRouter(tags=["工具 / utils"])


@router.get("/health", response_model=ApiResponse, summary="健康检查 / Health Check")
async def health_check() -> ApiResponse:
    """
    健康检查接口。 / Health check endpoint.
    """
    return ApiResponse(message="healthy")
