from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import update
from sqlmodel import Session

from app.core.db import engine
from app.core.task_cancellation import TASK_CANCELLED_MESSAGE
from app.enums import QueueStatus
from app.models.system import Queue


def prepare_queue_for_execution(queue_id: int) -> QueueStatus | None:
    """Atomically claim a pending queue while allowing active batch messages."""
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as session:
        result = session.execute(
            update(Queue)
            .where(Queue.queue_id == queue_id, Queue.status == QueueStatus.PENDING)
            .values(status=QueueStatus.RUNNING, start_time=now)
        )
        session.commit()
        if result.rowcount:
            return QueueStatus.RUNNING
        queue = session.get(Queue, queue_id)
        if queue is None:
            return None
        try:
            return QueueStatus(queue.status)
        except ValueError:
            return None


def finalize_queue_cancellation(queue_id: int) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as session:
        session.execute(
            update(Queue)
            .where(
                Queue.queue_id == queue_id,
                Queue.error == TASK_CANCELLED_MESSAGE,
            )
            .values(status=QueueStatus.ERROR, stop_time=now)
        )
        session.commit()


def cancellation_requested(queue_id: int) -> bool:
    with Session(engine) as session:
        queue = session.get(Queue, queue_id)
        return bool(
            queue is not None
            and queue.status == QueueStatus.ERROR
            and queue.error == TASK_CANCELLED_MESSAGE
        )
