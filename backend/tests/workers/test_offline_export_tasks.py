from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.task_cancellation import TaskCancelledError
from app.enums import QueueStatus
from app.models import CollectionBundleExport, Queue
from app.workers.tasks.offline_exports import export_collection_bundle


def _record(queue_id: int) -> CollectionBundleExport:
    return CollectionBundleExport(
        export_id=uuid4(),
        project_id=10,
        collection_id=20,
        user_id=1,
        queue_id=queue_id,
        status="queued",
        creation_date=datetime.now(UTC).replace(tzinfo=None),
    )


@pytest.mark.anyio
async def test_export_collection_bundle_completes_and_records_download(tmp_path) -> None:
    record = _record(7)
    queue = Queue(
        queue_id=7,
        type="offline_export",
        user_id=1,
        total=1,
        status=QueueStatus.RUNNING,
    )
    mock_session = MagicMock()
    mock_session.get.side_effect = [record, queue]
    mock_session.exec.return_value.first.return_value = queue

    def fake_export(_session, _collection_id, *, output_path, cancellation_token: object):
        del cancellation_token
        output_path.write_bytes(b"bundle")
        return {
            "counts": {"media": 1},
            "warnings": [],
        }

    with (
        patch("app.workers.tasks.offline_exports.Session", return_value=mock_session),
        patch("app.workers.tasks.offline_exports.media_root", return_value=tmp_path),
        patch(
            "app.workers.tasks.offline_exports.offline_bundle_service.export_collection_bundle",
            side_effect=fake_export,
        ),
    ):
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        result = await export_collection_bundle(
            {},
            export_id=str(record.export_id),
            queue_id=queue.queue_id,
        )

    assert result["filename"].endswith(".zip")
    assert record.status == "completed"
    assert record.size_b == len(b"bundle")
    assert record.counts == {"media": 1}
    assert record.expires_at is not None
    assert queue.status == QueueStatus.COMPLETED
    assert queue.completed == 1
    assert (tmp_path / record.path).read_bytes() == b"bundle"


@pytest.mark.anyio
async def test_export_collection_bundle_cleans_partial_file_when_cancelled(tmp_path) -> None:
    record = _record(8)
    queue = Queue(
        queue_id=8,
        type="offline_export",
        user_id=1,
        total=1,
        status=QueueStatus.RUNNING,
    )
    mock_session = MagicMock()
    mock_session.get.side_effect = [record, queue, record]

    def cancelled_export(_session, _collection_id, *, output_path, cancellation_token: object):
        del cancellation_token
        output_path.write_bytes(b"partial")
        raise TaskCancelledError("cancelled")

    with (
        patch("app.workers.tasks.offline_exports.Session", return_value=mock_session),
        patch("app.workers.tasks.offline_exports.media_root", return_value=tmp_path),
        patch(
            "app.workers.tasks.offline_exports.offline_bundle_service.export_collection_bundle",
            side_effect=cancelled_export,
        ),
    ):
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        with pytest.raises(TaskCancelledError):
            await export_collection_bundle(
                {},
                export_id=str(record.export_id),
                queue_id=queue.queue_id,
            )

    assert record.status == "cancelled"
    assert record.path is None
    assert list(tmp_path.rglob("*.part")) == []
