"""Business logic for asynchronous collection bundle exports."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import Session

from app.enums import QueueStatus, WorkerTaskType
from app.media_paths import media_root
from app.models import CollectionBundleExport, Queue, User
from app.repositories import collection_bundle_export_repository
from app.schemas.collection_bundle_export import CollectionBundleExportPublic
from app.workers.publisher import TaskPublisher

EXPORT_RETENTION_HOURS = 24
EXPORT_DIRECTORY = Path("offline_exports")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _to_public(record: CollectionBundleExport) -> CollectionBundleExportPublic:
    return CollectionBundleExportPublic.model_validate(record, from_attributes=True)


def _remove_artifact_file(record: CollectionBundleExport) -> None:
    if not record.path:
        return
    root = media_root().resolve()
    target = (root / record.path).resolve()
    if target.is_relative_to(root) and target.is_file():
        target.unlink()
    parent = target.parent
    if parent.is_relative_to(root) and parent != root:
        try:
            parent.rmdir()
        except OSError:
            pass


def expire_if_needed(session: Session, record: CollectionBundleExport) -> None:
    if (
        record.status == "completed"
        and record.expires_at is not None
        and record.expires_at <= _now()
    ):
        _remove_artifact_file(record)
        record.status = "expired"
        record.path = None
        session.add(record)
        session.commit()
        session.refresh(record)


async def create_export(
    session: Session,
    *,
    project_id: int,
    collection_id: int,
    current_user: User,
    publisher: TaskPublisher,
) -> CollectionBundleExportPublic:
    queue = Queue(
        type="offline_export",
        user_id=current_user.user_id,
        total=1,
        status=QueueStatus.PENDING,
    )
    session.add(queue)
    session.commit()
    session.refresh(queue)

    record = CollectionBundleExport(
        project_id=project_id,
        collection_id=collection_id,
        user_id=current_user.user_id,
        queue_id=queue.queue_id,
        status="queued",
    )
    session.add(record)
    session.commit()
    session.refresh(record)

    try:
        await publisher.enqueue_task(
            WorkerTaskType.EXPORT_COLLECTION_BUNDLE,
            export_id=str(record.export_id),
            queue_id=queue.queue_id,
        )
    except Exception as exc:
        record.status = "failed"
        record.error = str(exc)
        record.completion_date = _now()
        queue.status = QueueStatus.ERROR
        queue.error = "Failed to enqueue collection bundle export"
        queue.stop_time = _now()
        session.add(record)
        session.add(queue)
        session.commit()
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue collection bundle export",
        ) from exc

    return _to_public(record)


def list_exports(
    session: Session,
    *,
    project_id: int,
    current_user: User,
    is_admin: bool,
) -> list[CollectionBundleExportPublic]:
    records = collection_bundle_export_repository.list_recent(
        session,
        project_id=project_id,
        user_id=None if is_admin else current_user.user_id,
    )
    for record in records:
        expire_if_needed(session, record)
    return [_to_public(record) for record in records if record.status != "expired"]


def get_export(
    session: Session,
    export_id: UUID,
) -> CollectionBundleExport:
    record = collection_bundle_export_repository.get(session, export_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Collection bundle export not found")
    expire_if_needed(session, record)
    return record


def get_download_path(record: CollectionBundleExport) -> Path:
    if record.status == "expired":
        raise HTTPException(status_code=410, detail="Collection bundle export has expired")
    if record.status != "completed" or not record.path or not record.filename:
        raise HTTPException(status_code=409, detail="Collection bundle export is not ready")

    root = media_root().resolve()
    target = (root / record.path).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(status_code=500, detail="Invalid collection bundle export path")
    if not target.is_file():
        raise HTTPException(status_code=410, detail="Collection bundle export file is missing")
    return target


def mark_cancelled_exports(session: Session, queue_ids: list[int]) -> None:
    records = collection_bundle_export_repository.get_by_queue_ids(session, queue_ids)
    if not records:
        return
    for record in records:
        _remove_artifact_file(record)
        record.status = "cancelled"
        record.error = "Task cancelled by user"
        record.path = None
        record.completion_date = _now()
        session.add(record)
    session.commit()
