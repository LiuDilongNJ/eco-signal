from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.enums import QueueStatus
from app.models import CollectionBundleExport, Queue, User
from app.services import collection_bundle_export_service


def _record(**overrides) -> CollectionBundleExport:
    values = {
        "export_id": uuid4(),
        "project_id": 10,
        "collection_id": 20,
        "user_id": 1,
        "queue_id": 30,
        "status": "queued",
        "creation_date": datetime.now(UTC).replace(tzinfo=None),
    }
    values.update(overrides)
    return CollectionBundleExport(**values)


@pytest.mark.anyio
async def test_create_export_marks_queue_and_record_failed_when_publish_fails() -> None:
    session = MagicMock()
    queue_ids = iter([31])

    def refresh(item) -> None:
        if isinstance(item, Queue) and item.queue_id is None:
            item.queue_id = next(queue_ids)

    session.refresh.side_effect = refresh
    publisher = MagicMock()
    publisher.enqueue_task = AsyncMock(side_effect=RuntimeError("broker unavailable"))
    user = User(user_id=1, username="export-user", name="Export User", email="export@example.com")

    with pytest.raises(HTTPException) as exc_info:
        await collection_bundle_export_service.create_export(
            session,
            project_id=10,
            collection_id=20,
            current_user=user,
            publisher=publisher,
        )

    assert exc_info.value.status_code == 503
    added = [call.args[0] for call in session.add.call_args_list]
    queue = next(item for item in added if isinstance(item, Queue))
    record = next(item for item in added if isinstance(item, CollectionBundleExport))
    assert queue.status == QueueStatus.ERROR
    assert record.status == "failed"
    assert record.error == "broker unavailable"


def test_list_exports_filters_expired_records_and_scopes_non_admin(monkeypatch) -> None:
    active = _record(status="queued")
    expired = _record(
        status="completed",
        expires_at=(datetime.now(UTC) - timedelta(minutes=1)).replace(tzinfo=None),
    )
    session = MagicMock()
    repository = MagicMock()
    repository.list_recent.return_value = [active, expired]
    monkeypatch.setattr(
        collection_bundle_export_service,
        "collection_bundle_export_repository",
        repository,
    )
    user = User(user_id=8, username="reader", name="Reader", email="reader@example.com")

    result = collection_bundle_export_service.list_exports(
        session,
        project_id=10,
        current_user=user,
        is_admin=False,
    )

    assert [item.export_id for item in result] == [active.export_id]
    repository.list_recent.assert_called_once_with(session, project_id=10, user_id=8)
    assert expired.status == "expired"


def test_get_export_missing_and_download_path_errors(monkeypatch, tmp_path: Path) -> None:
    repository = MagicMock()
    repository.get.return_value = None
    monkeypatch.setattr(
        collection_bundle_export_service,
        "collection_bundle_export_repository",
        repository,
    )
    with pytest.raises(HTTPException) as missing:
        collection_bundle_export_service.get_export(MagicMock(), uuid4())
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as expired:
        collection_bundle_export_service.get_download_path(_record(status="expired"))
    assert expired.value.status_code == 410
    with pytest.raises(HTTPException) as pending:
        collection_bundle_export_service.get_download_path(_record(status="queued"))
    assert pending.value.status_code == 409

    monkeypatch.setattr(collection_bundle_export_service, "media_root", lambda: tmp_path)
    with pytest.raises(HTTPException) as unsafe:
        collection_bundle_export_service.get_download_path(
            _record(status="completed", path="../outside.zip", filename="outside.zip")
        )
    assert unsafe.value.status_code == 500
    with pytest.raises(HTTPException) as missing_file:
        collection_bundle_export_service.get_download_path(
            _record(status="completed", path="offline_exports/missing.zip", filename="missing.zip")
        )
    assert missing_file.value.status_code == 410


def test_mark_cancelled_exports_removes_artifacts(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "offline_exports" / "user" / "bundle.zip"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"bundle")
    record = _record(
        status="completed",
        path="offline_exports/user/bundle.zip",
        filename="bundle.zip",
    )
    repository = MagicMock()
    repository.get_by_queue_ids.return_value = [record]
    monkeypatch.setattr(
        collection_bundle_export_service,
        "collection_bundle_export_repository",
        repository,
    )
    monkeypatch.setattr(collection_bundle_export_service, "media_root", lambda: tmp_path)
    session = MagicMock()

    collection_bundle_export_service.mark_cancelled_exports(session, [record.queue_id])

    assert not target.exists()
    assert record.status == "cancelled"
    assert record.path is None
    session.commit.assert_called_once()

    repository.get_by_queue_ids.return_value = []
    session.reset_mock()
    collection_bundle_export_service.mark_cancelled_exports(session, [999])
    session.commit.assert_not_called()


def test_delete_queue_exports_removes_artifacts_and_records(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "offline_exports" / "user" / "bundle.zip"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"bundle")
    record = _record(
        status="completed",
        path="offline_exports/user/bundle.zip",
        filename="bundle.zip",
    )
    monkeypatch.setattr(collection_bundle_export_service, "media_root", lambda: tmp_path)
    session = MagicMock()

    collection_bundle_export_service.delete_queue_exports(session, [record])

    assert not target.exists()
    session.delete.assert_called_once_with(record)


def test_remove_artifact_tolerates_empty_path_and_nonempty_parent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(collection_bundle_export_service, "media_root", lambda: tmp_path)
    collection_bundle_export_service._remove_artifact_file(_record(path=None))

    directory = tmp_path / "offline_exports" / "shared"
    directory.mkdir(parents=True)
    (directory / "keep.txt").write_text("keep")
    target = directory / "remove.zip"
    target.write_bytes(b"remove")
    collection_bundle_export_service._remove_artifact_file(
        _record(path="offline_exports/shared/remove.zip")
    )

    assert not target.exists()
    assert directory.exists()
