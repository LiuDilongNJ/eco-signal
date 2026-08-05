"""Unit tests for file merge worker task (workers/tasks/files.py)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.enums import QueueStatus, WorkerTaskType
from app.models import FileUpload, Queue
from app.workers.tasks.files import merge_file_chunks


class FakeRedisPool:
    """Minimal async iterable that mimics the Redis dependency generator."""

    def __init__(self, redis_client):
        self._redis_client = redis_client
        self._yielded = False

    def __aiter__(self):
        self._yielded = False
        return self

    async def __anext__(self):
        if self._yielded:
            raise StopAsyncIteration
        self._yielded = True
        return self._redis_client


@pytest.mark.anyio
class TestMergeFileChunksTask:
    """Tests for the merge_file_chunks ARQ task."""

    async def test_file_upload_not_found(self):
        """Returns error dict when FileUpload record does not exist."""
        mock_session = MagicMock()
        mock_session.get.return_value = None

        with patch("app.workers.tasks.files.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            result = await merge_file_chunks(
                ctx={},
                file_upload_id=9999,
                filename="test.wav",
                user_id=1,
            )

        assert result == {"error": "FileUpload not found"}

    async def test_merge_success(self):
        """Returns success dict and updates FileUpload when merge succeeds."""
        mock_session = MagicMock()
        file_upload = FileUpload(
            file_upload_id=1,
            filename="test.wav",
            status=0,
            uploader_id=1,
        )
        mock_session.get.return_value = file_upload

        merged_path = MagicMock()
        merged_path.__str__ = MagicMock(return_value="/app/sounds/tmp/pending/1/test.wav")

        with patch("app.workers.tasks.files.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.files.file_service") as mock_svc:
                with patch("app.workers.tasks.files.file_service.merge_and_validate_chunks"):
                    mock_svc.merge_and_validate_chunks.return_value = merged_path

                    result = await merge_file_chunks(
                        ctx={},
                        file_upload_id=1,
                        filename="test.wav",
                        user_id=1,
                        batch_id=None,
                    )

        assert result["status"] == "success"
        assert result["file_upload_id"] == 1
        assert file_upload.status == 1
        assert file_upload.path == "tmp/pending/1/test.wav"
        mock_session.commit.assert_called()

    async def test_photo_merge_uses_photo_content_validation(self):
        mock_session = MagicMock()
        file_upload = FileUpload(
            file_upload_id=8,
            filename="camera.tiff",
            status=0,
            uploader_id=1,
        )
        mock_session.get.return_value = file_upload
        merged_path = MagicMock()
        merged_path.__str__ = MagicMock(
            return_value="/app/sounds/tmp/pending/1/camera.tiff"
        )

        with patch("app.workers.tasks.files.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.files.file_service") as mock_svc:
                mock_svc.merge_and_validate_chunks.return_value = merged_path
                result = await merge_file_chunks(
                    ctx={},
                    file_upload_id=8,
                    filename="camera.tiff",
                    user_id=1,
                    media_type="photo",
                )

        assert result["status"] == "success"

    async def test_merge_file_not_found_error(self):
        """Sets status=4 and returns error when chunks are missing."""
        mock_session = MagicMock()
        file_upload = FileUpload(file_upload_id=2, filename="missing.wav", status=0)
        mock_session.get.return_value = file_upload

        with patch("app.workers.tasks.files.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.files.file_service") as mock_svc:
                mock_svc.merge_and_validate_chunks.side_effect = FileNotFoundError("chunks missing")

                result = await merge_file_chunks(
                    ctx={},
                    file_upload_id=2,
                    filename="missing.wav",
                    user_id=1,
                )

        assert "error" in result
        assert "chunks missing" in result["error"]
        assert file_upload.status == 4
        assert file_upload.error == "chunks missing"
        mock_session.commit.assert_called()

    async def test_merge_unexpected_exception(self):
        """Sets status=4 and returns error on unexpected exceptions."""
        mock_session = MagicMock()
        file_upload = FileUpload(file_upload_id=3, filename="bad.wav", status=0)
        mock_session.get.return_value = file_upload

        with patch("app.workers.tasks.files.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.files.file_service") as mock_svc:
                mock_svc.merge_and_validate_chunks.side_effect = RuntimeError("disk full")

                result = await merge_file_chunks(
                    ctx={},
                    file_upload_id=3,
                    filename="bad.wav",
                    user_id=1,
                )

        assert "error" in result
        assert result["error"] == "invalid_file_content"
        assert file_upload.status == 4
        assert file_upload.error == "invalid_file_content"
        mock_session.commit.assert_called()

    async def test_invalid_file_type_marks_merge_queue_failed(self, tmp_path):
        """Content validation failures remain visible in the user queue."""
        mock_session = MagicMock()
        file_upload = FileUpload(file_upload_id=7, filename="fake.wav", status=0, uploader_id=1)
        queue = Queue(queue_id=77, type="file_upload", user_id=1, total=1, status=0)
        mock_session.get.side_effect = lambda model, identifier: (
            file_upload if model is FileUpload else queue if model is Queue else None
        )
        merged_path = tmp_path / "fake.wav"
        merged_path.write_bytes(b"not audio")

        with patch("app.workers.tasks.files.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.files.file_service") as mock_svc:
                mock_svc.merge_and_validate_chunks.side_effect = HTTPException(
                    status_code=400, detail="file_type_mismatch"
                )
                result = await merge_file_chunks(
                    ctx={},
                    file_upload_id=7,
                    filename="fake.wav",
                    user_id=1,
                    queue_id=77,
                )

        expected = "file_type_mismatch: file extension does not match the actual content"
        assert result == {"error": expected}
        assert file_upload.status == 4
        assert file_upload.error == expected
        assert queue.status == 3
        assert queue.error == expected
        assert queue.start_time is not None
        assert queue.stop_time is not None

    async def test_duplicate_audio_marks_merge_queue_warning(self, tmp_path):
        mock_session = MagicMock()
        file_upload = FileUpload(
            file_upload_id=9,
            filename="duplicate.wav",
            name="duplicate.wav",
            status=0,
            uploader_id=1,
        )
        queue = Queue(queue_id=91, type="file_upload", user_id=1, total=1, status=0)
        mock_session.get.side_effect = lambda model, identifier: (
            file_upload if model is FileUpload else queue if model is Queue else None
        )
        merged_path = tmp_path / "duplicate.wav"
        merged_path.write_bytes(b"valid audio")

        with (
            patch("app.workers.tasks.files.Session", return_value=mock_session),
            patch(
                "app.workers.tasks.files.file_service.merge_and_validate_chunks",
                return_value=merged_path,
            ),
            patch("app.workers.tasks.files._md5_file", return_value="same-md5"),
            patch("app.workers.tasks.files._find_duplicate_media", return_value=321),
        ):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            result = await merge_file_chunks(
                ctx={},
                file_upload_id=9,
                filename="duplicate.wav",
                user_id=1,
                queue_id=91,
                collection_id=10,
            )

        assert result["status"] == "duplicate"
        assert file_upload.status == 5
        assert file_upload.media_id == 321
        assert queue.status == QueueStatus.WARNING
        assert queue.completed == 0
        assert queue.total == 1
        assert queue.warning == "File duplicate.wav already exists in the collection."
        assert queue.stop_time is not None
        assert not merged_path.exists()

    async def test_merge_success_without_batch_id(self):
        """Merge works correctly when batch_id is None (default)."""
        mock_session = MagicMock()
        file_upload = FileUpload(file_upload_id=4, filename="no_batch.wav", status=0)
        mock_session.get.return_value = file_upload

        merged_path = MagicMock()
        merged_path.__str__ = MagicMock(return_value="/app/sounds/tmp/pending/1/no_batch.wav")

        with patch("app.workers.tasks.files.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.files.file_service") as mock_svc:
                mock_svc.merge_and_validate_chunks.return_value = merged_path

                result = await merge_file_chunks(
                    ctx={},
                    file_upload_id=4,
                    filename="no_batch.wav",
                    user_id=1,
                )

        assert result["status"] == "success"
        mock_svc.merge_and_validate_chunks.assert_called_once_with(
            filename="no_batch.wav",
            user_id=1,
            batch_id=None,
            media_type="audio",
        )

    @pytest.mark.filterwarnings(r"ignore:unclosed Connection <redis\.asyncio\.connection\.Connection.*:ResourceWarning")
    @pytest.mark.filterwarnings(r"ignore:unclosed transport <_SelectorSocketTransport.*:ResourceWarning")
    async def test_merge_success_creates_offline_import_queue(self):
        """Offline import batches create a queue and enqueue the import worker after merge."""
        mock_session = MagicMock()
        file_upload = FileUpload(
            file_upload_id=5,
            filename="bundle.zip",
            status=0,
            uploader_id=1,
        )
        queue = Queue(queue_id=88, type="offline_import", user_id=1, total=1, status=0)
        mock_session.get.return_value = file_upload
        mock_session.refresh.side_effect = lambda obj: None

        merged_path = MagicMock()
        merged_path.__str__ = MagicMock(return_value="/app/sounds/tmp/pending/1/bundle.zip")

        class FakePublisher:
            def __init__(self):
                self.calls = []

            async def enqueue_task(self, task_name, **kwargs):
                self.calls.append((task_name, kwargs))

            async def close(self):
                return None

        fake_publisher = FakePublisher()
        fake_redis = MagicMock()
        fake_redis.aclose = AsyncMock(return_value=None)

        with patch("app.workers.tasks.files.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.files.file_service") as mock_svc, \
                patch("app.workers.tasks.files.data_import_service.get_context") as mock_get_context, \
                patch("app.workers.tasks.files.data_import_service.update_context") as mock_update_context, \
                patch("app.workers.tasks.files.get_redis_client", side_effect=[FakeRedisPool(fake_redis), FakeRedisPool(fake_redis)]), \
                patch("app.api.deps.Redis", return_value=fake_redis), \
                patch("app.workers.tasks.files.TaskPublisher", return_value=fake_publisher), \
                patch("app.workers.tasks.files.Queue", return_value=queue), \
                patch("app.workers.tasks.files.file_service.merge_and_validate_chunks"):
                    mock_svc.merge_and_validate_chunks.return_value = merged_path
                    mock_get_context.return_value = {
                        "project_id": 12,
                        "uploader_id": 1,
                        "file_upload_id": None,
                    }

                    result = await merge_file_chunks(
                        ctx={},
                        file_upload_id=5,
                        filename="bundle.zip",
                        user_id=1,
                        batch_id="offline-batch",
                    )

        assert result["status"] == "success"
        assert queue.type == "offline_import"
        assert mock_update_context.await_count == 1
        assert fake_publisher.calls[0][0] == WorkerTaskType.IMPORT_COLLECTION_BUNDLE
        assert fake_publisher.calls[0][1]["queue_id"] == queue.queue_id

    async def test_merge_failure_marks_offline_import_context_failed(self):
        """Offline import merge failure updates the lightweight import context."""
        mock_session = MagicMock()
        file_upload = FileUpload(file_upload_id=6, filename="bundle.zip", status=0)
        mock_session.get.return_value = file_upload
        fake_redis = MagicMock()
        fake_redis.aclose = AsyncMock(return_value=None)

        with patch("app.workers.tasks.files.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.files.file_service") as mock_svc, \
                patch("app.workers.tasks.files.get_redis_client", return_value=FakeRedisPool(fake_redis)), \
                patch("app.api.deps.Redis", return_value=fake_redis), \
                patch("app.workers.tasks.files.data_import_service.get_context") as mock_get_context, \
                patch("app.workers.tasks.files.data_import_service.update_context") as mock_update_context:
                mock_svc.merge_and_validate_chunks.side_effect = FileNotFoundError("chunks missing")
                mock_get_context.return_value = {"project_id": 1}

                result = await merge_file_chunks(
                    ctx={},
                    file_upload_id=6,
                    filename="bundle.zip",
                    user_id=1,
                    batch_id="offline-batch",
                )

        assert result == {"error": "chunks missing"}
        assert file_upload.status == 4
        assert file_upload.error == "chunks missing"
        assert mock_update_context.await_count == 1
