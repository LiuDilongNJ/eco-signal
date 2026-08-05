"""Unit tests for offline import worker task (workers/tasks/offline_imports.py)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import FileUpload, Queue, User
from app.workers.tasks.offline_imports import import_collection_bundle


@pytest.mark.anyio
class TestOfflineImportTask:
    """Tests for the import_collection_bundle ARQ task."""

    async def test_import_marks_queue_running_then_completed(self):
        """Successful imports update both queue and lightweight context states."""
        mock_session = MagicMock()
        queue = Queue(queue_id=9, type="offline_import", user_id=1, total=1, status=0)
        file_upload = FileUpload(
            file_upload_id=5,
            filename="bundle.zip",
            name="bundle.zip",
            path="tmp/pending/1/bundle.zip",
            uploader_id=1,
            directory=1,
            status=1,
        )
        uploader = User(user_id=1, username="admin", name="Admin", email="admin@example.com", password="x", role_id=1)
        result_payload = MagicMock(collection_id=77)
        result_payload.model_dump.return_value = {"collection_id": 77}
        mock_session.get.side_effect = [queue, file_upload, uploader, queue, file_upload]

        async def fake_pool():
            redis = MagicMock()
            yield redis

        with patch("app.workers.tasks.offline_imports.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.offline_imports.get_redis_client", side_effect=[fake_pool(), fake_pool()]), \
                patch("app.workers.tasks.offline_imports.data_import_service.update_context", new=AsyncMock()) as mock_update_context, \
                patch("app.workers.tasks.offline_imports.offline_bundle_service.import_collection_bundle_from_file_upload", return_value=result_payload) as mock_import:
                result = await import_collection_bundle(
                    ctx={},
                    batch_id="offline-batch",
                    project_id=12,
                    uploader_id=1,
                    file_upload_id=5,
                    queue_id=9,
                )

        assert result["status"] == "success"
        assert queue.status == 2
        assert queue.completed == 1
        assert file_upload.status == 3
        assert mock_import.call_args.kwargs["batch_id"] == "offline-batch"
        assert mock_update_context.await_args_list[0].kwargs["status"] == "running"
        assert mock_update_context.await_args_list[1].kwargs["status"] == "completed"

    async def test_import_marks_queue_error_on_failure(self):
        """Failed imports update queue and lightweight context to error states."""
        mock_session = MagicMock()
        queue = Queue(queue_id=10, type="offline_import", user_id=1, total=1, status=0)
        file_upload = FileUpload(
            file_upload_id=6,
            filename="bundle.zip",
            name="bundle.zip",
            path="tmp/pending/1/bundle.zip",
            uploader_id=1,
            directory=1,
            status=1,
        )
        uploader = User(user_id=1, username="admin", name="Admin", email="admin@example.com", password="x", role_id=1)
        mock_session.get.side_effect = [queue, file_upload, uploader, queue, file_upload]

        async def fake_pool():
            redis = MagicMock()
            yield redis

        with patch("app.workers.tasks.offline_imports.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.offline_imports.get_redis_client", side_effect=[fake_pool(), fake_pool()]), \
                patch("app.workers.tasks.offline_imports.data_import_service.update_context", new=AsyncMock()) as mock_update_context, \
                patch("app.workers.tasks.offline_imports.offline_bundle_service.import_collection_bundle_from_file_upload", side_effect=RuntimeError("bad zip")):
                result = await import_collection_bundle(
                    ctx={},
                    batch_id="offline-batch",
                    project_id=12,
                    uploader_id=1,
                    file_upload_id=6,
                    queue_id=10,
                )

        assert result["error"] == "bad zip"
        assert queue.status == 3
        assert queue.error == "bad zip"
        assert file_upload.status == 4
        assert file_upload.error == "bad zip"
        mock_session.rollback.assert_called_once()
        assert mock_update_context.await_args_list[0].kwargs["status"] == "running"
        assert mock_update_context.await_args_list[1].kwargs["status"] == "failed"
