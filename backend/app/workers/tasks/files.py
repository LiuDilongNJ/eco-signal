import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session

from app.api.deps import get_redis_client
from app.core.db import engine
from app.enums import QueueStatus, WorkerTaskType
from app.media_paths import normalize_media_relative_path
from app.models import FileUpload, Queue
from app.services.data_import_service import data_import_service
from app.services.file_service import file_service
from app.services.upload_validation_service import format_validation_error
from app.workers.publisher import TaskPublisher
from app.core.task_cancellation import (
    TASK_CANCELLED_MESSAGE,
    CancellationToken,
    TaskCancelledError,
)

logger = logging.getLogger(__name__)

def _validation_failure_reason(code: str) -> str:
    return format_validation_error(code)


def _update_merge_queue(
    session: Session,
    queue_id: int | None,
    *,
    status: int,
    error: str | None = None,
    warning: str | None = None,
) -> None:
    if queue_id is None:
        return
    queue = session.get(Queue, queue_id)
    if queue is None:
        return
    if queue.status == QueueStatus.ERROR and queue.error == TASK_CANCELLED_MESSAGE:
        return
    now = datetime.now(UTC).replace(tzinfo=None)
    queue.status = status
    queue.error = error
    queue.warning = warning
    if status == 1:
        queue.start_time = queue.start_time or now
    elif status in {QueueStatus.COMPLETED, QueueStatus.ERROR, QueueStatus.WARNING}:
        queue.stop_time = now
        if status == QueueStatus.COMPLETED:
            queue.completed = queue.total
    session.add(queue)
    session.commit()


async def _mark_offline_import_context_failed(
    *,
    batch_id: str | None,
    error: str,
    file_upload_id: int | None = None,
    queue_id: int | None = None,
) -> None:
    if not batch_id:
        return
    async for redis in get_redis_client():
        context = await data_import_service.get_context(redis, batch_id)
        if context is not None:
            await data_import_service.update_context(
                redis,
                batch_id,
                status="failed",
                error=error,
                file_upload_id=file_upload_id,
                queue_id=queue_id,
            )
        break


async def merge_file_chunks(
    ctx: dict[str, Any],
    file_upload_id: int,
    filename: str,
    user_id: int,
    batch_id: str | None = None,
    queue_id: int | None = None,
) -> dict[str, Any]:
    """
    Asynchronously merge uploaded chunks for a file.
    
    Args:
        ctx: Worker context
        file_upload_id: FileUpload record ID (pre-created with status=0)
        filename: Original filename
        user_id: Uploader's user ID
        batch_id: Optional batch ID
        
    Returns:
        Task execution result
    """
    cancellation_token: CancellationToken | None = ctx.get("cancellation_token")
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    with Session(engine) as session:
        file_upload = session.get(FileUpload, file_upload_id)
        if not file_upload:
            logger.error(f"FileUpload {file_upload_id} not found for merging")
            _update_merge_queue(session, queue_id, status=QueueStatus.ERROR, error="FileUpload not found")
            return {"error": "FileUpload not found"}

        merged_path: Path | None = None
        try:
            _update_merge_queue(session, queue_id, status=QueueStatus.RUNNING)
            data_import = None
            if batch_id:
                async for redis in get_redis_client():
                    data_import = await data_import_service.get_context(redis, batch_id)
                    break
            if data_import is None:
                raise RuntimeError("Chunk merge task is only available for offline imports")
            logger.info(f"Merging import bundle for {filename} (batch: {batch_id})")
            merged_path = file_service.merge_and_validate_chunks(
                filename=filename,
                user_id=user_id,
                batch_id=batch_id,
                media_type="zip",
            )
            # Update FileUpload record with actual path and status
            file_upload.path = str(normalize_media_relative_path(merged_path))
            file_upload.status = 1  # pending (ready for processing)
            session.commit()

            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()

            _update_merge_queue(session, queue_id, status=QueueStatus.COMPLETED)

            if data_import is not None:
                queue = Queue(
                    type="offline_import",
                    user_id=file_upload.uploader_id,
                    total=1,
                    status=QueueStatus.PENDING,
                )
                session.add(queue)
                session.commit()
                session.refresh(queue)
                try:
                    async for redis in get_redis_client():
                        await data_import_service.update_context(
                            redis,
                            batch_id,
                            status="queued",
                            error=None,
                            file_upload_id=file_upload.file_upload_id,
                            queue_id=queue.queue_id,
                        )
                        publisher = TaskPublisher()
                        try:
                            await publisher.enqueue_task(
                                WorkerTaskType.IMPORT_COLLECTION_BUNDLE,
                                batch_id=batch_id,
                                project_id=data_import["project_id"],
                                uploader_id=data_import["uploader_id"],
                                file_upload_id=file_upload.file_upload_id,
                                queue_id=queue.queue_id,
                            )
                        finally:
                            await publisher.close()
                        break
                except Exception as exc:
                    logger.exception("Failed to enqueue offline import for batch_id=%s", batch_id)
                    queue.status = QueueStatus.ERROR
                    queue.error = "Failed to enqueue offline import job"
                    session.add(queue)
                    session.commit()
                    file_upload.status = 4
                    file_upload.error = str(exc)
                    session.add(file_upload)
                    session.commit()
                    async for redis in get_redis_client():
                        await data_import_service.update_context(
                            redis,
                            batch_id,
                            status="failed",
                            error=str(exc),
                            file_upload_id=file_upload.file_upload_id,
                            queue_id=queue.queue_id,
                        )
                        break
                    return {"error": str(exc), "file_upload_id": file_upload_id}
            
            logger.info(f"Successfully merged chunks for file_upload_id={file_upload_id}")
            return {"status": "success", "file_upload_id": file_upload_id, "path": file_upload.path}

        except TaskCancelledError:
            session.rollback()
            if batch_id:
                async for redis in get_redis_client():
                    await data_import_service.update_context(
                        redis,
                        batch_id,
                        status="cancelled",
                        error=None,
                        file_upload_id=file_upload_id,
                        queue_id=queue_id,
                    )
                    break
            raise
        except HTTPException as e:
            code = str(e.detail) if isinstance(e.detail, str) else "invalid_file_content"
            reason = _validation_failure_reason(code)
            logger.info("Rejected file_upload_id=%s during upload validation: %s", file_upload_id, reason)
            if merged_path is not None:
                merged_path.unlink(missing_ok=True)
            file_upload.status = 4
            file_upload.error = reason
            session.add(file_upload)
            session.commit()
            _update_merge_queue(session, queue_id, status=QueueStatus.ERROR, error=reason)
            await _mark_offline_import_context_failed(
                batch_id=batch_id,
                error=reason,
                file_upload_id=file_upload_id,
                queue_id=queue_id,
            )
            return {"error": reason}
        except FileNotFoundError as e:
            logger.error(f"Chunks missing during merge for file_upload_id={file_upload_id}: {e}")
            file_upload.status = 4  # error
            file_upload.error = str(e)
            session.commit()
            _update_merge_queue(session, queue_id, status=QueueStatus.ERROR, error=str(e))
            await _mark_offline_import_context_failed(
                batch_id=batch_id,
                error=str(e),
                file_upload_id=file_upload_id,
            )
            return {"error": str(e)}
        except Exception as e:
            logger.exception(f"Unexpected error during merge for file_upload_id={file_upload_id}: {e}")
            if merged_path is not None:
                merged_path.unlink(missing_ok=True)
            file_upload.status = 4  # error
            # Never expose parser or subprocess diagnostics in persisted errors.
            file_upload.error = "invalid_file_content"
            session.commit()
            _update_merge_queue(session, queue_id, status=QueueStatus.ERROR, error="invalid_file_content")
            await _mark_offline_import_context_failed(
                batch_id=batch_id,
                error="invalid_file_content",
                file_upload_id=file_upload_id,
            )
            return {"error": "invalid_file_content"}
