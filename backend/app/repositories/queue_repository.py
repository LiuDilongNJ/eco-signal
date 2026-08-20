from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, func, select

from app.core.task_cancellation import TASK_CANCELLED_MESSAGE
from app.enums import QueueStatus
from app.models.system import Queue
from app.models.user import User
from app.repositories.base import BaseRepository
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
    apply_pagination,
)

_FILTER_SPECS: list[FilterSpec] = [
    # user_id is resolved externally (permission logic) and passed in as-is
    ("queue_id",   Queue.queue_id,   FilterOp.EQ),
    ("user_id",    Queue.user_id,    FilterOp.EQ),
    ("type",       Queue.type,       FilterOp.LIKE),
    # Numeric ranges
    ("completed",  Queue.completed,  FilterOp.RANGE),
    ("total",      Queue.total,      FilterOp.RANGE),
    # Date ranges
    ("start_time", Queue.start_time, FilterOp.DATE_RANGE),
    ("stop_time",  Queue.stop_time,  FilterOp.DATE_RANGE),
]

# Explicit sort-field mapping prevents getattr-based SQL injection.
_SORT_FIELDS: dict[str, Any] = {
    "queue_id":    Queue.queue_id,
    "id":          Queue.queue_id,
    "type":        Queue.type,
    "status":      Queue.status,
    "start_time":  Queue.start_time,
    "stop_time":   Queue.stop_time,
    "completed":   Queue.completed,
    "total":       Queue.total,
    "user_id":     Queue.user_id,
    "user":        func.lower(User.username),
    "error":       Queue.error,
    "warning":     Queue.warning,
}


class QueueRepository(BaseRepository[Queue, Any, Any]):
    def __init__(self):
        super().__init__(Queue)

    def _build_list_query(self, filters: dict | None = None, order_by: str | None = None):
        """Construct the base query with generic filters.

        Custom (non-spec) filters handled here:
        - status: string → integer mapping
        - error/warning/search: partial match fields
        """
        if filters is None:
            filters = {}

        query = select(Queue)

        # Standard declarative filters
        query = apply_filters(query, filters, _FILTER_SPECS)

        if filters.get("username") or order_by == "user":
            query = query.join(User, Queue.user_id == User.user_id)
        if filters.get("username"):
            query = query.where(User.username.ilike(f"%{filters['username']}%"))

        # Custom: status string → integer mapping
        status = filters.get("status")
        if status is not None:
            status_map = {status.name.lower(): status.value for status in QueueStatus}
            normalized_status = str(status).strip().lower()
            if normalized_status in status_map:
                query = query.where(Queue.status == status_map[normalized_status])
            else:
                matched_codes = [
                    code
                    for name, code in status_map.items()
                    if normalized_status and normalized_status in name
                ]
                query = query.where(Queue.status.in_(matched_codes)) if matched_codes else query.where(Queue.status == -999)

        # Custom: individual text filters
        if filters.get("error"):
            query = query.where(Queue.error.ilike(f"%{filters['error']}%"))
        if filters.get("warning"):
            query = query.where(Queue.warning.ilike(f"%{filters['warning']}%"))

        # Custom: broad search across relevant text fields
        if filters.get("search"):
            s = f"%{filters['search']}%"
            query = query.where(
                (Queue.error.ilike(s)) | (Queue.warning.ilike(s)) | (Queue.type.ilike(s))
            )

        return query

    def list_queues(
        self,
        session: Session,
        is_admin: bool,
        current_user_id: int,
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
    ) -> tuple[list[Queue], int]:
        """Fetch paginated queue records based on filters and permissions."""
        # Resolve effective user_id (permission logic)
        actual_user_id = None if is_admin else current_user_id
        if is_admin and user_id is not None:
            actual_user_id = user_id

        filters = {k: v for k, v in {
            "user_id":          actual_user_id,
            "username":        username,
            "queue_id":         queue_id,
            "type":             type,
            "status":           status,
            "completed_min":    completed_min,
            "completed_max":    completed_max,
            "total_min":        total_min,
            "total_max":        total_max,
            "start_time_from":  start_time_from,
            "start_time_to":    start_time_to,
            "stop_time_from":   stop_time_from,
            "stop_time_to":     stop_time_to,
            "error":            error,
            "warning":          warning,
            "search":           search,
        }.items() if v is not None}

        query = self._build_list_query(filters=filters, order_by=order_by)
        total = session.exec(
            select(func.count()).select_from(query.subquery())
        ).one()
        query = apply_ordering(
            query,
            order_by,
            order_dir,
            _SORT_FIELDS,
            Queue.start_time,
            Queue.queue_id,
        )
        query = apply_pagination(query, page, page_size)

        return list(session.exec(query).all()), total

    def delete_or_cancel_queues(
        self,
        session: Session,
        queue_ids: list[int],
        is_admin: bool,
        current_user_id: int,
    ) -> dict[str, Any]:
        """Delete terminal queues and request cancellation for active queues."""
        unique_ids = list(dict.fromkeys(queue_ids))
        if not unique_ids:
            return {
                "deleted_ids": [],
                "cancelling_ids": [],
                "unavailable_ids": [],
            }

        query = select(Queue).where(Queue.queue_id.in_(unique_ids)).with_for_update()
        if not is_admin:
            query = query.where(Queue.user_id == current_user_id)

        queues = list(session.exec(query).all())
        available_ids = {queue.queue_id for queue in queues}
        result: dict[str, Any] = {
            "deleted_ids": [],
            "cancelling_ids": [],
            "unavailable_ids": [queue_id for queue_id in unique_ids if queue_id not in available_ids],
        }
        for queue in queues:
            status = QueueStatus(queue.status)
            if status == QueueStatus.PENDING:
                session.delete(queue)
                result["deleted_ids"].append(queue.queue_id)
            elif status == QueueStatus.RUNNING:
                queue.status = QueueStatus.ERROR
                queue.error = TASK_CANCELLED_MESSAGE
                result["cancelling_ids"].append(queue.queue_id)
            elif status == QueueStatus.ERROR and queue.error == TASK_CANCELLED_MESSAGE and queue.stop_time is None:
                result["cancelling_ids"].append(queue.queue_id)
            else:
                session.delete(queue)
                result["deleted_ids"].append(queue.queue_id)
        requested_order = {queue_id: index for index, queue_id in enumerate(unique_ids)}
        result["deleted_ids"].sort(key=requested_order.__getitem__)
        result["cancelling_ids"].sort(key=requested_order.__getitem__)
        return result


queue_repository = QueueRepository()
