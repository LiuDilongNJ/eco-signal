"""AI 分析 API 接口 / AI Analysis API endpoints."""
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, SessionDep, TaskPublisherDep
from app.models.index import IndexType
from app.repositories import index_type_repository
from app.schemas.analysis import (
    AcousticIndexPreviewRequest,
    AcousticIndexPreviewResponse,
    AcousticIndicesResponse,
    RunAcousticIndicesRequest,
    RunAnalysisRequest,
    RunAnalysisResponse,
)
from app.schemas.index_type import IndexTypeParameterRead, IndexTypeRead
from app.schemas.response import ApiResponse, api_success
from app.services.analysis_service import analysis_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["AI 分析 / AI Analysis"])


def _parse_index_parameters(raw_param: Any) -> list[IndexTypeParameterRead]:
    if raw_param is None:
        return []
    if not isinstance(raw_param, list):
        raise HTTPException(status_code=500, detail="Invalid acoustic index parameter format")

    parameters: list[IndexTypeParameterRead] = []
    for item in raw_param:
        if not isinstance(item, dict) or not item.get("key"):
            raise HTTPException(status_code=500, detail="Invalid acoustic index parameter format")
        parameters.append(
            IndexTypeParameterRead(
                key=str(item["key"]),
                default=item.get("default"),
                value_type=item.get("value_type", "string"),
            )
        )
    return parameters


def _to_index_type_read(index_type: IndexType) -> IndexTypeRead:
    return IndexTypeRead(
        index_id=index_type.index_id,
        name=index_type.name,
        description=index_type.description,
        param=index_type.param,
        url=index_type.url,
        parameters=_parse_index_parameters(index_type.param),
    )


@router.get(
    "/index-types",
    response_model=ApiResponse[list[IndexTypeRead]],
    summary="获取声学指数目录 / Get Acoustic Index Types",
)
def get_index_types(
    session: SessionDep,
    current_user: CurrentUser,
):
    """
    获取可用的声学指数类型及参数元数据。 / Get available acoustic index types and their parameter metadata.
    """
    del current_user
    index_types = index_type_repository.list_all(session)
    return api_success(data=[_to_index_type_read(index_type) for index_type in index_types])


@router.post("/analysis-jobs", response_model=ApiResponse[RunAnalysisResponse], summary="运行分析 / Run Analysis")
async def run_analysis(
    request: RunAnalysisRequest,
    session: SessionDep,
    current_user: CurrentUser,
    publisher: TaskPublisherDep,
):
    """
    统一的 AI 分析接口。 / Unified AI analysis endpoint.

    提交一个或多个 AI 模型异步分析媒体文件。 / Submit one or more AI models to analyze a media file asynchronously.
    每个选定的模型都会创建一个单独的队列任务。通过 GET /queues/{queue_id} 轮询状态。 / Each selected model creates a separate queue task. Poll status via GET /queues/{queue_id}.

    Args:
        request: 包含 media_id、模型选择和参数的分析请求 / Analysis request containing media_id, model selection and parameters

    Returns:
        已排队的任务列表，每个选定模型一个 / List of queued tasks, one per selected model
    """
    if request.birdnet is None and request.batdetect is None and request.insects is None:
        raise HTTPException(
            status_code=400,
            detail="At least one model must be selected (birdnet, batdetect, or insects)",
        )

    try:
        result = await analysis_service.enqueue_analysis(
            session=session,
            publisher=publisher,
            request=request,
            current_user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return api_success(data=result)


@router.post(
    "/acoustic-index-jobs",
    response_model=ApiResponse[AcousticIndicesResponse],
    summary="计算声学指数 / Calculate Acoustic Indices",
)
async def run_acoustic_indices(
    request: RunAcousticIndicesRequest,
    session: SessionDep,
    current_user: CurrentUser,
    publisher: TaskPublisherDep,
):
    """
    触发声学指数计算任务。 / Trigger acoustic indices calculation jobs.

    对媒体文件异步计算所选声学指数，结果存入 index_log 表。 / Asynchronously computes selected acoustic indices for a media file and stores results in index_log.

    - 至少须选择一个 index / At least one index must be selected
    - 需要对媒体文件所在集合有 collection:write 权限（或为管理员/上传者）/ Requires collection:write permission on the collection

    通过 GET /queues/{queue_id} 轮询进度。 / Poll progress via GET /queues/{queue_id}.
    """
    if not request.indices:
        raise HTTPException(status_code=400, detail="At least one index must be selected")

    result = await analysis_service.enqueue_acoustic_indices(
        session=session,
        publisher=publisher,
        request=request,
        current_user=current_user,
    )
    return api_success(data=result)


@router.post(
    "/acoustic-index-previews",
    response_model=ApiResponse[AcousticIndexPreviewResponse],
    summary="预览声学指数结果 / Preview Acoustic Index Result",
)
async def preview_acoustic_index(
    request: AcousticIndexPreviewRequest,
    session: SessionDep,
    current_user: CurrentUser,
):
    """
    计算单个声学指数并返回预览结果，不写入 index_log。 / Calculate one acoustic index and return a preview without writing index_log.

    详情页确认保存前使用该接口。 / Used by the detail page before the user confirms saving.
    """
    result = await run_in_threadpool(
        analysis_service.preview_acoustic_index,
        session,
        request,
        current_user,
    )
    return api_success(data=result)
