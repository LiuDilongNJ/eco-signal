from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session

from app.api.deps import get_redis_client
from app.core.db import engine
from app.enums import QueueStatus
from app.models import FileUpload, Queue, User
from app.services import offline_bundle_service
from app.services.data_import_service import data_import_service
from app.core.task_cancellation import (
    TASK_CANCELLED_MESSAGE,
    CancellationToken,
    TaskCancelledError,
)

logger = logging.getLogger(__name__)


async def import_collection_bundle(
    ctx: dict[str, Any],
    batch_id: str,
    project_id: int,
    uploader_id: int,
    file_upload_id: int,
    queue_id: int,
) -> dict[str, Any]:
    """Process an uploaded offline bundle after chunk merge completes."""
    cancellation_token: CancellationToken | None = ctx.get("cancellation_token")
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    with Session(engine) as session:
        queue = session.get(Queue, queue_id)
        file_upload = session.get(FileUpload, file_upload_id)
        uploader = session.get(User, uploader_id)
        if queue is None or file_upload is None or uploader is None:
            logger.error(
                "Offline import task missing context: batch_id=%s queue_id=%s file_upload_id=%s uploader_id=%s",
                batch_id,
                queue_id,
                file_upload_id,
                uploader_id,
            )
            return {"error": "Offline import context not found"}

        queue.total = 1
        file_upload.status = 2
        session.add(queue)
        session.add(file_upload)
        session.commit()
        async for redis in get_redis_client():
            await data_import_service.update_context(
                redis,
                batch_id,
                status="running",
                error=None,
                queue_id=queue_id,
                file_upload_id=file_upload_id,
            )
            break

        try:
            result = offline_bundle_service.import_collection_bundle_from_file_upload(
                session,
                project_id=project_id,
                file_upload=file_upload,
                uploader=uploader,
                batch_id=batch_id,
                cancellation_token=cancellation_token,
                queue_id=queue_id,
            )
        except TaskCancelledError:
            session.rollback()
            async for redis in get_redis_client():
                await data_import_service.update_context(
                    redis,
                    batch_id,
                    status="cancelled",
                    error=None,
                    queue_id=queue_id,
                    file_upload_id=file_upload_id,
                    cleanup_after=(datetime.now(UTC) + timedelta(days=7)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
                )
                break
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Offline bundle import failed for batch_id=%s", batch_id)
            error_message = str(exc)
            session.rollback()
            queue = session.get(Queue, queue_id)
            file_upload = session.get(FileUpload, file_upload_id)
            if queue is None or file_upload is None:
                return {"error": error_message, "batch_id": batch_id}
            if queue.status == QueueStatus.ERROR and queue.error == TASK_CANCELLED_MESSAGE:
                async for redis in get_redis_client():
                    await data_import_service.update_context(
                        redis,
                        batch_id,
                        status="cancelled",
                        error=None,
                        queue_id=queue_id,
                        file_upload_id=file_upload_id,
                        cleanup_after=(datetime.now(UTC) + timedelta(days=7)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    break
                raise TaskCancelledError("Task cancellation requested") from exc
            file_upload.status = 4
            file_upload.error = error_message
            queue.status = QueueStatus.ERROR
            queue.completed = 0
            queue.total = 1
            queue.error = error_message
            queue.stop_time = datetime.now(UTC).replace(tzinfo=None)
            session.add(file_upload)
            session.add(queue)
            session.commit()
            async for redis in get_redis_client():
                await data_import_service.update_context(
                    redis,
                    batch_id,
                    status="failed",
                    error=error_message,
                    queue_id=queue_id,
                    file_upload_id=file_upload_id,
                    cleanup_after=(datetime.now(UTC) + timedelta(days=7)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
                )
                break
            return {"error": error_message, "batch_id": batch_id}

        queue = session.get(Queue, queue_id)
        file_upload = session.get(FileUpload, file_upload_id)
        if queue is None or file_upload is None:
            return {"error": "Offline import context not found", "batch_id": batch_id}
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if queue.status == QueueStatus.ERROR and queue.error == TASK_CANCELLED_MESSAGE:
            raise TaskCancelledError("Task cancellation requested")
        if queue.status != QueueStatus.COMPLETED:
            file_upload.status = 3
            file_upload.error = None
            file_upload.path = ""
            queue.status = QueueStatus.COMPLETED
            queue.completed = 1
            queue.total = 1
            queue.error = None
            queue.stop_time = datetime.now(UTC).replace(tzinfo=None)
            session.add(file_upload)
            session.add(queue)
            session.commit()

        async for redis in get_redis_client():
            await data_import_service.update_context(
                redis,
                batch_id,
                status="completed",
                error=None,
                queue_id=queue_id,
                file_upload_id=file_upload_id,
                cleanup_after=None,
                summary_json=result.model_dump(mode="json"),
            )
            break
        return {
            "status": "success",
            "batch_id": batch_id,
            "collection_id": result.collection_id,
        }
