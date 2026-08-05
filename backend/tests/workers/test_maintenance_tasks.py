"""Unit tests for maintenance worker tasks."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.models import FileUpload, Role, User
from app.workers.tasks.maintenance import (
    cleanup_expired_chunks,
    cleanup_expired_offline_imports,
    startup_sync_network_nodes,
)


@pytest.mark.anyio
class TestMaintenanceTasks:
    """Tests for maintenance ARQ tasks."""

    @patch("pathlib.Path.exists")
    async def test_cleanup_no_dir(self, mock_exists):
        """Returns deleted=0 if chunks directory does not exist."""
        mock_exists.return_value = False
        result = await cleanup_expired_chunks(ctx={})
        assert result == {"deleted": 0}

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.iterdir")
    @patch("shutil.rmtree")
    @patch("pathlib.Path.rmdir")
    @patch("time.time")
    async def test_cleanup_expired_chunks(self, mock_time, mock_rmdir, mock_rmtree, mock_iterdir, mock_exists):
        """Cleans up expired directories and empty batch directories."""
        mock_exists.return_value = True
        mock_time.return_value = 1000000
        
        # Mock directory structure:
        # chunks/batch_1/file_1 (expired)
        # chunks/batch_1/file_2 (not expired)
        # chunks/batch_2/file_3 (expired) -> batch_2 becomes empty
        
        mock_batch_1 = MagicMock(spec=Path)
        mock_batch_1.is_dir.return_value = True
        mock_batch_1.exists.return_value = True
        
        mock_file_1 = MagicMock(spec=Path)
        mock_file_1.is_dir.return_value = True
        mock_file_1.stat.return_value.st_mtime = 1000000 - (30 * 3600) # 30h ago (expired)
        
        mock_file_2 = MagicMock(spec=Path)
        mock_file_2.is_dir.return_value = True
        mock_file_2.stat.return_value.st_mtime = 1000000 - (2 * 3600) # 2h ago (not expired)
        
        mock_batch_1.iterdir.return_value = [mock_file_1, mock_file_2]
        
        mock_batch_2 = MagicMock(spec=Path)
        mock_batch_2.is_dir.return_value = True
        mock_batch_2.exists.return_value = True
        
        mock_file_3 = MagicMock(spec=Path)
        mock_file_3.is_dir.return_value = True
        mock_file_3.stat.return_value.st_mtime = 1000000 - (48 * 3600) # 48h ago (expired)
        
        mock_batch_2.iterdir.side_effect = [[mock_file_3], []] # First iteration find file, second check if empty
        
        mock_iterdir.return_value = [mock_batch_1, mock_batch_2]
        
        result = await cleanup_expired_chunks(ctx={}, max_age_hours=24)
        
        assert result == {"deleted": 2}
        assert mock_rmtree.call_count == 2
        # Assert on the mock instance method instead of the class patch
        mock_batch_2.rmdir.assert_called_once()
        mock_batch_1.rmdir.assert_not_called()

    @patch("app.services.network_service.sync_from_host")
    @patch("app.workers.tasks.maintenance.logger")
    async def test_startup_sync_network_nodes_success(self, mock_logger, mock_sync_from_host):
        """Startup sync runs once and logs trigger=startup with result."""
        result_obj = MagicMock()
        result_obj.synced = 3
        result_obj.message = "ok"
        mock_sync_from_host.return_value = result_obj

        result = await startup_sync_network_nodes(ctx={})

        assert result == {"synced": 3, "message": "ok"}
        mock_sync_from_host.assert_called_once()
        mock_logger.info.assert_any_call("Network sync started: trigger=startup")
        mock_logger.info.assert_any_call(
            "Network sync completed: trigger=startup synced=%d message=%s",
            3,
            "ok",
        )

    @patch("app.services.network_service.sync_from_host")
    @patch("app.workers.tasks.maintenance.logger")
    async def test_startup_sync_network_nodes_failure(self, mock_logger, mock_sync_from_host):
        """Startup sync failure is logged and should not raise."""
        mock_sync_from_host.side_effect = RuntimeError("boom")

        result = await startup_sync_network_nodes(ctx={})

        assert result == {"synced": 0, "message": "startup sync failed"}
        mock_sync_from_host.assert_called_once()
        mock_logger.info.assert_any_call("Network sync started: trigger=startup")
        mock_logger.exception.assert_called_once_with("Network sync failed: trigger=startup")

    @patch("app.workers.tasks.maintenance.media_root")
    @patch("app.workers.tasks.maintenance.get_redis_client")
    async def test_cleanup_expired_offline_imports(self, mock_get_redis_client, mock_media_root, db):
        bundle_path = Path("/tmp/offline-bundle.zip")

        with Session(engine) as worker_db:
            role = worker_db.exec(select(Role).order_by(Role.role_id.asc())).first()
            if role is None:
                role = Role(name=f"Maintenance Role {uuid4().hex[:8]}")
                worker_db.add(role)
                worker_db.commit()
                worker_db.refresh(role)

            suffix = uuid4().hex[:8]
            uploader = User(
                username=f"maint_{suffix}",
                name="Maintenance Uploader",
                email=f"maint_{suffix}@example.com",
                password="x",
                role_id=role.role_id,
            )
            worker_db.add(uploader)
            worker_db.commit()
            worker_db.refresh(uploader)
            uploader_id = uploader.user_id
            upload = FileUpload(
                path="tmp/pending/1/offline-bundle.zip",
                filename="offline-bundle.zip",
                name="offline-bundle.zip",
                directory=1,
                uploader_id=uploader_id,
                status=4,
            )
            worker_db.add(upload)
            worker_db.commit()
            worker_db.refresh(upload)
            upload_id = upload.file_upload_id

        class FakeRedis:
            async def keys(self, pattern):
                return ["offline-import:test-batch"]

            async def get(self, key):
                return json.dumps(
                    {
                        "batch_id": "test-batch",
                        "project_id": 1,
                        "uploader_id": uploader_id,
                        "file_upload_id": upload_id,
                        "queue_id": None,
                        "status": "failed",
                        "error": "boom",
                        "summary_json": None,
                        "cleanup_after": "2000-01-01 00:00:00",
                        "creation_date": "2000-01-01 00:00:00",
                        "update_date": "2000-01-01 00:00:00",
                    }
                )

            async def delete(self, key):
                return 1

        async def fake_redis_dependency():
            yield FakeRedis()

        mock_get_redis_client.return_value = fake_redis_dependency()
        mock_media_root.return_value = bundle_path.parent

        with patch.object(Path, "exists", return_value=True), patch.object(Path, "unlink") as mock_unlink:
            result = await cleanup_expired_offline_imports(ctx={})

        assert result == {"deleted": 1}
        mock_unlink.assert_called_once()

        with Session(engine) as worker_db:
            persisted = worker_db.get(FileUpload, upload_id)
            if persisted is not None:
                worker_db.delete(persisted)
            persisted_uploader = worker_db.get(User, uploader_id)
            if persisted_uploader is not None:
                worker_db.delete(persisted_uploader)
            worker_db.commit()
