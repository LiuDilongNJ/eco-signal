"""Background collection bundle export tasks."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from app.core.db import engine
from app.core.task_cancellation import (
    TASK_CANCELLED_MESSAGE,
    CancellationToken,
    TaskCancelledError,
)
from app.enums import QueueStatus
from app.media_paths import media_root
from app.models import CollectionBundleExport, Queue
from app.services import collection_bundle_export_service, offline_bundle_service

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _delete_if_present(path: Path) -> None:
    if path.is_file():
        path.unlink()


async def export_collection_bundle(
    ctx: dict[str, Any],
    export_id: str,
    queue_id: int,
) -> dict[str, Any]:
    """Generate a complete collection bundle and persist its download metadata."""
    cancellation_token: CancellationToken | None = ctx.get("cancellation_token")
    parsed_export_id = UUID(export_id)
    with Session(engine) as session:
        record = session.get(CollectionBundleExport, parsed_export_id)
        queue = session.get(Queue, queue_id)
        if record is None or queue is None:
            raise RuntimeError("Collection bundle export context not found")

        relative_dir = (
            collection_bundle_export_service.EXPORT_DIRECTORY
            / str(record.user_id)
            / str(record.export_id)
        )
        filename = f"collection-{record.collection_id}-{record.export_id}.zip"
        final_path = media_root() / relative_dir / filename
        temporary_path = final_path.with_suffix(".zip.part")
        final_path.parent.mkdir(parents=True, exist_ok=True)

        record.status = "running"
        record.error = None
        session.add(record)
        session.commit()

        try:
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            result = offline_bundle_service.export_collection_bundle(
                session,
                record.collection_id,
                output_path=temporary_path,
                cancellation_token=cancellation_token,
            )
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()

            locked_queue = session.exec(
                select(Queue).where(Queue.queue_id == queue_id).with_for_update()
            ).first()
            if locked_queue is None:
                raise RuntimeError("Queue not found")
            if (
                locked_queue.status == QueueStatus.ERROR
                and locked_queue.error == TASK_CANCELLED_MESSAGE
            ):
                if cancellation_token is not None:
                    cancellation_token.cancel()
                raise TaskCancelledError("Task cancellation requested")

            temporary_path.replace(final_path)
            completed_at = _now()
            record.status = "completed"
            record.filename = filename
            record.path = (relative_dir / filename).as_posix()
            record.size_b = final_path.stat().st_size
            record.counts = result["counts"]
            record.warnings = result["warnings"]
            record.error = None
            record.completion_date = completed_at
            record.expires_at = completed_at + timedelta(
                hours=collection_bundle_export_service.EXPORT_RETENTION_HOURS
            )
            locked_queue.status = QueueStatus.COMPLETED
            locked_queue.completed = 1
            locked_queue.total = 1
            locked_queue.error = None
            locked_queue.warning = (
                "; ".join(result["warnings"])[:1000] if result["warnings"] else None
            )
            locked_queue.stop_time = completed_at
            session.add(record)
            session.add(locked_queue)
            session.commit()
            return {
                "export_id": export_id,
                "queue_id": queue_id,
                "filename": filename,
                "counts": result["counts"],
                "warnings": result["warnings"],
            }
        except TaskCancelledError:
            session.rollback()
            _delete_if_present(temporary_path)
            _delete_if_present(final_path)
            record = session.get(CollectionBundleExport, parsed_export_id)
            if record is not None:
                record.status = "cancelled"
                record.path = None
                record.error = TASK_CANCELLED_MESSAGE
                record.completion_date = _now()
                session.add(record)
                session.commit()
            raise
        except Exception as exc:
            session.rollback()
            _delete_if_present(temporary_path)
            _delete_if_present(final_path)
            record = session.get(CollectionBundleExport, parsed_export_id)
            if record is not None:
                record.status = "failed"
                record.path = None
                record.error = str(exc)
                record.completion_date = _now()
                session.add(record)
                session.commit()
            logger.exception("Collection bundle export failed: export_id=%s", export_id)
            raise
