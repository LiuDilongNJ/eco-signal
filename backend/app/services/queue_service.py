from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session

from app.csv_export import CsvColumn, export_columns_csv
from app.enums import QueueStatus
from app.models.user import User
from app.repositories import queue_repository
from app.schemas.queue import QueueDeletionResult, QueueDetail, QueueListItem
from app.schemas.capability import RowCapabilities
from app.schemas.response import ApiResponse, PagedApiResponse, api_page, api_success
from app.services import permission_service
from app.repositories.collection_bundle_export_repository import collection_bundle_export_repository
from app.services.collection_bundle_export_service import delete_queue_exports

_QUEUE_EXPORT_COLUMNS = [
    CsvColumn("queue_id"), CsvColumn("type"), CsvColumn("username"),
    CsvColumn("user_id"), CsvColumn("completed"), CsvColumn("total"),
    CsvColumn("status"), CsvColumn("start_time"),
    CsvColumn("stop_time"), CsvColumn("error"), CsvColumn("warning"),
]


def list_queues(
    session: Session,
    current_user: User,
    page: int,
    page_size: int,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    queue_id: Optional[int] = None,
    type: Optional[str] = None,
    status: Optional[str] = None,
    completed_min: Optional[int] = None,
    completed_max: Optional[int] = None,
    total_min: Optional[int] = None,
    total_max: Optional[int] = None,
    start_time_from: Optional[datetime] = None,
    start_time_to: Optional[datetime] = None,
    stop_time_from: Optional[datetime] = None,
    stop_time_to: Optional[datetime] = None,
    error: Optional[str] = None,
    warning: Optional[str] = None,
    search: Optional[str] = None,
    order_by: str = "start_time",
    order_dir: str = "asc",
) -> PagedApiResponse[list[QueueListItem]]:
    """
    获取分页的队列数据及总数，包含权限控制逻辑。
    """
    is_admin = permission_service.is_admin(current_user)

    queues, total_count = queue_repository.list_queues(
        session=session,
        is_admin=is_admin,
        current_user_id=current_user.user_id,
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

    data = []
    for queue in queues:
        progress = 0.0
        if queue.total > 0:
            progress = round((queue.completed / queue.total) * 100, 2)
            
        username = queue.user.username if queue.user else "Unknown"
        try:
            status_name = QueueStatus(queue.status).name.lower()
        except ValueError:
            status_name = "unknown"

        data.append(QueueListItem(
            queue_id=queue.queue_id,
            user_id=queue.user_id,
            username=username,
            type=queue.type,
            status=status_name,
            completed=queue.completed,
            total=queue.total,
            progress=progress,
            start_time=queue.start_time,
            stop_time=queue.stop_time,
            error=queue.error,
            warning=queue.warning,
            capabilities=RowCapabilities(delete=is_admin or queue.user_id == current_user.user_id),
        ))

    return api_page(
        data=data,
        total=total_count,
        page=page,
        page_size=page_size
    )


def get_queue(
    session: Session,
    current_user: User,
    queue_id: int
) -> ApiResponse[QueueDetail]:
    """
    获取单个队列详情，包含权限验证逻辑。
    """
    queue = queue_repository.get(session, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found / 任务不存在")
        
    is_admin = permission_service.is_admin(current_user)
    if not is_admin and queue.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Permission Denied / 权限不足，无法访问该队列")
        
    try:
        status_name = QueueStatus(queue.status).name.lower()
    except ValueError:
        status_name = "unknown"

    progress = 0.0
    if queue.total > 0:
        progress = round((queue.completed / queue.total) * 100, 2)

    return api_success(data=QueueDetail(
        queue_id=queue.queue_id,
        status=status_name,
        progress=progress,
        completed=queue.completed,
        total=queue.total,
        error=queue.error,
        warning=queue.warning,
        start_time=queue.start_time,
        stop_time=queue.stop_time,
        type=queue.type
    ))


def export_queue_csv(
    session: Session,
    current_user: User,
    order_by: str = "queue_id",
    order_dir: str = "asc",
):
    """
    Export queues to CSV format string using standard repository method.
    """
    result = list_queues(
        session=session,
        current_user=current_user,
        page=1,
        page_size=1_000_000,
        order_by=order_by,
        order_dir=order_dir,
    )
    return export_columns_csv(_QUEUE_EXPORT_COLUMNS, result.data)


def delete_queues(
    session: Session,
    current_user: User,
    queue_ids: list[int],
) -> ApiResponse[QueueDeletionResult]:
    """
    Delete terminal queues and request cancellation for active queues.
    """
    is_admin = permission_service.is_admin(current_user)
    export_records = collection_bundle_export_repository.get_by_queue_ids(session, queue_ids)
    raw_result = queue_repository.delete_or_cancel_queues(
        session=session,
        queue_ids=queue_ids,
        is_admin=is_admin,
        current_user_id=current_user.user_id
    )
    delete_queue_exports(
        session,
        [record for record in export_records if record.queue_id in raw_result["deleted_ids"]],
    )
    session.commit()
    result = QueueDeletionResult.model_validate(raw_result)
    message_parts = []
    if result.deleted_ids:
        label = "Task" if len(result.deleted_ids) == 1 else "Tasks"
        message_parts.append(f"{label} deleted successfully")
    if result.cancelling_ids:
        label = "Task" if len(result.cancelling_ids) == 1 else "Tasks"
        message_parts.append(f"{label} deletion requested")
    if result.unavailable_ids:
        label = "Task" if len(result.unavailable_ids) == 1 else "Tasks"
        message_parts.append(f"{label} failed to delete")
    message = ". ".join(message_parts) or "No tasks were deleted"
    return api_success(data=result, message=message)
