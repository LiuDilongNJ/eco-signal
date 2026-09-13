"""AI 模型 API 路由。 / Machine learning models API endpoints."""
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import SessionDep
from app.repositories.model_repository import model_repository
from app.schemas.model import MLModelRead
from app.schemas.response import ApiResponse, api_success
from app.services.analysis_service import analysis_service

router = APIRouter(prefix="/models", tags=["AI 模型 / AI Models"])


def _resolve_model_version(model_name: str | None, db_version: str | None) -> str | None:
    """解析模型版本，优先使用数据库版本，其次回退到运行时分析器版本。 / Resolve model version, preferring DB version with fallback to runtime analyzer version."""
    if db_version:
        return db_version
    lower_name = (model_name or "").lower()
    if "birdnet" in lower_name:
        try:
            return analysis_service.birdnet.version
        except Exception:
            return "2.4"
    if "batdetect" in lower_name:
        try:
            return analysis_service.batdetect.version
        except Exception:
            return "1.3.0"
    return None


@router.get("", response_model=ApiResponse[list[MLModelRead]], summary="获取 AI 模型列表 / List AI Models")
def list_models(
    session: SessionDep,
) -> Any:
    """
    获取系统中可用的 AI 模型元数据及版本信息。 / Get available AI model metadata and versions.

    返回模型 ID、名称、版本、描述、来源链接及参数配置。 / Returns model ID, name, version, description, source URL, and parameter configuration.
    """
    models = model_repository.list_all(session)
    data = [
        MLModelRead(
            model_id=m.model_id,
            name=m.name,
            version=_resolve_model_version(m.name, m.version),
            description=m.description,
            source_url=m.source_url,
            parameter=m.parameter,
        )
        for m in models
    ]
    return api_success(data=data)


@router.get("/{model_id}", response_model=ApiResponse[MLModelRead], summary="获取单个 AI 模型详情 / Get AI Model Detail")
def get_model(
    model_id: int,
    session: SessionDep,
) -> Any:
    """
    获取指定 AI 模型的详细元数据。 / Get detailed metadata for a specific AI model.
    """
    model = model_repository.get_by_id(session, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return api_success(
        data=MLModelRead(
            model_id=model.model_id,
            name=model.name,
            version=_resolve_model_version(model.name, model.version),
            description=model.description,
            source_url=model.source_url,
            parameter=model.parameter,
        )
    )
