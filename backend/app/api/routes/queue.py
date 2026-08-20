"""任务队列 API 路由；异步后台任务查询与管理。 / Queue: async task query and management."""
import logging
from datetime import datetime

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, RedisDep, SessionDep
from app.api.responses import csv_response
from app.schemas.queue import (
    QueueDeletionResult,
    QueueDeleteRequest,
    QueueDetail,
    QueueListItem,
)
from app.schemas.response import ApiResponse, PagedApiResponse
from app.services import queue_service
from app.services.analysis_queue_message_cache import get_analysis_queue_message
from app.utils import parse_range

router = APIRouter(prefix="/queues", tags=["任务队列 / queue"])

logger = logging.getLogger(__name__)


@router.get("", response_model=PagedApiResponse[list[QueueListItem]], summary="列出任务队列 / List Queues")
def list_queues(
    session: SessionDep,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条目数 / Items per page"),
    queue_id: int | None = Query(default=None, description="队列 ID 精确筛选 / Filter by queue ID"),
    type: str | None = Query(default=None, description="任务类型模糊筛选 / Fuzzy filter by task type"),
    status: str | None = Query(default=None, description="任务状态，支持完整值或模糊文本 / Task status supports canonical or fuzzy text"),
    user_id: int | None = Query(default=None, description="指定用户 ID（仅管理员可用）/ User ID (Admins only)"),
    username: str | None = Query(default=None, description="用户名模糊筛选（大小写不敏感） / Fuzzy filter by user name (case-insensitive)"),
    completed: str | None = Query(default=None, description="完成数范围（min,max）/ Completed range"),
    total: str | None = Query(default=None, description="总数范围（min,max）/ Total range"),
    start_time_from: datetime | None = Query(default=None, description="开始时间起 / Start time from"),
    start_time_to: datetime | None = Query(default=None, description="开始时间止 / Start time to"),
    stop_time_from: datetime | None = Query(default=None, description="结束时间起 / Stop time from"),
    stop_time_to: datetime | None = Query(default=None, description="结束时间止 / Stop time to"),
    error: str | None = Query(default=None, description="报错信息模糊搜索 / Search in error message"),
    warning: str | None = Query(default=None, description="警告信息模糊搜索 / Search in warning message"),
    search: str | None = Query(default=None, description="搜索报错或警告 / Search in error or warning"),
    order_by: str | None = Query(default="queue_id", description="排序字段 / Sort field"),
    order_dir: str | None = Query(default="asc", pattern="^(asc|desc)$", description="排序方向：asc 或 desc")
):
    """
    列出分析任务。 / List analysis tasks.

    - 普通用户：仅可查看自己的任务。 / Regular users: see own tasks only.
    - 管理员：可查看全站任务，可通过 user_id 筛选。 / Admins: can see all tasks, filterable by user_id.
    """
    completed_min, completed_max = parse_range(completed)
    total_min, total_max = parse_range(total)

    return queue_service.list_queues(
        session=session,
        current_user=current_user,
        page=page,
        page_size=page_size,
        user_id=user_id,
        username=username,
        queue_id=queue_id,
        type=type,
        status=status,
        completed_min=completed_min,
        completed_max=completed_max,
        total_min=total_min,
        total_max=total_max,
        start_time_from=start_time_from,
        start_time_to=start_time_to,
        stop_time_from=stop_time_from,
        stop_time_to=stop_time_to,
        error=error,
        warning=warning,
        search=search,
        order_by=order_by,
        order_dir=order_dir
    )


@router.get("/exports", summary="导出任务队列为 CSV / Export Queues")
def export_queues(
    session: SessionDep,
    current_user: CurrentUser,
    order_by: str = Query(default="queue_id", description="排序字段 / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向：asc 或 desc")
):
    """
    导出任务队列。 / Export queues to CSV.
    """
    csv_data = queue_service.export_queue_csv(
        session=session,
        current_user=current_user,
        order_by=order_by,
        order_dir=order_dir,
    )
    return csv_response(csv_data, "queue.csv")

@router.delete("", response_model=ApiResponse[QueueDeletionResult], summary="删除任务队列 / Delete Queues")
def delete_queues(
    session: SessionDep,
    current_user: CurrentUser,
    body: QueueDeleteRequest,
):
    """
    删除已结束任务；等待任务直接取消并删除，运行任务会在取消完成后删除。
    / Delete terminal tasks; pending tasks are cancelled and deleted immediately, while running tasks are deleted after cancellation completes.
    """
    return queue_service.delete_queues(
        session=session,
        current_user=current_user,
        queue_ids=body.queue_ids,
    )

@router.get("/{queue_id}", response_model=ApiResponse[QueueDetail], summary="获取任务状态 / Get Queue Status")
async def get_queue(
    queue_id: int,
    session: SessionDep,
    redis: RedisDep,
    current_user: CurrentUser,
):
    """
    查询单个分析任务状态信息。 / Query single analysis task status.
    """
    response = queue_service.get_queue(
        session=session,
        current_user=current_user,
        queue_id=queue_id
    )
    if response.data is not None:
        response.data.message = await get_analysis_queue_message(redis, queue_id)
    return response
