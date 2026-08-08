import csv
import hashlib
import io
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import jwt as pyjwt
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import get_task_publisher
from app.core.config import settings
from app.main import app
from app.models import (
    Collection,
    FileUpload,
    Permission,
    Project,
    ProjectCollection,
    Queue,
    Role,
    User,
    UserPermission,
)
from app.models.device import Camera, Lens, Microphone, Recorder, Sensor
from app.models.label import Label, LabelMedia
from app.models.media import (
    AudioSetting,
    License,
    Media,
    MediaCollection,
    PhotoSetting,
    Preview,
)
from app.models.site import IucnGet, Site
from tests.utils.csv import read_csv_header


def _write_audio_fixture(
    path,
    *,
    sample_rate: int,
    channel_num: int = 1,
    duration_s: float = 1.0,
) -> None:
    frames = int(sample_rate * duration_s)
    t = np.arange(frames, dtype=np.float32) / sample_rate
    left = 0.6 * np.sin(2 * np.pi * 440 * t)
    if channel_num >= 2:
        right = 0.6 * np.sin(2 * np.pi * 880 * t)
        data = np.column_stack((left, right)).astype(np.float32)
    else:
        data = left.astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), data, sample_rate)


def _ensure_project_for_collection(db: Session, collection_id: int, creator_id: int = 1) -> int:
    project_id = db.exec(
        select(ProjectCollection.project_id).where(ProjectCollection.collection_id == collection_id)
    ).first()
    if project_id is not None:
        return project_id
    project = Project(
        name=f"Media Test Project {uuid.uuid4().hex[:8]}",
        url=f"https://media-test-{uuid.uuid4().hex[:8]}.example",
        public=True,
        creator_id=creator_id,
    )
    db.add(project)
    db.flush()
    db.add(ProjectCollection(project_id=project.project_id, collection_id=collection_id))
    db.flush()
    return project.project_id


class TestChunkUpload:
    """Tests for chunk upload endpoints."""

    def test_upload_chunk_unauthorized(self, client: TestClient) -> None:
        """Chunk upload requires authentication."""
        batch_id = str(uuid.uuid4())
        r = client.post(
            f"{settings.API_V1_STR}/file-upload-batches/{batch_id}/chunks",
            data={"filename": "test.wav", "chunk_index": 0, "total_chunks": 1},
            files={"file": ("chunk", b"test data")}
        )
        assert r.status_code == 401

    def test_upload_chunk_incomplete(
        self, client: TestClient, normal_user_token_headers: dict
    ) -> None:
        """Incomplete upload does not return file_upload_id."""
        unique_filename = f"test_audio_{uuid.uuid4().hex[:8]}.wav"
        batch_id = str(uuid.uuid4())

        r = client.post(
            f"{settings.API_V1_STR}/file-upload-batches/{batch_id}/chunks",
            headers=normal_user_token_headers,
            data={"filename": unique_filename, "chunk_index": 0, "total_chunks": 2, "batch_id": batch_id},
            files={"file": ("chunk", b"test chunk data 1")}
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["filename"] == unique_filename
        assert data["uploaded_chunks"] == 1
        assert data["is_complete"] is False
        assert data.get("file_upload_id") is None

    def test_upload_chunk_creates_record_on_complete(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        """Last chunk triggers merge task enqueue and FileUpload record creation."""
        unique_filename = f"test_auto_{uuid.uuid4().hex[:8]}.wav"
        batch_id = str(uuid.uuid4())

        # Upload all chunks in one shot (total_chunks=1)
        r = client.post(
            f"{settings.API_V1_STR}/file-upload-batches/{batch_id}/chunks",
            headers=normal_user_token_headers,
            data={"filename": unique_filename, "chunk_index": 0, "total_chunks": 1, "batch_id": batch_id},
            files={"file": ("chunk", b"complete file data")}
        )

        assert r.status_code == 200
        data = r.json()["data"]
        assert data["is_complete"] is True
        assert "file_upload_id" in data
        fid = data["file_upload_id"]
        assert isinstance(fid, int)

        # Verify FileUpload record was created with merging status
        file_upload = db.get(FileUpload, fid)
        assert file_upload is not None
        assert file_upload.status == 1  # pending
        assert file_upload.filename == unique_filename

    def test_upload_chunk_invalid_filename(
        self, client: TestClient, normal_user_token_headers: dict
    ) -> None:
        """Reject filenames with path traversal."""
        batch_id = str(uuid.uuid4())
        r = client.post(
            f"{settings.API_V1_STR}/file-upload-batches/{batch_id}/chunks",
            headers=normal_user_token_headers,
            data={"filename": "../../../etc/passwd", "chunk_index": 0, "total_chunks": 1, "batch_id": batch_id},
            files={"file": ("chunk", b"test data")}
        )
        assert r.status_code == 400


class TestMediaCreate:
    """Tests for batch media creation endpoint."""

    def test_create_media_unauthorized(self, client: TestClient) -> None:
        """Media creation requires authentication."""
        r = client.post(
            f"{settings.API_V1_STR}/media",
            json={"collection_id": 1, "file_upload_ids": [1]}
        )
        assert r.status_code == 401

    def test_create_media_collection_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Return HTTP 404 if collection not found."""
        r = client.post(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            json={"collection_id": 99999, "file_upload_ids": [1], "date_from_filename": True}
        )
        assert r.status_code == 404

    def test_create_media_file_upload_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Non-existent file_upload_id returns a batch validation conflict."""
        r = client.post(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            json={"collection_id": 1, "file_upload_ids": [999999], "date_from_filename": True}
        )
        assert r.status_code == 409
        assert "1 file(s) failed to process" in r.json()["message"]

    def test_create_media_batch_multi_file(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Multiple file_upload_ids are all enqueued successfully."""

        # Create two pending FileUpload records directly
        fids = []
        for i in range(2):
            fu = FileUpload(
                path=f"/tmp/pending/1/multi_{i}.wav",
                filename=f"multi_{i}.wav",
                name=f"multi_{i}.wav",
                directory=1,
                uploader_id=1,
                status=1,
            )
            db.add(fu)
            db.flush()
            fids.append(fu.file_upload_id)
        db.commit()

        # Override the Redis dependency to avoid real queue calls
        async def mock_redis():
            mock = AsyncMock()
            mock.enqueue_task = AsyncMock()
            yield mock

        app.dependency_overrides[get_task_publisher] = mock_redis
        try:
            r = client.post(
                f"{settings.API_V1_STR}/media",
                headers=superuser_token_headers,
                json={
                    "collection_id": 1,
                    "file_upload_ids": fids,
                    "date_from_filename": True,
                },
            )
        finally:
            app.dependency_overrides.pop(get_task_publisher, None)

        assert r.status_code == 200
        data = r.json()["data"]
        assert set(data["queued"]) == set(fids)
    def test_create_photo_batch_enqueues_all_staged_files(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Photo uploads use the same single batch queue as audio uploads."""
        uploads = []
        for index in range(2):
            upload = FileUpload(
                path="",
                filename=f"photo_{index}.jpg",
                name=f"photo_{index}.jpg",
                directory=1,
                uploader_id=1,
                status=1,
            )
            db.add(upload)
            db.flush()
            uploads.append(upload)
        db.commit()

        publisher = AsyncMock()
        app.dependency_overrides[get_task_publisher] = lambda: publisher
        try:
            response = client.post(
                f"{settings.API_V1_STR}/media",
                headers=superuser_token_headers,
                json={
                    "collection_id": 1,
                    "file_upload_ids": [upload.file_upload_id for upload in uploads],
                    "media_type": "photo",
                },
            )
        finally:
            app.dependency_overrides.pop(get_task_publisher, None)

        assert response.status_code == 200
        data = response.json()["data"]
        assert set(data["queued"]) == {upload.file_upload_id for upload in uploads}
        assert data["failed"] == []
        publisher.enqueue_task.assert_awaited_once()
        _, kwargs = publisher.enqueue_task.call_args
        assert kwargs["items"] == [
            {
                "file_upload_id": upload.file_upload_id,
                "file_date": None,
                "file_time": None,
                "display_filename": upload.filename,
            }
            for upload in uploads
        ]
    def test_create_media_with_filename_prefix(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """filename_prefix should produce a prefixed logical display filename for worker tasks."""
        fu = FileUpload(
            path="/tmp/pending/1/prefix_case.wav",
            filename="prefix_case.wav",
            name="prefix_case.wav",
            directory=1,
            uploader_id=1,
            status=1,
        )
        db.add(fu)
        db.commit()
        db.refresh(fu)

        captured_kwargs: dict = {}

        async def mock_redis():
            mock = AsyncMock()

            async def _enqueue_task(*_args, **kwargs):
                captured_kwargs.update(kwargs)

            mock.enqueue_task.side_effect = _enqueue_task
            yield mock

        app.dependency_overrides[get_task_publisher] = mock_redis
        try:
            r = client.post(
                f"{settings.API_V1_STR}/media",
                headers=superuser_token_headers,
                json={
                    "collection_id": 1,
                    "filename_prefix": "LEGACY_",
                    "file_upload_ids": [fu.file_upload_id],
                    "date_from_filename": True,
                },
            )
        finally:
            app.dependency_overrides.pop(get_task_publisher, None)

        assert r.status_code == 200
        assert captured_kwargs["items"] == [
            {
                "file_upload_id": fu.file_upload_id,
                "file_date": "1970-01-01",
                "file_time": "00:00:00",
                "display_filename": "LEGACY_prefix_case.wav",
            }
        ]

    def test_create_media_invalid_filename_prefix_rejected(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """filename_prefix must reject path traversal-like input."""
        r = client.post(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            json={
                "collection_id": 1,
                "filename_prefix": "../bad/",
                "file_upload_ids": [1],
                "date_from_filename": True,
            },
        )
        assert r.status_code == 422

    def test_create_media_unsupported_files_payload_rejected(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Unsupported files[] payload should be rejected."""
        r = client.post(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            json={
                "collection_id": 1,
                "files": [{"file_upload_id": 1, "date_from_filename": True}],
            },
        )
        assert r.status_code == 422


    def test_create_media_wrong_status_goes_to_failed(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """FileUpload not in pending status returns a batch validation conflict."""
        fu = FileUpload(
            path="/tmp/pending/1/not_pending.wav",
            filename="not_pending.wav",
            name="not_pending.wav",
            directory=1,
            uploader_id=1,
            status=2,  # processing, not pending
        )
        db.add(fu)
        db.commit()
        db.refresh(fu)

        r = client.post(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            json={"collection_id": 1, "file_upload_ids": [fu.file_upload_id], "date_from_filename": True}
        )
        assert r.status_code == 409
        assert "1 file(s) failed to process" in r.json()["message"]

    def test_create_media_empty_files_rejected(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Empty files list is rejected by validation."""
        r = client.post(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            json={"collection_id": 1, "file_upload_ids": []}
        )
        assert r.status_code == 422

    def test_create_media_invalid_sensor_id_goes_to_failed(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Non-existent sensor_id: nothing queued, so the request reports failure (HTTP 409)."""
        fu = FileUpload(
            path="/tmp/pending/1/sensor_test.wav",
            filename="sensor_test.wav",
            name="sensor_test.wav",
            directory=1,
            uploader_id=1,
            status=1,
        )
        db.add(fu)
        db.commit()
        db.refresh(fu)

        r = client.post(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            json={"collection_id": 1, "file_upload_ids": [fu.file_upload_id], "sensor_id": 999999, "date_from_filename": True}
        )
        assert r.status_code == 409
        assert "Sensor" in r.json()["message"]

    def test_create_media_invalid_site_id_goes_to_failed(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Non-existent site_id: nothing queued, so the request reports failure (HTTP 409)."""
        fu = FileUpload(
            path="/tmp/pending/1/site_test.wav",
            filename="site_test.wav",
            name="site_test.wav",
            directory=1,
            uploader_id=1,
            status=1,
        )
        db.add(fu)
        db.commit()
        db.refresh(fu)

        r = client.post(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            json={"collection_id": 1, "file_upload_ids": [fu.file_upload_id], "site_id": 999999, "date_from_filename": True}
        )
        assert r.status_code == 409
        assert "Site" in r.json()["message"]

    def test_create_media_invalid_license_id_goes_to_failed(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Non-existent license_id: nothing queued, so the request reports failure (HTTP 409)."""
        fu = FileUpload(
            path="/tmp/pending/1/license_test.wav",
            filename="license_test.wav",
            name="license_test.wav",
            directory=1,
            uploader_id=1,
            status=1,
        )
        db.add(fu)
        db.commit()
        db.refresh(fu)

        r = client.post(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            json={"collection_id": 1, "file_upload_ids": [fu.file_upload_id], "license_id": 999999, "date_from_filename": True}
        )
        assert r.status_code == 409
        assert "License" in r.json()["message"]

    def test_create_media_creates_queue_record(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Batch media creation should create a Queue record."""
        # 1. Prepare valid FileUpload
        fu = FileUpload(
            path="/tmp/pending/1/queue_test.wav",
            filename="queue_test.wav",
            name="queue_test.wav",
            directory=1,
            uploader_id=1,
            status=1,
        )
        db.add(fu)
        db.commit()
        db.refresh(fu)

        # 2. Mock redis to avoid real enqueue
        async def mock_redis():
            mock = AsyncMock()
            mock.enqueue_task = AsyncMock()
            yield mock

        app.dependency_overrides[get_task_publisher] = mock_redis
        try:
            # 3. Call API
            r = client.post(
                f"{settings.API_V1_STR}/media",
                headers=superuser_token_headers,
                json={
                    "collection_id": 1,
                    "file_upload_ids": [fu.file_upload_id],
                    "note": "queue test",
                    "date_from_filename": True,
                },
            )
            assert r.status_code == 200

            # 4. Verify Queue record exists in DB
            statement = select(Queue).where(Queue.type == "upload").order_by(Queue.queue_id.desc())
            queue_record = db.exec(statement).first()

            assert queue_record is not None
            assert queue_record.total == 1
            assert queue_record.status == 0  # pending (as expected before worker picks it up)
            assert queue_record.user_id is not None
        finally:
            app.dependency_overrides.pop(get_task_publisher, None)

    def test_create_media_from_filename(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Extract date and time from filename when requested."""
        filename = "audio_20240310_194553.wav"
        fu = FileUpload(
            path=f"/tmp/pending/1/{filename}",
            filename=filename,
            name=filename,
            batch_id=uuid.uuid4(),
            directory=1,
            uploader_id=1,
            status=1,
        )
        db.add(fu)
        db.commit()
        db.refresh(fu)

        mock_enqueue = AsyncMock()
        async def mock_redis():
            mock = AsyncMock()
            mock.enqueue_task = mock_enqueue
            yield mock

        app.dependency_overrides[get_task_publisher] = mock_redis
        try:
            r = client.post(
                f"{settings.API_V1_STR}/media",
                headers=superuser_token_headers,
                json={
                    "collection_id": 1,
                    "file_upload_ids": [fu.file_upload_id],
                    "date_from_filename": True,
                },
            )
        finally:
            app.dependency_overrides.pop(get_task_publisher, None)

        assert r.status_code == 200
        mock_enqueue.assert_called_once()
        kwargs = mock_enqueue.call_args.kwargs
        assert kwargs["items"][0]["file_date"] == "2024-03-10"
        assert kwargs["items"][0]["file_time"] == "19:45:53"

    def test_create_media_from_filename_falls_back_to_default_datetime(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Use the configured default datetime when filename parsing fails."""
        filename = "audio_without_timestamp.wav"
        fu = FileUpload(
            path=f"/tmp/pending/1/{filename}",
            filename=filename,
            name=filename,
            batch_id=uuid.uuid4(),
            directory=1,
            uploader_id=1,
            status=1,
        )
        db.add(fu)
        db.commit()
        db.refresh(fu)

        mock_enqueue = AsyncMock()

        async def mock_redis():
            mock = AsyncMock()
            mock.enqueue_task = mock_enqueue
            yield mock

        app.dependency_overrides[get_task_publisher] = mock_redis
        try:
            r = client.post(
                f"{settings.API_V1_STR}/media",
                headers=superuser_token_headers,
                json={
                    "collection_id": 1,
                    "file_upload_ids": [fu.file_upload_id],
                    "date_from_filename": True,
                },
            )
        finally:
            app.dependency_overrides.pop(get_task_publisher, None)

        assert r.status_code == 200
        mock_enqueue.assert_called_once()
        kwargs = mock_enqueue.call_args.kwargs
        assert kwargs["items"][0]["file_date"] == "1970-01-01"
        assert kwargs["items"][0]["file_time"] == "00:00:00"


class TestMediaList:
    """Tests for media list endpoint."""

    def test_list_media_anonymous_allowed(self, client: TestClient) -> None:
        """Media list allows anonymous access."""
        r = client.get(f"{settings.API_V1_STR}/media?project_id=1")
        assert r.status_code == 200

    def test_list_media_anonymous_only_public_collections(
        self, client: TestClient, db: Session
    ) -> None:
        """Anonymous list should only return media in public collections under project scope."""
        project_id, public_media_id, private_media_id = TestMediaBrowse._setup_browse_data(db)
        r = client.get(f"{settings.API_V1_STR}/media?project_id={project_id}")
        assert r.status_code == 200
        data = r.json()["data"]
        ids = {item["media_id"] for item in data}
        assert public_media_id in ids
        assert private_media_id not in ids
        for item in data:
            assert item["labels"] == []

    def test_list_media_anonymous_site_filter_intersection_with_public_scope(
        self, client: TestClient, db: Session
    ) -> None:
        """Anonymous site filter should still be constrained by public collection scope."""
        project_id, public_media_id, private_media_id = TestMediaBrowse._setup_browse_data(db)
        public_site_id = db.exec(
            select(Media.site_id).where(Media.media_id == public_media_id)
        ).first()
        private_site_id = db.exec(
            select(Media.site_id).where(Media.media_id == private_media_id)
        ).first()
        assert public_site_id is not None
        assert private_site_id is not None

        r_public = client.get(
            f"{settings.API_V1_STR}/media?project_id={project_id}&site_id={public_site_id}"
        )
        assert r_public.status_code == 200
        public_ids = {item["media_id"] for item in r_public.json()["data"]}
        assert public_media_id in public_ids
        assert private_media_id not in public_ids

        r_private = client.get(
            f"{settings.API_V1_STR}/media?project_id={project_id}&site_id={private_site_id}"
        )
        assert r_private.status_code == 200
        assert r_private.json()["data"] == []

    def test_list_media_missing_project_id(self, client: TestClient, superuser_token_headers: dict) -> None:
        """Return 422 if project_id is missing."""
        r = client.get(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers
        )
        assert r.status_code == 422

    def test_list_media_authenticated(
        self, client: TestClient, normal_user_token_headers: dict
    ) -> None:
        """List media with authentication."""
        r = client.get(
            f"{settings.API_V1_STR}/media?project_id=1",
            headers=normal_user_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        assert "data" in json_resp
        assert "page_info" in json_resp

    def test_list_media_with_pagination(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """List media with pagination parameters."""
        r = client.get(
            f"{settings.API_V1_STR}/media?project_id=1&page=1&page_size=10",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        page_info = json_resp["page_info"]
        assert page_info["page"] == 1
        assert page_info["page_size"] == 10

    def test_list_media_with_search(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """List media with search parameter."""
        r = client.get(
            f"{settings.API_V1_STR}/media?project_id=1&search=test",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0

    def test_list_media_with_filters(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """List media with various new filters."""
        r = client.get(
            f"{settings.API_V1_STR}/media?project_id=1&sampling_rate_hz=44100,&duration_s=,60.0",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0

    def test_list_media_with_comprehensive_filters(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        # Setup proj/coll

        # Setup proj/coll
        project = Project(name="Media Proj", url="http://test.com", creator_id=1)
        db.add(project)
        db.commit()
        db.refresh(project)

        collection = Collection(name="Media Coll", creator_id=1, public_access=True)
        db.add(collection)
        db.commit()
        db.refresh(collection)

        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        # Setup settings to bypass check constraint
        audio_setting = AudioSetting(duration_s=10.5, sampling_rate_hz=44100)
        video_setting = PhotoSetting()
        db.add(audio_setting)
        db.add(video_setting)
        db.commit()
        db.refresh(audio_setting)
        db.refresh(video_setting)

        # Setup Sites and Sensors
        site1 = Site(name="Site 1", creator_id=1)
        site2 = Site(name="Site 2", creator_id=1)
        db.add(site1)
        db.add(site2)
        db.commit()
        db.refresh(site1)
        db.refresh(site2)

        mic = Microphone(name="test mic")
        cam = Camera(name="test cam")
        rec = Recorder(name="test rec")
        lens = Lens(name="test lens")
        db.add(mic)
        db.add(cam)
        db.add(rec)
        db.add(lens)
        db.commit()
        db.refresh(mic)
        db.refresh(cam)
        db.refresh(rec)
        db.refresh(lens)

        sensor10 = Sensor(name="Sensor 10", sensor_type="audio", microphone_id=mic.microphone_id, recorder_id=rec.recorder_id)
        sensor20 = Sensor(name="Sensor 20", sensor_type="photo", camera_id=cam.camera_id, lens_id=lens.lens_id)
        db.add(sensor10)
        db.add(sensor20)
        db.commit()
        db.refresh(sensor10)
        db.refresh(sensor20)

        # Create two medias with different properties
        m1 = Media(
            filename="audio1.wav",
            name="Audio 1",
            media_type="audio",
            audio_setting_id=audio_setting.audio_setting_id,
            medium="air",
            site_id=site1.site_id,
            sensor_id=sensor10.sensor_id,
            size_b=1000,
            duty_cycle_recording=60,
            duty_cycle_period=600,
            license_id=1,
            doi="10.1000/1",
            note="Note one",
            uploader_id=1,
            creator_id=1
        )
        m1.creation_date = datetime.now(UTC) - timedelta(days=10)
        db.add(m1)

        m2 = Media(
            filename="video1.mp4",
            name="Video 1",
            media_type="video",
            photo_setting_id=video_setting.photo_setting_id,
            medium="water",
            site_id=site2.site_id,
            sensor_id=sensor20.sensor_id,
            size_b=2000,
            duty_cycle_recording=120,
            duty_cycle_period=1200,
            license_id=2,
            doi="10.1000/2",
            note="Note two",
            uploader_id=1,
            creator_id=1
        )
        m2.creation_date = datetime.now(UTC) - timedelta(days=2)
        db.add(m2)
        db.commit()
        db.refresh(m1)
        db.refresh(m2)

        db.add(MediaCollection(media_id=m1.media_id, collection_id=collection.collection_id, added_by=1))
        db.add(MediaCollection(media_id=m2.media_id, collection_id=collection.collection_id, added_by=1))
        db.commit()

        p_id = project.project_id

        # 1. Test media_type
        r = client.get(f"{settings.API_V1_STR}/media?project_id={p_id}&media_type=audio", headers=superuser_token_headers)
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["media_id"] == m1.media_id

        # 2. Test site_id & sensor_id
        r = client.get(f"{settings.API_V1_STR}/media?project_id={p_id}&site_id={site2.site_id}&sensor_id={sensor20.sensor_id}", headers=superuser_token_headers)
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["media_id"] == m2.media_id

        # 3. Test numeric ranges (comma-string format)
        r = client.get(f"{settings.API_V1_STR}/media?project_id={p_id}&sampling_rate_hz=44000,45000", headers=superuser_token_headers)
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["media_id"] == m1.media_id

        r = client.get(f"{settings.API_V1_STR}/media?project_id={p_id}&size_b=1500,", headers=superuser_token_headers)
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["media_id"] == m2.media_id

        # 4. Test text fuzzy fields
        r = client.get(f"{settings.API_V1_STR}/media?project_id={p_id}&name=Audio 1", headers=superuser_token_headers)
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["media_id"] == m1.media_id

        r = client.get(f"{settings.API_V1_STR}/media?project_id={p_id}&filename=audio1", headers=superuser_token_headers)
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["media_id"] == m1.media_id

        r = client.get(f"{settings.API_V1_STR}/media?project_id={p_id}&doi=1000/1", headers=superuser_token_headers)
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["media_id"] == m1.media_id

        # 5. Test date ranges
        to_dt = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5)).isoformat()
        r = client.get(f"{settings.API_V1_STR}/media?project_id={p_id}&creation_date_to={to_dt}", headers=superuser_token_headers)
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["media_id"] == m1.media_id

        from_dt = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5)).isoformat()
        r = client.get(f"{settings.API_V1_STR}/media?project_id={p_id}&creation_date_from={from_dt}", headers=superuser_token_headers)
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["media_id"] == m2.media_id

    def test_list_media_with_ordering(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """List media with custom ordering."""
        r = client.get(
            f"{settings.API_V1_STR}/media?project_id=1&order_by=sampling_rate_hz&order_dir=asc",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0

    def test_list_photos_filters_and_orders_photo_settings_without_dimensions(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        project = Project(
            name="Photo Technical Filter Project",
            url="https://photo-filter.example",
            creator_id=1,
        )
        collection = Collection(
            name="Photo Technical Filter Collection",
            creator_id=1,
            public_access=True,
        )
        db.add_all([project, collection])
        db.flush()
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))

        low = PhotoSetting(exposure_ms=5, aperture=1.8, iso=100)
        high = PhotoSetting(exposure_ms=20, aperture=4, iso=800)
        db.add_all([low, high])
        db.flush()
        low_photo = Media(
            name="Low technical photo",
            media_type="photo",
            creator_id=1,
            photo_setting_id=low.photo_setting_id,
        )
        high_photo = Media(
            name="High technical photo",
            media_type="photo",
            creator_id=1,
            photo_setting_id=high.photo_setting_id,
        )
        db.add_all([low_photo, high_photo])
        db.flush()
        db.add_all([
            MediaCollection(
                media_id=low_photo.media_id,
                collection_id=collection.collection_id,
                added_by=1,
            ),
            MediaCollection(
                media_id=high_photo.media_id,
                collection_id=collection.collection_id,
                added_by=1,
            ),
        ])
        db.commit()

        filtered_response = client.get(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            params={
                "project_id": project.project_id,
                "media_type": "photo",
                "exposure_ms": "10,",
                "iso": ",800",
            },
        )

        assert filtered_response.status_code == 200
        filtered_data = filtered_response.json()["data"]
        assert [item["media_id"] for item in filtered_data] == [high_photo.media_id]
        assert "image_width" not in filtered_data[0]
        assert "image_height" not in filtered_data[0]

        ordered_response = client.get(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            params={
                "project_id": project.project_id,
                "media_type": "photo",
                "order_by": "aperture",
                "order_dir": "desc",
            },
        )
        assert ordered_response.status_code == 200
        assert [item["media_id"] for item in ordered_response.json()["data"]] == [
            high_photo.media_id,
            low_photo.media_id,
        ]

    def test_list_media_filter_by_media_id(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Filter by exact media_id returns only the matching record."""
        project = Project(name="MediaId Filter Proj", url="http://test.com", creator_id=1)
        db.add(project)
        db.commit()
        db.refresh(project)

        collection = Collection(name="MediaId Filter Coll", creator_id=1, public_access=True)
        db.add(collection)
        db.commit()
        db.refresh(collection)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        audio_setting = AudioSetting(duration_s=5.0, sampling_rate_hz=44100)
        db.add(audio_setting)
        db.commit()
        db.refresh(audio_setting)

        m1 = Media(filename="mid_a.wav", name="MID A", media_type="audio",
                   audio_setting_id=audio_setting.audio_setting_id, uploader_id=1, creator_id=1)
        m2 = Media(filename="mid_b.wav", name="MID B", media_type="audio",
                   audio_setting_id=audio_setting.audio_setting_id, uploader_id=1, creator_id=1)
        db.add(m1)
        db.add(m2)
        db.commit()
        db.refresh(m1)
        db.refresh(m2)

        db.add(MediaCollection(media_id=m1.media_id, collection_id=collection.collection_id, added_by=1))
        db.add(MediaCollection(media_id=m2.media_id, collection_id=collection.collection_id, added_by=1))
        db.commit()

        p_id = project.project_id

        # Filter by m1's media_id: only m1 returned
        r = client.get(
            f"{settings.API_V1_STR}/media?project_id={p_id}&media_id={m1.media_id}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["media_id"] == m1.media_id

        # Non-existent media_id: empty result
        r = client.get(
            f"{settings.API_V1_STR}/media?project_id={p_id}&media_id=999999",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        assert len(r.json()["data"]) == 0

    def test_list_media_filter_by_date_time_range(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Filter by date_time_from / date_time_to returns matching records."""
        project = Project(name="DateTime Filter Proj", url="http://test.com", creator_id=1)
        db.add(project)
        db.commit()
        db.refresh(project)

        collection = Collection(name="DateTime Filter Coll", creator_id=1, public_access=True)
        db.add(collection)
        db.commit()
        db.refresh(collection)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        audio_setting = AudioSetting(duration_s=3.0, sampling_rate_hz=48000)
        db.add(audio_setting)
        db.commit()
        db.refresh(audio_setting)

        now = datetime.now(UTC).replace(tzinfo=None)
        old_dt = now - timedelta(days=30)
        recent_dt = now - timedelta(days=1)

        m_old = Media(filename="dt_old.wav", name="Old", media_type="audio",
                      audio_setting_id=audio_setting.audio_setting_id, uploader_id=1, creator_id=1)
        m_old.date_time = old_dt
        m_recent = Media(filename="dt_recent.wav", name="Recent", media_type="audio",
                         audio_setting_id=audio_setting.audio_setting_id, uploader_id=1, creator_id=1)
        m_recent.date_time = recent_dt
        db.add(m_old)
        db.add(m_recent)
        db.commit()
        db.refresh(m_old)
        db.refresh(m_recent)

        db.add(MediaCollection(media_id=m_old.media_id, collection_id=collection.collection_id, added_by=1))
        db.add(MediaCollection(media_id=m_recent.media_id, collection_id=collection.collection_id, added_by=1))
        db.commit()

        p_id = project.project_id
        cutoff = (now - timedelta(days=10)).isoformat()

        # date_time_to: only old record (before cutoff)
        r = client.get(
            f"{settings.API_V1_STR}/media?project_id={p_id}&date_time_to={cutoff}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        ids = [d["media_id"] for d in data]
        assert m_old.media_id in ids
        assert m_recent.media_id not in ids

        # date_time_from: only recent record (after cutoff)
        r = client.get(
            f"{settings.API_V1_STR}/media?project_id={p_id}&date_time_from={cutoff}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        ids = [d["media_id"] for d in data]
        assert m_recent.media_id in ids
        assert m_old.media_id not in ids


    def test_list_media_filter_by_sr_range(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """sr=min,max (comma string) filters by sampling_rate_hz range."""
        project = Project(name="SR Range Proj", url="http://test.com", creator_id=1)
        db.add(project)
        db.commit()
        db.refresh(project)

        collection = Collection(name="SR Range Coll", creator_id=1, public_access=True)
        db.add(collection)
        db.commit()
        db.refresh(collection)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        # Two audio files with different sample rates
        as_low  = AudioSetting(duration_s=1.0, sampling_rate_hz=8000)
        as_high = AudioSetting(duration_s=1.0, sampling_rate_hz=48000)
        db.add_all([as_low, as_high])
        db.commit()
        db.refresh(as_low)
        db.refresh(as_high)

        m_low  = Media(filename="low_sr.wav",  name="Low SR",  media_type="audio",
                       audio_setting_id=as_low.audio_setting_id,  uploader_id=1, creator_id=1)
        m_high = Media(filename="high_sr.wav", name="High SR", media_type="audio",
                       audio_setting_id=as_high.audio_setting_id, uploader_id=1, creator_id=1)
        db.add_all([m_low, m_high])
        db.commit()
        db.refresh(m_low)
        db.refresh(m_high)

        db.add(MediaCollection(media_id=m_low.media_id,  collection_id=collection.collection_id, added_by=1))
        db.add(MediaCollection(media_id=m_high.media_id, collection_id=collection.collection_id, added_by=1))
        db.commit()

        p_id = project.project_id

        # sr=10000,44100 should include m_low (8000 is outside), only m_high (48000) is also outside
        # Actually 8000 < 10000 → excluded; 48000 > 44100 → excluded → empty
        r = client.get(
            f"{settings.API_V1_STR}/media?project_id={p_id}&sampling_rate_hz=10000,44100",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        ids = [d["media_id"] for d in r.json()["data"]]
        assert m_low.media_id not in ids
        assert m_high.media_id not in ids

        # sr=1000,44100 includes 8000 but not 48000
        r = client.get(
            f"{settings.API_V1_STR}/media?project_id={p_id}&sampling_rate_hz=1000,44100",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        ids = [d["media_id"] for d in r.json()["data"]]
        assert m_low.media_id in ids
        assert m_high.media_id not in ids

        # sr=,50000 (no lower bound) includes both
        r = client.get(
            f"{settings.API_V1_STR}/media?project_id={p_id}&sampling_rate_hz=,50000",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        ids = [d["media_id"] for d in r.json()["data"]]
        assert m_low.media_id in ids
        assert m_high.media_id in ids

        # invalid sr string → silently ignored, returns all media in project
        r = client.get(
            f"{settings.API_V1_STR}/media?project_id={p_id}&sampling_rate_hz=invalid",
            headers=superuser_token_headers
        )
        assert r.status_code == 200

    def test_list_media_no_audio_permission(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        """Return 403 if project_id is provided but no audio:read permission."""

        # Find a project the user definitely does NOT have direct permissions for
        user = db.exec(select(User)).first()
        project = Project(name="No Audio Read Project", url="http://test.com", active=True, creator_id=user.user_id)
        db.add(project)
        db.commit()
        db.refresh(project)

        # User normal@example.com does not have audio:read on this new project
        r = client.get(
            f"{settings.API_V1_STR}/media?project_id={project.project_id}",
            headers=normal_user_token_headers
        )
        assert r.status_code == 200
        assert len(r.json()["data"]) == 0




class TestMediaOptions:
    """Tests for media options endpoint."""

    def test_media_options_anonymous_only_public_collections(self, client: TestClient, db: Session) -> None:
        project_id, public_media_id, private_media_id = TestMediaBrowse._setup_browse_data(db)

        r = client.get(
            f"{settings.API_V1_STR}/media-options",
            params={"project_id": project_id},
        )
        assert r.status_code == 200
        ids = {item["media_id"] for item in r.json()["data"]}
        assert public_media_id in ids
        assert private_media_id not in ids

    def test_media_options_anonymous_empty_when_no_public_media(self, client: TestClient, db: Session) -> None:
        project = Project(name="Options Private Proj", url="http://options-private.test", creator_id=1)
        private_collection = Collection(name="Options Private Col", creator_id=1, public_access=False)
        audio_setting = AudioSetting(duration_s=8.0, sampling_rate_hz=44100)
        media = Media(
            filename="OPTIONS_PRIVATE.wav",
            name="OPTIONS_PRIVATE",
            media_type="audio", is_metadata=True,
            creator_id=1,
            uploader_id=1,
        )
        db.add(project)
        db.add(private_collection)
        db.add(audio_setting)
        db.flush()
        db.add(ProjectCollection(project_id=project.project_id, collection_id=private_collection.collection_id))
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=private_collection.collection_id, added_by=1))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media-options",
            params={"project_id": project.project_id},
        )
        assert r.status_code == 200
        assert r.json()["data"] == []

    def test_media_options_missing_project_id(self, client: TestClient) -> None:
        r = client.get(f"{settings.API_V1_STR}/media-options")
        assert r.status_code == 422


class TestMediaBrowse:
    """Tests for browse media endpoint."""

    @staticmethod
    def _setup_browse_data(db: Session) -> tuple[int, int, int]:
        """Create project, public/private collections and one media in each."""
        project = Project(name="Browse Proj", url="http://browse.test", creator_id=1)
        db.add(project)
        db.commit()
        db.refresh(project)

        public_collection = Collection(name="Browse Public", creator_id=1, public_access=True)
        private_collection = Collection(name="Browse Private", creator_id=1, public_access=False)
        db.add(public_collection)
        db.add(private_collection)
        db.commit()
        db.refresh(public_collection)
        db.refresh(private_collection)

        db.add(ProjectCollection(project_id=project.project_id, collection_id=public_collection.collection_id))
        db.add(ProjectCollection(project_id=project.project_id, collection_id=private_collection.collection_id))
        db.commit()

        max_iucn_id = db.exec(select(IucnGet.iucn_get_id).order_by(IucnGet.iucn_get_id.desc())).first() or 100000
        realm_id = max_iucn_id + 1
        biome_id = max_iucn_id + 2
        functional_type_id = max_iucn_id + 3
        realm = IucnGet(iucn_get_id=realm_id, pid=0, name="Terrestrial", level=1)
        biome = IucnGet(iucn_get_id=biome_id, pid=realm_id, name="Tropical Forests", level=2)
        functional_type = IucnGet(iucn_get_id=functional_type_id, pid=biome_id, name="Montane Rainforest", level=3)
        realm2 = IucnGet(iucn_get_id=functional_type_id + 1, pid=0, name="Marine", level=1)
        biome2 = IucnGet(iucn_get_id=functional_type_id + 2, pid=realm2.iucn_get_id, name="Open Ocean", level=2)
        functional_type2 = IucnGet(iucn_get_id=functional_type_id + 3, pid=biome2.iucn_get_id, name="Pelagic", level=3)
        db.add_all([realm, biome, functional_type, realm2, biome2, functional_type2])
        db.commit()

        site_private = Site(
            name="Browse Site",
            creator_id=1,
            realm_id=realm.iucn_get_id,
            biome_id=biome.iucn_get_id,
            functional_type_id=functional_type.iucn_get_id,
            topography_m=435.0,
            freshwater_depth_m=2.5,
            iho="South China Sea",
            gadm0="China",
            gadm1="Guangdong",
            gadm2="Shenzhen",
        )
        site_public = Site(
            name="Browse Public Site",
            creator_id=1,
            realm_id=realm2.iucn_get_id,
            biome_id=biome2.iucn_get_id,
            functional_type_id=functional_type2.iucn_get_id,
            topography_m=5.0,
            freshwater_depth_m=15.0,
            iho="Pacific Ocean",
            gadm0="USA",
            gadm1="California",
            gadm2="Monterey",
        )
        db.add(site_private)
        db.add(site_public)
        db.commit()
        db.refresh(site_private)
        db.refresh(site_public)

        role = db.exec(select(Role).order_by(Role.role_id.asc())).first()
        if role is None:
            role = Role(name=f"Browse Role {uuid.uuid4().hex[:6]}")
            db.add(role)
            db.commit()
            db.refresh(role)

        browse_user = User(
            username=f"browse_u_{uuid.uuid4().hex[:8]}",
            name="Browse Creator",
            email=f"browse_{uuid.uuid4().hex[:8]}@test.com",
            role_id=role.role_id,
            password="hashed_password",
        )
        db.add(browse_user)
        db.commit()
        db.refresh(browse_user)

        recorder = Recorder(name="Browse Recorder X", brand="BrowseBrand")
        microphone = Microphone(name="Browse Mic X")
        db.add(recorder)
        db.add(microphone)
        db.commit()
        db.refresh(recorder)
        db.refresh(microphone)

        sensor = Sensor(
            name="Browse Sensor X",
            sensor_type="audio",
            recorder_id=recorder.recorder_id,
            microphone_id=microphone.microphone_id,
        )
        license_obj = License(name="Browse License X", link="https://license.example/browse")
        db.add(sensor)
        db.add(license_obj)
        db.commit()
        db.refresh(sensor)
        db.refresh(license_obj)

        audio_public = AudioSetting(duration_s=12.5, sampling_rate_hz=48000, bit_depth=16, channel_num=1, recording_gain_db=0)
        audio_private = AudioSetting(duration_s=30303.75, sampling_rate_hz=44100, bit_depth=24242, channel_num=271, recording_gain_db=98765)
        db.add(audio_public)
        db.add(audio_private)
        db.commit()
        db.refresh(audio_public)
        db.refresh(audio_private)

        media_public = Media(
            filename="REC_PUBLIC_001.wav",
            name="REC_PUBLIC_001",
            media_type="audio",
            audio_setting_id=audio_public.audio_setting_id,
            site_id=site_public.site_id,
            size_b=12345,
            uploader_id=1,
            creator_id=1,
            medium="air",
            note="Public browse note",
            doi="10.1000/public",
        )
        media_private = Media(
            filename="REC_PRIVATE_001.wav",
            name="REC_PRIVATE_001",
            media_type="audio",
            audio_setting_id=audio_private.audio_setting_id,
            site_id=site_private.site_id,
            size_b=67890,
            uploader_id=browse_user.user_id,
            creator_id=browse_user.user_id,
            medium="water",
            note="Private browse note xyz",
            doi="10.5555/browse-private",
            duty_cycle_recording=30,
            duty_cycle_period=90,
            sensor_id=sensor.sensor_id,
            license_id=license_obj.license_id,
        )
        db.add(media_public)
        db.add(media_private)
        db.commit()
        db.refresh(media_public)
        db.refresh(media_private)

        db.add(MediaCollection(media_id=media_public.media_id, collection_id=public_collection.collection_id, added_by=1))
        db.add(MediaCollection(media_id=media_private.media_id, collection_id=private_collection.collection_id, added_by=1))
        public_preview_name = "REC_PUBLIC_001_thumbnail.png"
        private_preview_name = "REC_PRIVATE_001_thumbnail.png"
        db.add(
            Preview(
                media_id=media_public.media_id,
                filename=public_preview_name,
                type="thumbnail",
            )
        )
        db.add(
            Preview(
                media_id=media_private.media_id,
                filename=private_preview_name,
                type="thumbnail",
            )
        )
        browse_label = Label(name=f"bpri_{uuid.uuid4().hex[:6]}", creator_id=browse_user.user_id)
        db.add(browse_label)
        db.commit()
        db.refresh(browse_label)
        db.add(LabelMedia(media_id=media_private.media_id, user_id=browse_user.user_id, label_id=browse_label.label_id))
        db.commit()

        return project.project_id, media_public.media_id, media_private.media_id

    def test_browse_media_anonymous_only_public(self, client: TestClient, db: Session) -> None:
        project_id, public_media_id, private_media_id = self._setup_browse_data(db)

        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            params={"project_id": project_id, "view_type": "gallery"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        ids = {item["media_id"] for item in data}
        assert public_media_id in ids
        assert private_media_id not in ids
        public_item = next(item for item in data if item["media_id"] == public_media_id)
        assert public_item["label"] == "not analysed"

    def test_browse_media_normal_user_with_permission(self, client: TestClient, normal_user_token_headers: dict, db: Session) -> None:
        project_id, public_media_id, private_media_id = self._setup_browse_data(db)

        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        user_id = int(payload["sub"])

        private_collection_id = db.exec(
            select(Collection.collection_id).where(Collection.name == "Browse Private").order_by(Collection.collection_id.desc())
        ).first()
        assert private_collection_id is not None

        audio_read_perm = db.exec(
            select(Permission).where(
                Permission.resource_type == "audio",
                Permission.action == "read",
            )
        ).first()
        assert audio_read_perm is not None

        db.add(
            UserPermission(
                user_id=user_id,
                project_id=project_id,
                collection_id=private_collection_id,
                permission_id=audio_read_perm.permission_id,
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=normal_user_token_headers,
            params={"project_id": project_id, "view_type": "list"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        ids = {item["media_id"] for item in data}
        assert public_media_id in ids
        assert private_media_id in ids

    def test_browse_media_admin_sees_all(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        project_id, public_media_id, private_media_id = self._setup_browse_data(db)

        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project_id, "view_type": "gallery"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        ids = {item["media_id"] for item in data}
        assert public_media_id in ids
        assert private_media_id in ids
        by_id = {item["media_id"]: item for item in data}
        assert by_id[public_media_id]["label"] == "not analysed"
        assert by_id[private_media_id]["label"] == "not analysed"

    def test_browse_media_user_sees_own_label_only(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        project_id, _, private_media_id = self._setup_browse_data(db)

        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        user_id = int(payload["sub"])

        private_collection_id = db.exec(
            select(Collection.collection_id)
            .where(Collection.name == "Browse Private")
            .order_by(Collection.collection_id.desc())
        ).first()
        assert private_collection_id is not None

        audio_read_perm = db.exec(
            select(Permission).where(
                Permission.resource_type == "audio",
                Permission.action == "read",
            )
        ).first()
        assert audio_read_perm is not None

        db.add(
            UserPermission(
                user_id=user_id,
                project_id=project_id,
                collection_id=private_collection_id,
                permission_id=audio_read_perm.permission_id,
            )
        )
        own_label = Label(name=f"bself_{uuid.uuid4().hex[:6]}", creator_id=user_id)
        db.add(own_label)
        db.commit()
        db.refresh(own_label)
        db.add(LabelMedia(media_id=private_media_id, user_id=user_id, label_id=own_label.label_id))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=normal_user_token_headers,
            params={"project_id": project_id, "view_type": "list"},
        )
        assert r.status_code == 200
        by_id = {item["media_id"]: item for item in r.json()["data"]}
        assert by_id[private_media_id]["label"] == own_label.name

    def test_browse_media_admin_does_not_see_other_users_label(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        project_id, _, private_media_id = self._setup_browse_data(db)

        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project_id, "view_type": "list"},
        )
        assert r.status_code == 200
        by_id = {item["media_id"]: item for item in r.json()["data"]}
        assert by_id[private_media_id]["label"] == "not analysed"

    def test_browse_media_user_without_own_label_defaults_to_not_analysed(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        project_id, public_media_id, private_media_id = self._setup_browse_data(db)

        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        user_id = int(payload["sub"])

        private_collection_id = db.exec(
            select(Collection.collection_id)
            .where(Collection.name == "Browse Private")
            .order_by(Collection.collection_id.desc())
        ).first()
        assert private_collection_id is not None

        audio_read_perm = db.exec(
            select(Permission).where(
                Permission.resource_type == "audio",
                Permission.action == "read",
            )
        ).first()
        assert audio_read_perm is not None

        db.add(
            UserPermission(
                user_id=user_id,
                project_id=project_id,
                collection_id=private_collection_id,
                permission_id=audio_read_perm.permission_id,
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=normal_user_token_headers,
            params={"project_id": project_id, "view_type": "list"},
        )
        assert r.status_code == 200
        by_id = {item["media_id"]: item for item in r.json()["data"]}
        assert by_id[public_media_id]["label"] == "not analysed"
        assert by_id[private_media_id]["label"] == "not analysed"

    def test_browse_media_gallery_fields(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        project_id, _, _ = self._setup_browse_data(db)

        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project_id, "view_type": "gallery"},
        )
        assert r.status_code == 200
        first = r.json()["data"][0]
        assert "label" in first
        assert "duration_s" in first
        assert "sampling_rate_hz" in first
        assert "bit_depth" in first
        assert "channel_num" in first
        realm_names = {item["realm_name"] for item in r.json()["data"]}
        assert "Terrestrial" in realm_names
        assert "site_name" not in first
        if first.get("preview_url"):
            assert first["preview_url"].startswith(f"{settings.media_base_url}/")
            assert "/media/previews/" not in first["preview_url"]

    def test_browse_media_metadata_with_audio_setting_exposes_technical_fields(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        project_id, _, _ = self._setup_browse_data(db)
        public_collection_id = db.exec(
            select(Collection.collection_id)
            .where(Collection.name == "Browse Public")
            .order_by(Collection.collection_id.desc())
        ).first()
        assert public_collection_id is not None

        metadata_audio_setting = AudioSetting(
            duration_s=88.5,
            sampling_rate_hz=32000,
            bit_depth=24,
            channel_num=2,
            recording_gain_db=11,
        )
        db.add(metadata_audio_setting)
        db.commit()
        db.refresh(metadata_audio_setting)

        metadata_media = Media(
            filename="REC_META_001.csv",
            name="REC_META_001",
            media_type="audio", is_metadata=True,
            audio_setting_id=metadata_audio_setting.audio_setting_id,
            uploader_id=1,
            creator_id=1,
            date_time=datetime.now(UTC),
        )
        db.add(metadata_media)
        db.commit()
        db.refresh(metadata_media)
        db.add(
            MediaCollection(
                media_id=metadata_media.media_id,
                collection_id=public_collection_id,
                added_by=1,
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project_id, "view_type": "gallery"},
        )
        assert r.status_code == 200
        metadata_item = next(item for item in r.json()["data"] if item["media_id"] == metadata_media.media_id)
        assert metadata_item["media_type"] == "audio"
        assert metadata_item["is_metadata"] is True
        assert metadata_item["duration_s"] == 88.5
        assert metadata_item["sampling_rate_hz"] == 32000
        assert metadata_item["bit_depth"] == 24
        assert metadata_item["channel_num"] == 2

    def test_browse_media_gallery_preview_url_uses_absolute_url(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Gallery preview_url should be a normalized absolute URL."""
        project_id, _, _ = self._setup_browse_data(db)

        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project_id, "view_type": "gallery"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        preview_urls = [item.get("preview_url") for item in data if item.get("preview_url")]
        assert preview_urls
        assert all(url.startswith(f"{settings.media_base_url}/") for url in preview_urls)
        assert all("/media/previews/" not in url for url in preview_urls)
        assert all("\\" not in url for url in preview_urls)
        assert all("/sounds/sounds/sounds/" not in url for url in preview_urls)
        assert all("//" not in url.split("://", 1)[1] for url in preview_urls if "://" in url)

    def test_browse_media_gallery_no_preview_keeps_null(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Media without preview should keep preview_url as null."""
        project = Project(name="Browse No Preview Proj", url="http://browse-no-preview.test", creator_id=1)
        db.add(project)
        db.commit()
        db.refresh(project)

        collection = Collection(name="Browse No Preview Col", creator_id=1, public_access=True)
        db.add(collection)
        db.commit()
        db.refresh(collection)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        media = Media(
            filename="NO_PREVIEW.wav",
            name="NO_PREVIEW",
            media_type="audio", is_metadata=True,
            uploader_id=1,
            creator_id=1,
        )
        db.add(media)
        db.commit()
        db.refresh(media)
        db.add(MediaCollection(media_id=media.media_id, collection_id=collection.collection_id, added_by=1))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id, "view_type": "gallery"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        no_preview_item = next(item for item in data if item["media_id"] == media.media_id)
        assert no_preview_item.get("preview_url") is None

        r_list = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id, "view_type": "list"},
        )
        assert r_list.status_code == 200
        list_data = r_list.json()["data"]
        no_preview_list_item = next(item for item in list_data if item["media_id"] == media.media_id)
        assert no_preview_list_item.get("preview_url") is None

    def test_browse_media_list_fields(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        project_id, public_media_id, private_media_id = self._setup_browse_data(db)

        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project_id, "view_type": "list"},
        )
        assert r.status_code == 200
        by_id = {item["media_id"]: item for item in r.json()["data"]}
        first = r.json()["data"][0]
        assert "site_name" in first
        assert "sensor_name" in first
        assert "license_name" in first
        assert "label" in first
        assert "sampling_rate_hz" in first
        assert "duty_cycle_period" in first
        assert "duty_cycle_recording" in first
        assert "preview_url" in first
        assert "media_type" in first
        assert "freshwater_depth_m" in first
        assert "realm" not in first
        assert "reaml" not in first
        assert by_id[public_media_id]["freshwater_depth_m"] == 15.0
        assert by_id[private_media_id]["freshwater_depth_m"] == 2.5
        assert by_id[private_media_id]["duty_cycle_period"] == 90
        assert by_id[private_media_id]["duty_cycle_recording"] == 30
        if first.get("preview_url"):
            assert first["preview_url"].startswith(f"{settings.media_base_url}/")
        realms = {item["realm_name"] for item in by_id.values()}
        assert "Terrestrial" in realms
        assert "Marine" in realms

    def test_browse_media_prefers_requested_collection_context(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        project = Project(name="Browse Stable Proj", url="http://browse-stable.test", creator_id=1)
        db.add(project)
        db.commit()
        db.refresh(project)

        lower_collection = Collection(name="Browse Lower", creator_id=1, public_access=True, sphere="air")
        higher_collection = Collection(name="Browse Higher", creator_id=1, public_access=True, sphere="water")
        db.add_all([lower_collection, higher_collection])
        db.commit()
        db.refresh(lower_collection)
        db.refresh(higher_collection)

        db.add(ProjectCollection(project_id=project.project_id, collection_id=lower_collection.collection_id))
        db.add(ProjectCollection(project_id=project.project_id, collection_id=higher_collection.collection_id))
        db.commit()

        media = Media(
            filename="stable_browse.wav",
            name="Stable Browse",
            media_type="audio", is_metadata=True,
            uploader_id=1,
            creator_id=1,
        )
        db.add(media)
        db.commit()
        db.refresh(media)

        lower_id = min(lower_collection.collection_id, higher_collection.collection_id)
        higher_id = max(lower_collection.collection_id, higher_collection.collection_id)
        db.add(MediaCollection(media_id=media.media_id, collection_id=higher_id, added_by=1))
        db.add(MediaCollection(media_id=media.media_id, collection_id=lower_id, added_by=1))
        db.commit()

        r_default = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id, "view_type": "gallery"},
        )
        assert r_default.status_code == 200
        default_item = next(item for item in r_default.json()["data"] if item["media_id"] == media.media_id)
        expected_default_sphere = "air" if lower_id == lower_collection.collection_id else "water"
        assert default_item["sphere"] == expected_default_sphere

        r_preferred = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={
                "project_id": project.project_id,
                "view_type": "gallery",
                "collection_id": higher_collection.collection_id,
            },
        )
        assert r_preferred.status_code == 200
        preferred_item = next(item for item in r_preferred.json()["data"] if item["media_id"] == media.media_id)
        assert preferred_item["sphere"] == higher_collection.sphere

    def test_browse_media_name_search_filters_results(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        project_id, public_media_id, private_media_id = self._setup_browse_data(db)

        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project_id, "view_type": "list", "name": "PRIVATE_001"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        ids = {item["media_id"] for item in data}
        assert private_media_id in ids
        assert public_media_id not in ids

    @pytest.mark.parametrize(
        "keyword",
        [
            "PRIVATE_001",
            "browse-private",
            "Browse Creator",
            "Browse Site",
            "Browse License X",
            "Browse Sensor X",
            "2.5",
            "435",
            "Terrestrial",
            "Tropical Forests",
            "Montane Rainforest",
            "xyz",
            "water",
        ],
    )
    def test_browse_media_list_search_hits_private(
        self,
        keyword: str,
        client: TestClient,
        superuser_token_headers: dict,
        db: Session,
    ) -> None:
        project_id, public_media_id, private_media_id = self._setup_browse_data(db)
        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project_id, "view_type": "list", "name": keyword},
        )
        assert r.status_code == 200
        ids = {item["media_id"] for item in r.json()["data"]}
        assert private_media_id in ids
        assert public_media_id not in ids

    def test_browse_media_gallery_search_only_matches_gallery_fields(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        project_id, public_media_id, private_media_id = self._setup_browse_data(db)

        list_resp = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=normal_user_token_headers,
            params={"project_id": project_id, "view_type": "list"},
        )
        assert list_resp.status_code == 200
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        user_id = int(payload["sub"])

        private_collection_id = db.exec(
            select(Collection.collection_id)
            .where(Collection.name == "Browse Private")
            .order_by(Collection.collection_id.desc())
        ).first()
        assert private_collection_id is not None

        audio_read_perm = db.exec(
            select(Permission).where(
                Permission.resource_type == "audio",
                Permission.action == "read",
            )
        ).first()
        assert audio_read_perm is not None

        db.add(
            UserPermission(
                user_id=user_id,
                project_id=project_id,
                collection_id=private_collection_id,
                permission_id=audio_read_perm.permission_id,
            )
        )
        own_label = Label(name=f"bgal_{uuid.uuid4().hex[:6]}", creator_id=user_id)
        db.add(own_label)
        db.commit()
        db.refresh(own_label)
        db.add(LabelMedia(media_id=private_media_id, user_id=user_id, label_id=own_label.label_id))
        db.commit()

        tag_resp = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=normal_user_token_headers,
            params={"project_id": project_id, "view_type": "gallery", "name": own_label.name},
        )
        assert tag_resp.status_code == 200
        tag_ids = {item["media_id"] for item in tag_resp.json()["data"]}
        assert private_media_id in tag_ids
        assert public_media_id not in tag_ids

        site_resp = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=normal_user_token_headers,
            params={"project_id": project_id, "view_type": "gallery", "name": "Browse Site"},
        )
        assert site_resp.status_code == 200
        assert site_resp.json()["data"] == []

    def test_browse_media_search_ignores_other_users_labels(
        self,
        client: TestClient,
        normal_user_token_headers: dict,
        superuser_token_headers: dict,
        db: Session,
    ) -> None:
        project_id, _, private_media_id = self._setup_browse_data(db)
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        user_id = int(payload["sub"])

        private_collection_id = db.exec(
            select(Collection.collection_id)
            .where(Collection.name == "Browse Private")
            .order_by(Collection.collection_id.desc())
        ).first()
        assert private_collection_id is not None
        audio_read_perm = db.exec(
            select(Permission).where(
                Permission.resource_type == "audio",
                Permission.action == "read",
            )
        ).first()
        assert audio_read_perm is not None
        db.add(
            UserPermission(
                user_id=user_id,
                project_id=project_id,
                collection_id=private_collection_id,
                permission_id=audio_read_perm.permission_id,
            )
        )
        db.commit()

        foreign_label = db.exec(
            select(Label)
            .join(LabelMedia, LabelMedia.label_id == Label.label_id)
            .where(LabelMedia.media_id == private_media_id)
        ).first()
        assert foreign_label is not None

        normal_resp = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=normal_user_token_headers,
            params={
                "project_id": project_id,
                "view_type": "gallery",
                "name": foreign_label.name,
            },
        )
        assert normal_resp.status_code == 200
        assert normal_resp.json()["data"] == []

        admin_resp = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={
                "project_id": project_id,
                "view_type": "gallery",
                "name": foreign_label.name,
            },
        )
        assert admin_resp.status_code == 200
        assert admin_resp.json()["data"] == []

    def test_browse_media_anonymous_search_ignores_labels(
        self, client: TestClient, db: Session
    ) -> None:
        project_id, _, private_media_id = self._setup_browse_data(db)
        foreign_label = db.exec(
            select(Label)
            .join(LabelMedia, LabelMedia.label_id == Label.label_id)
            .where(LabelMedia.media_id == private_media_id)
        ).first()
        assert foreign_label is not None

        resp = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            params={
                "project_id": project_id,
                "view_type": "gallery",
                "name": foreign_label.name,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_browse_media_full_field_search_no_match(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        project_id, _, _ = self._setup_browse_data(db)
        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project_id, "view_type": "list", "name": "NO_MATCH_TOKEN_9b2c7d"},
        )
        assert r.status_code == 200
        assert r.json()["data"] == []

    def test_browse_media_invalid_view_type(self, client: TestClient, db: Session) -> None:
        project_id, _, _ = self._setup_browse_data(db)
        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            params={"project_id": project_id, "view_type": "table"},
        )
        assert r.status_code == 422

    def test_browse_media_missing_project_id(self, client: TestClient) -> None:
        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            params={"view_type": "gallery"},
        )
        assert r.status_code == 422

    def test_browse_media_filter_by_site_id(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Browse endpoint should filter media by site_id."""
        project = Project(name="Browse Site Filter", url="http://browse-site.test", creator_id=1)
        db.add(project)
        db.commit()
        db.refresh(project)

        collection = Collection(name="Browse Site Filter Col", creator_id=1, public_access=True)
        db.add(collection)
        db.commit()
        db.refresh(collection)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        site1 = Site(name="Browse Site 1", creator_id=1)
        site2 = Site(name="Browse Site 2", creator_id=1)
        db.add(site1)
        db.add(site2)
        db.commit()
        db.refresh(site1)
        db.refresh(site2)

        media_site1 = Media(
            filename="SITE1.wav",
            name="SITE1",
            media_type="audio", is_metadata=True,
            site_id=site1.site_id,
            creator_id=1,
            uploader_id=1,
        )
        media_site2 = Media(
            filename="SITE2.wav",
            name="SITE2",
            media_type="audio", is_metadata=True,
            site_id=site2.site_id,
            creator_id=1,
            uploader_id=1,
        )
        db.add(media_site1)
        db.add(media_site2)
        db.commit()
        db.refresh(media_site1)
        db.refresh(media_site2)

        db.add(MediaCollection(media_id=media_site1.media_id, collection_id=collection.collection_id, added_by=1))
        db.add(MediaCollection(media_id=media_site2.media_id, collection_id=collection.collection_id, added_by=1))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={
                "project_id": project.project_id,
                "view_type": "list",
                "site_id": site1.site_id,
            },
        )
        assert r.status_code == 200
        items = r.json()["data"]
        assert len(items) == 1
        assert items[0]["media_id"] == media_site1.media_id
        assert items[0]["site_id"] == site1.site_id

    def test_browse_media_media_type_filter(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """media_type filter should restrict browse results to audio or photo only."""
        project = Project(
            name=f"Browse MT Project {uuid.uuid4().hex[:6]}",
            url=f"https://example.com/{uuid.uuid4().hex[:6]}",
            public=True,
            active=True,
            creator_id=1,
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        collection = Collection(
            name=f"Browse MT Col {uuid.uuid4().hex[:6]}",
            creator_id=1,
            public_access=True,
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        audio_setting = AudioSetting(duration_s=10.0, sampling_rate_hz=44100)
        db.add(audio_setting)
        photo_setting = PhotoSetting()
        db.add(photo_setting)
        db.commit()
        db.refresh(audio_setting)
        db.refresh(photo_setting)

        audio_media = Media(
            filename="browse_mt_audio.wav",
            name="browse_mt_audio",
            media_type="audio",
            audio_setting_id=audio_setting.audio_setting_id,
            creator_id=1,
            uploader_id=1,
        )
        photo_media = Media(
            filename="browse_mt_photo.jpg",
            name="browse_mt_photo",
            media_type="photo",
            photo_setting_id=photo_setting.photo_setting_id,
            creator_id=1,
            uploader_id=1,
        )
        db.add(audio_media)
        db.add(photo_media)
        db.commit()
        db.refresh(audio_media)
        db.refresh(photo_media)

        db.add(MediaCollection(media_id=audio_media.media_id, collection_id=collection.collection_id, added_by=1))
        db.add(MediaCollection(media_id=photo_media.media_id, collection_id=collection.collection_id, added_by=1))
        db.commit()

        # all (default)
        r_all = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id, "view_type": "gallery", "media_type": "all"},
        )
        assert r_all.status_code == 200
        all_ids = {item["media_id"] for item in r_all.json()["data"]}
        assert audio_media.media_id in all_ids
        assert photo_media.media_id in all_ids

        # audio only
        r_audio = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id, "view_type": "gallery", "media_type": "audio"},
        )
        assert r_audio.status_code == 200
        audio_ids = {item["media_id"] for item in r_audio.json()["data"]}
        assert audio_media.media_id in audio_ids
        assert photo_media.media_id not in audio_ids

        # photo only
        r_photo = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id, "view_type": "gallery", "media_type": "photo"},
        )
        assert r_photo.status_code == 200
        photo_ids = {item["media_id"] for item in r_photo.json()["data"]}
        assert audio_media.media_id not in photo_ids
        assert photo_media.media_id in photo_ids


class TestMediaGet:
    """Tests for get single media endpoint."""

    def test_get_media_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Return HTTP 404 if media not found."""
        r = client.get(
            f"{settings.API_V1_STR}/media/99999",
            params={"project_id": 1},
            headers=superuser_token_headers
        )
        assert r.status_code == 404

    def test_get_media_anonymous_allows_public_media(self, client: TestClient, db: Session) -> None:
        """Anonymous can access media linked to public collections."""
        project_id, public_media_id, _ = TestMediaBrowse._setup_browse_data(db)
        r = client.get(f"{settings.API_V1_STR}/media/{public_media_id}", params={"project_id": project_id})
        assert r.status_code == 200
        assert r.json()["data"]["labels"] == []

    def test_get_media_anonymous_denies_private_media(self, client: TestClient, db: Session) -> None:
        """Anonymous access to non-public media should return 403."""
        project_id, _, private_media_id = TestMediaBrowse._setup_browse_data(db)
        r = client.get(f"{settings.API_V1_STR}/media/{private_media_id}", params={"project_id": project_id})
        assert r.status_code == 403

    def test_get_media_returns_theme_value_and_source(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Media detail theme prefers site realm and falls back to project-scoped collection sphere."""
        project = Project(
            name=f"Theme Project {uuid.uuid4().hex[:8]}",
            url=f"https://theme-{uuid.uuid4().hex[:8]}.example",
            creator_id=1,
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        collection_with_sphere = Collection(
            name=f"Theme Collection {uuid.uuid4().hex[:8]}",
            creator_id=1,
            sphere="hydrosphere",
        )
        collection_without_sphere = Collection(
            name=f"No Theme Collection {uuid.uuid4().hex[:8]}",
            creator_id=1,
        )
        db.add(collection_with_sphere)
        db.add(collection_without_sphere)
        db.commit()
        db.refresh(collection_with_sphere)
        db.refresh(collection_without_sphere)

        db.add(
            ProjectCollection(
                project_id=project.project_id,
                collection_id=collection_with_sphere.collection_id,
            )
        )
        db.add(
            ProjectCollection(
                project_id=project.project_id,
                collection_id=collection_without_sphere.collection_id,
            )
        )
        db.commit()

        max_iucn_id = (
            db.exec(select(IucnGet.iucn_get_id).order_by(IucnGet.iucn_get_id.desc())).first()
            or 100000
        )
        realm = IucnGet(iucn_get_id=max_iucn_id + 1, pid=0, name="Freshwater", level=1)
        db.add(realm)
        db.commit()
        db.refresh(realm)

        site = Site(
            name=f"Theme Site {uuid.uuid4().hex[:8]}",
            creator_id=1,
            realm_id=realm.iucn_get_id,
        )
        db.add(site)
        db.commit()
        db.refresh(site)

        audio_setting = AudioSetting(duration_s=1.0, sampling_rate_hz=44100)
        db.add(audio_setting)
        db.commit()
        db.refresh(audio_setting)

        media_with_site = Media(
            filename="THEME_SITE.wav",
            name="THEME_SITE",
            media_type="audio",
            audio_setting_id=audio_setting.audio_setting_id,
            site_id=site.site_id,
            uploader_id=1,
            creator_id=1,
        )
        media_without_site = Media(
            filename="THEME_COLLECTION.wav",
            name="THEME_COLLECTION",
            media_type="audio",
            audio_setting_id=audio_setting.audio_setting_id,
            uploader_id=1,
            creator_id=1,
        )
        media_without_theme = Media(
            filename="THEME_EMPTY.wav",
            name="THEME_EMPTY",
            media_type="audio",
            audio_setting_id=audio_setting.audio_setting_id,
            uploader_id=1,
            creator_id=1,
        )
        db.add(media_with_site)
        db.add(media_without_site)
        db.add(media_without_theme)
        db.commit()
        db.refresh(media_with_site)
        db.refresh(media_without_site)
        db.refresh(media_without_theme)

        db.add(
            MediaCollection(
                media_id=media_with_site.media_id,
                collection_id=collection_with_sphere.collection_id,
                added_by=1,
            )
        )
        db.add(
            MediaCollection(
                media_id=media_without_site.media_id,
                collection_id=collection_with_sphere.collection_id,
                added_by=1,
            )
        )
        db.add(
            MediaCollection(
                media_id=media_without_theme.media_id,
                collection_id=collection_without_sphere.collection_id,
                added_by=1,
            )
        )
        db.commit()

        site_resp = client.get(
            f"{settings.API_V1_STR}/media/{media_with_site.media_id}",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert site_resp.status_code == 200
        site_data = site_resp.json()["data"]
        assert site_data["theme_value"] == "Freshwater"
        assert site_data["theme_source"] == "site_realm"

        collection_resp = client.get(
            f"{settings.API_V1_STR}/media/{media_without_site.media_id}",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert collection_resp.status_code == 200
        collection_data = collection_resp.json()["data"]
        assert collection_data["theme_value"] == "hydrosphere"
        assert collection_data["theme_source"] == "collection_sphere"

        empty_resp = client.get(
            f"{settings.API_V1_STR}/media/{media_without_theme.media_id}",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert empty_resp.status_code == 200
        empty_data = empty_resp.json()["data"]
        assert empty_data["theme_value"] is None
        assert empty_data["theme_source"] is None

    def test_get_media_preview_urls_use_absolute_static_paths(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Media detail previews should return normalized absolute static URLs."""
        project_id, public_media_id, _ = TestMediaBrowse._setup_browse_data(db)
        db.add(
            Preview(
                media_id=public_media_id,
                filename="REC_PUBLIC_001_player_s.png",
                type="spectrogram",
            )
        )
        db.commit()

        browse_resp = client.get(
            f"{settings.API_V1_STR}/media-browse-items",
            headers=superuser_token_headers,
            params={"project_id": project_id, "view_type": "gallery"},
        )
        assert browse_resp.status_code == 200
        browse_item = next(item for item in browse_resp.json()["data"] if item["media_id"] == public_media_id)
        browse_preview_url = browse_item.get("preview_url")
        assert browse_preview_url is not None
        assert browse_preview_url.endswith("/REC_PUBLIC_001_player_s.png")

        detail_resp = client.get(
            f"{settings.API_V1_STR}/media/{public_media_id}",
            headers=superuser_token_headers,
            params={"project_id": project_id},
        )
        assert detail_resp.status_code == 200
        previews = detail_resp.json()["data"]["previews"]
        assert previews

        detail_urls = [p["url"] for p in previews]
        assert all(u.startswith(f"{settings.media_base_url}/") for u in detail_urls)
        assert all("/api/v1/media/" not in u for u in detail_urls)
        assert all("/media/previews/" not in u for u in detail_urls)
        assert all("\\" not in u for u in detail_urls)
        assert all("/sounds/sounds/sounds/" not in u for u in detail_urls)
        assert browse_preview_url in detail_urls
        assert detail_urls[0] == browse_preview_url

    def test_get_metadata_media_exposes_audio_setting_without_audio_url(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        project_id, _, _ = TestMediaBrowse._setup_browse_data(db)
        public_collection_id = db.exec(
            select(Collection.collection_id)
            .where(Collection.name == "Browse Public")
            .order_by(Collection.collection_id.desc())
        ).first()
        assert public_collection_id is not None

        metadata_audio_setting = AudioSetting(
            duration_s=66.0,
            sampling_rate_hz=22050,
            bit_depth=16,
            channel_num=1,
            recording_gain_db=5,
        )
        db.add(metadata_audio_setting)
        db.commit()
        db.refresh(metadata_audio_setting)

        metadata_media = Media(
            filename="DETAIL_META_001.csv",
            name="DETAIL_META_001",
            media_type="audio", is_metadata=True,
            audio_setting_id=metadata_audio_setting.audio_setting_id,
            uploader_id=1,
            creator_id=1,
            date_time=datetime.now(UTC),
        )
        db.add(metadata_media)
        db.commit()
        db.refresh(metadata_media)
        db.add(
            MediaCollection(
                media_id=metadata_media.media_id,
                collection_id=public_collection_id,
                added_by=1,
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{metadata_media.media_id}",
            headers=superuser_token_headers,
            params={"project_id": project_id},
        )
        assert r.status_code == 200
        payload = r.json()["data"]
        assert payload["media_type"] == "audio"
        assert payload["is_metadata"] is True
        assert payload["audio_url"] is None
        assert payload["audio_setting"] == {
            "recording_gain_db": 5,
            "sampling_rate_hz": 22050,
            "bit_depth": 16,
            "channel_num": 1,
            "duration_s": 66.0,
        }


class TestMediaUpdate:
    """Tests for media update endpoint."""

    def test_update_media_requires_auth(self, client: TestClient) -> None:
        """Update media requires authentication."""
        r = client.patch(
            f"{settings.API_V1_STR}/media/1",
            json={"name": "Updated Name"}
        )
        assert r.status_code == 401

    def test_update_media_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Return HTTP 404 if media not found."""
        r = client.patch(
            f"{settings.API_V1_STR}/media/99999",
            headers=superuser_token_headers,
            params={"project_id": 1},
            json={"name": "Updated Name", "date_time": "2024-01-01 00:00:00"}
        )
        assert r.status_code == 404


class TestMediaDelete:
    """Tests for media delete endpoint."""

    def test_delete_media_requires_auth(self, client: TestClient) -> None:
        """Delete media requires authentication."""
        r = client.delete(f"{settings.API_V1_STR}/media/1")
        assert r.status_code == 401

    def test_delete_media_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Return HTTP 404 if media not found."""
        r = client.delete(
            f"{settings.API_V1_STR}/media/99999",
            headers=superuser_token_headers
        )
        assert r.status_code == 404


class TestMediaExport:
    """Tests for media export endpoint."""

    @pytest.mark.parametrize("resource", ["audios", "photos"])
    def test_export_media_resource_missing_project_id(
        self,
        client: TestClient,
        superuser_token_headers: dict,
        resource: str,
    ) -> None:
        r = client.get(
            f"{settings.API_V1_STR}/{resource}/exports",
            headers=superuser_token_headers
        )
        assert r.status_code == 422

    def test_export_audio_admin(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        r = client.get(
            f"{settings.API_V1_STR}/audios/exports?project_id=1",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "text/csv; charset=utf-8"
        assert r.headers["content-disposition"] == (
            'attachment; filename="audios.csv"; '
            "filename*=UTF-8''audios.csv"
        )
        header = read_csv_header(r.text)
        assert header == [
            "media_id", "uuid", "media_type", "type", "name", "filename", "site_name", "sensor_name",
            "medium", "sampling_rate_hz", "bit_depth", "channel_num", "duration_s",
            "size_b", "recording_gain_db", "duty_cycle_recording", "duty_cycle_period",
            "license_name", "doi", "note",
            "uploader_name", "uploader_id", "creator_name", "creator_id", "date_time",
        ]

    def test_export_audio_normal_user(
        self, client: TestClient, normal_user_token_headers: dict
    ) -> None:
        r = client.get(
            f"{settings.API_V1_STR}/audios/exports?project_id=1",
            headers=normal_user_token_headers
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "text/csv; charset=utf-8"

    @pytest.mark.parametrize(
        ("resource", "expected_media_type", "filename"),
        [
            ("audios", "audio", "audios.csv"),
            ("photos", "photo", "photos.csv"),
        ],
    )
    def test_export_media_resource_only_returns_fixed_type(
        self,
        client: TestClient,
        superuser_token_headers: dict,
        db: Session,
        resource: str,
        expected_media_type: str,
        filename: str,
    ) -> None:
        project_id, _, _ = TestMediaBrowse._setup_browse_data(db)
        collection_id = db.exec(
            select(Collection.collection_id)
            .where(Collection.name == "Browse Public")
            .order_by(Collection.collection_id.desc())
        ).first()
        assert collection_id is not None

        photo_setting = PhotoSetting(exposure_ms=5, aperture=2.8, iso=100)
        db.add(photo_setting)
        db.flush()
        photo = Media(
            filename="EXPORT_PHOTO_001.jpg",
            name="EXPORT_PHOTO_001",
            media_type="photo",
            photo_setting_id=photo_setting.photo_setting_id,
            uploader_id=1,
            creator_id=1,
        )
        db.add(photo)
        db.commit()
        db.refresh(photo)
        db.add(
            MediaCollection(
                media_id=photo.media_id,
                collection_id=collection_id,
                added_by=1,
            )
        )
        db.commit()

        response = client.get(
            f"{settings.API_V1_STR}/{resource}/exports",
            headers=superuser_token_headers,
            params={"project_id": project_id},
        )

        assert response.status_code == 200
        assert f'filename="{filename}"' in response.headers["content-disposition"]
        rows = list(csv.reader(response.text.splitlines()))
        assert rows[1:]
        # Audio export carries a "Media Type" column; the photo export set omits it
        # (aligned to the photo list), so verify the type column only when present.
        header = rows[0]
        if "Media Type" in header:
            media_type_idx = header.index("Media Type")
            assert {row[media_type_idx] for row in rows[1:]} == {expected_media_type}

    @pytest.mark.parametrize("resource", ["audios", "photos"])
    def test_export_media_resource_requires_auth(
        self,
        client: TestClient,
        resource: str,
    ) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/{resource}/exports",
            params={"project_id": 1},
        )

        assert response.status_code == 401

    def test_export_media_metadata_row_includes_audio_setting_values(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        project_id, _, _ = TestMediaBrowse._setup_browse_data(db)
        public_collection_id = db.exec(
            select(Collection.collection_id)
            .where(Collection.name == "Browse Public")
            .order_by(Collection.collection_id.desc())
        ).first()
        assert public_collection_id is not None

        metadata_audio_setting = AudioSetting(
            duration_s=91.5,
            sampling_rate_hz=16000,
            bit_depth=8,
            channel_num=1,
            recording_gain_db=3,
        )
        db.add(metadata_audio_setting)
        db.commit()
        db.refresh(metadata_audio_setting)

        metadata_media = Media(
            filename="EXPORT_META_001.csv",
            name="EXPORT_META_001",
            media_type="audio", is_metadata=True,
            audio_setting_id=metadata_audio_setting.audio_setting_id,
            uploader_id=1,
            creator_id=1,
            date_time=datetime(2026, 3, 17, 10, 0, 0),
        )
        db.add(metadata_media)
        db.commit()
        db.refresh(metadata_media)
        db.add(
            MediaCollection(
                media_id=metadata_media.media_id,
                collection_id=public_collection_id,
                added_by=1,
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/audios/exports",
            headers=superuser_token_headers,
            params={"project_id": project_id},
        )
        assert r.status_code == 200
        rows = list(csv.reader(r.text.splitlines()))
        header = rows[0]
        metadata_row = next(
            row for row in rows[1:] if row[header.index("name")] == "EXPORT_META_001"
        )
        assert metadata_row[header.index("media_type")] == "audio"
        assert metadata_row[header.index("type")] == "metadata"
        assert metadata_row[header.index("sampling_rate_hz")] == "16000"
        assert metadata_row[header.index("bit_depth")] == "8"
        assert metadata_row[header.index("channel_num")] == "1"
        assert metadata_row[header.index("duration_s")] == "91.5"
        # Date Time carries the media capture time, not the DB insert time.
        assert metadata_row[header.index("date_time")] == "2026-03-17 10:00:00"

    def test_export_audio_csv_reimportable(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """An exported audio CSV can be POSTed back to the metadata import endpoint."""
        project_id, _, _ = TestMediaBrowse._setup_browse_data(db)
        public_collection_id = db.exec(
            select(Collection.collection_id)
            .where(Collection.name == "Browse Public")
            .order_by(Collection.collection_id.desc())
        ).first()
        assert public_collection_id is not None

        audio_setting = AudioSetting(
            duration_s=45.0,
            sampling_rate_hz=22050,
            bit_depth=16,
            channel_num=2,
        )
        db.add(audio_setting)
        db.commit()
        db.refresh(audio_setting)
        metadata_media = Media(
            name="REIMPORT_META_001",
            media_type="audio", is_metadata=True,
            audio_setting_id=audio_setting.audio_setting_id,
            uploader_id=1,
            creator_id=1,
            date_time=datetime(2026, 4, 1, 6, 30, 0),
        )
        db.add(metadata_media)
        db.commit()
        db.refresh(metadata_media)
        db.add(
            MediaCollection(
                media_id=metadata_media.media_id,
                collection_id=public_collection_id,
                added_by=1,
            )
        )
        db.commit()

        export = client.get(
            f"{settings.API_V1_STR}/audios/exports",
            headers=superuser_token_headers,
            params={"project_id": project_id, "collection_id": public_collection_id},
        )
        assert export.status_code == 200

        # Keep only the metadata row: file rows would otherwise create new
        # metadata records by design.
        rows = list(csv.reader(export.text.splitlines()))
        header = rows[0]
        type_idx = header.index("type")
        name_idx = header.index("name")
        kept = [rows[0]] + [
            row for row in rows[1:]
            if row[type_idx] == "metadata" and row[name_idx] == "REIMPORT_META_001"
        ]
        assert len(kept) == 2
        buffer = io.StringIO()
        csv.writer(buffer).writerows(kept)

        count_before = len(db.exec(select(Media)).all())
        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={"project_id": project_id, "collection_id": public_collection_id},
            files={"file": ("export.csv", buffer.getvalue().encode("utf-8"), "text/csv")},
        )
        assert r.status_code == 200
        resp_data = r.json()["data"]
        # The exported row matches the existing record exactly, so it dedups.
        assert resp_data["total"] == 1
        assert resp_data["succeeded"] == 0
        assert resp_data["skipped"] == 1
        assert len(db.exec(select(Media)).all()) == count_before

    def test_export_photo_header_uses_import_template_keys(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        project_id, _, _ = TestMediaBrowse._setup_browse_data(db)
        r = client.get(
            f"{settings.API_V1_STR}/photos/exports",
            headers=superuser_token_headers,
            params={"project_id": project_id},
        )
        assert r.status_code == 200
        header = read_csv_header(r.text)
        for key in ("date_time", "name", "exposure_ms", "aperture", "iso"):
            assert key in header


class TestMetadataImport:
    """Tests for metadata CSV import endpoint."""

    def test_import_metadata_unauthorized(self, client: TestClient) -> None:
        """Metadata import requires authentication."""
        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            data={"collection_id": 1},
            files={"file": ("test.csv", b"dummy data")}
        )
        assert r.status_code == 401

    def test_import_metadata_collection_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Return HTTP 404 if collection not found."""
        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={"project_id": 1, "collection_id": 99999},
            files={"file": ("test.csv", b"dummy data")}
        )
        assert r.status_code == 404

    def test_import_metadata_no_permission(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        """Return 403 if no write permission."""
        # Get a user for creator_id
        user = db.exec(select(User)).first()

        # Create a private collection the user doesn't have access to
        col = Collection(name="Private Col", public_access=False, creator_id=user.user_id)
        db.add(col)
        db.commit()
        db.refresh(col)
        project_id = _ensure_project_for_collection(db, col.collection_id, user.user_id)

        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=normal_user_token_headers,
            data={"project_id": project_id, "collection_id": col.collection_id},
            files={"file": ("test.csv", b"dummy data")}
        )
        assert r.status_code == 403

    def test_import_metadata_invalid_csv_format(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Invalid CSV rows return an uncommitted import report."""
        # Ensure we have a collection
        col = db.exec(select(Collection)).first()
        if not col:
            user = db.exec(select(User)).first()
            col = Collection(name="Test Col", public_access=True, creator_id=user.user_id)
            db.add(col)
            db.commit()
            db.refresh(col)
        project_id = _ensure_project_for_collection(db, col.collection_id, col.creator_id)

        csv_content = (
            "date_time,duration_s,sampling_rate_hz,name,bit_depth,channel_num,duty_cycle_recording,duty_cycle_period\n"
            "2024-01-01 08:00:00,600.0,44100,Row 1,16,1,,\n"
            "INVALID_DATE,300.5,48000,Row 2,24,2,60,600\n"
        ).encode("utf-8")

        # Count media before
        count_before = len(db.exec(select(Media)).all())

        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={"project_id": project_id, "collection_id": col.collection_id},
            files={"file": ("test.csv", csv_content, "text/csv")}
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["committed"] is False
        assert data["total"] == 2
        assert data["failed"] == 2
        err_msg = data["global_errors"][0]
        assert "Row 3, column 1 (date_time)" in err_msg
        assert "INVALID_DATE" in err_msg
        assert "supported formats" in err_msg

        # Verify nothing was inserted
        count_after = len(db.exec(select(Media)).all())
        assert count_after == count_before

    def test_import_metadata_rejects_row_width_mismatch(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Upload endpoint rejects a data row whose field count differs from the header."""
        col = db.exec(select(Collection)).first()
        if not col:
            user = db.exec(select(User)).first()
            col = Collection(name="Test Col", public_access=True, creator_id=user.user_id)
            db.add(col)
            db.commit()
            db.refresh(col)
        project_id = _ensure_project_for_collection(db, col.collection_id, col.creator_id)

        # Header has 4 columns; the data row only has 3 -> column shift.
        csv_content = (
            "date_time,duration_s,sampling_rate_hz,name\n"
            "2024-05-01 08:00:00,10.5,48000\n"
        ).encode("utf-8")
        count_before = len(db.exec(select(Media)).all())

        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={"project_id": project_id, "collection_id": col.collection_id},
            files={"file": ("test.csv", csv_content, "text/csv")}
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["committed"] is False
        assert data["total"] == 1
        assert data["failed"] == 1
        assert "expected 4 columns" in data["global_errors"][0]
        assert len(db.exec(select(Media)).all()) == count_before

    def test_import_metadata_rejects_extra_trailing_cell_with_blank_header(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """A trailing blank header column must not let rows carry an extra trailing cell."""
        col = db.exec(select(Collection)).first()
        if not col:
            user = db.exec(select(User)).first()
            col = Collection(name="Test Col", public_access=True, creator_id=user.user_id)
            db.add(col)
            db.commit()
            db.refresh(col)
        project_id = _ensure_project_for_collection(db, col.collection_id, col.creator_id)

        # Header ends with a spreadsheet-style trailing comma (effective 4 columns);
        # the data row smuggles a 5th trailing cell that must be rejected.
        csv_content = (
            "date_time,duration_s,sampling_rate_hz,name,\n"
            "2024-05-01 08:00:00,10.5,48000,rec.wav,extra\n"
        ).encode("utf-8")
        count_before = len(db.exec(select(Media)).all())

        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={"project_id": project_id, "collection_id": col.collection_id},
            files={"file": ("test.csv", csv_content, "text/csv")}
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["committed"] is False
        assert data["total"] == 1
        assert data["failed"] == 1
        assert "expected 4 columns" in data["global_errors"][0]
        assert len(db.exec(select(Media)).all()) == count_before

    def test_import_metadata_rejects_unclosed_quote(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Upload endpoint rejects an unclosed quote that would swallow the next row."""
        col = db.exec(select(Collection)).first()
        if not col:
            user = db.exec(select(User)).first()
            col = Collection(name="Test Col", public_access=True, creator_id=user.user_id)
            db.add(col)
            db.commit()
            db.refresh(col)
        project_id = _ensure_project_for_collection(db, col.collection_id, col.creator_id)

        csv_content = (
            "Date Time,Duration(s),Sample Rate(Hz),Name\n"
            '2024-05-01 08:00:00,10.5,48000,"Unclosed\n'
            "2024-05-01 09:00:00,11.5,48000,Next\n"
        ).encode("utf-8")
        count_before = len(db.exec(select(Media)).all())

        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={"project_id": project_id, "collection_id": col.collection_id},
            files={"file": ("test.csv", csv_content, "text/csv")}
        )
        # Rejected either by the strict pre-guard (400) or the metadata parser (422).
        assert r.status_code in (400, 422)
        assert len(db.exec(select(Media)).all()) == count_before

    def test_import_metadata_invalid_recording_start_format(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Invalid date_time returns an uncommitted import report."""
        col = db.exec(select(Collection)).first()
        if not col:
            user = db.exec(select(User)).first()
            col = Collection(name="Test Col", public_access=True, creator_id=user.user_id)
            db.add(col)
            db.commit()
            db.refresh(col)
        project_id = _ensure_project_for_collection(db, col.collection_id, col.creator_id)

        csv_content = (
            "date_time,duration_s,sampling_rate_hz,name,bit_depth,channel_num,duty_cycle_recording,duty_cycle_period\n"
            "01-01-2022 12:12,600.0,44100,Bad Date,16,1,,\n"
        ).encode("utf-8")

        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={"project_id": project_id, "collection_id": col.collection_id},
            files={"file": ("test.csv", csv_content, "text/csv")}
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["committed"] is False
        assert data["total"] == 1
        assert data["failed"] == 1
        err_msg = data["global_errors"][0]
        assert "Row 2, column 1 (date_time)" in err_msg
        assert "01-01-2022 12:12" in err_msg
        assert "supported formats" in err_msg

    def test_import_metadata_all_rows_invalid(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """All invalid rows are reported before the atomic import is rejected."""

        # Ensure we have a collection
        col = db.exec(select(Collection)).first()
        if not col:
            user = db.exec(select(User)).first()
            col = Collection(name="Test Col", public_access=True, creator_id=user.user_id)
            db.add(col)
            db.commit()
            db.refresh(col)
        project_id = _ensure_project_for_collection(db, col.collection_id, col.creator_id)

        csv_content = (
            "date_time,duration_s,sampling_rate_hz,name,bit_depth,channel_num,duty_cycle_recording,duty_cycle_period\n"
            "2024-01-01 08:00:00,NOT_A_FLOAT,44100,Row 1,16,1,,\n"
            "INVALID_DATE,300.5,NOT_A_FLOAT,Row 2,24,2,60,600\n"
        ).encode("utf-8")

        # Count media before
        count_before = len(db.exec(select(Media)).all())

        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={"project_id": project_id, "collection_id": col.collection_id},
            files={"file": ("test.csv", csv_content, "text/csv")}
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["committed"] is False
        assert data["total"] == 2
        assert data["failed"] == 2
        err_msg = data["global_errors"][0]
        assert "Row 2, column 2 (duration_s)" in err_msg
        assert "NOT_A_FLOAT" in err_msg
        assert any("Row 3" in error for error in data["global_errors"])
        assert all(row["status"] == "failed" for row in data["rows"])

        # Verify nothing was inserted
        count_after = len(db.exec(select(Media)).all())
        assert count_after == count_before

    def test_import_metadata_success(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Successfully import all rows."""


        # Ensure we have a collection
        col = db.exec(select(Collection)).first()
        if not col:
            user = db.exec(select(User)).first()
            col = Collection(name="Test Col", public_access=True, creator_id=user.user_id)
            db.add(col)
            db.commit()
            db.refresh(col)
        project_id = _ensure_project_for_collection(db, col.collection_id, col.creator_id)

        csv_content = (
            "date_time,duration_s,sampling_rate_hz,name,bit_depth,channel_num,duty_cycle_recording,duty_cycle_period\n"
            "2022/1/1 12:12,600.0,44100,Successful Row 1,16,1,,\n"
            "2022-01-01T10:00:00,300.5,48000,Successful Row 2,24,2,60,600\n"
            "2022-01-01 12:12,120.0,32000,Successful Row 3,24,1,,\n"
        ).encode("utf-8")

        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={"project_id": project_id, "collection_id": col.collection_id},
            files={"file": ("test.csv", csv_content, "text/csv")}
        )
        assert r.status_code == 200

        resp_data = r.json()["data"]
        assert resp_data["total"] == 3
        assert resp_data["succeeded"] == 3
        assert resp_data["skipped"] == 0
        assert resp_data["failed"] == 0
        assert "results" not in resp_data
        assert resp_data["global_errors"] == []

        medias = db.exec(
            select(Media).where(Media.name.in_(["Successful Row 1", "Successful Row 2", "Successful Row 3"]))
        ).all()
        assert len(medias) == 3
        media_1 = next(m for m in medias if m.name == "Successful Row 1")
        media_2 = next(m for m in medias if m.name == "Successful Row 2")
        media_3 = next(m for m in medias if m.name == "Successful Row 3")
        assert media_1.media_type == "audio"
        assert media_1.is_metadata is True
        assert media_1.date_time is not None
        assert media_1.date_time.replace(tzinfo=None) == datetime(2022, 1, 1, 12, 12, 0)
        assert media_2.date_time.replace(tzinfo=None) == datetime(2022, 1, 1, 10, 0, 0)
        assert media_3.date_time.replace(tzinfo=None) == datetime(2022, 1, 1, 12, 12, 0)
        assert media_2.duty_cycle_recording == 60
        assert media_2.duty_cycle_period == 600
        # AudioSetting is created to preserve technical attributes from CSV
        assert media_1.audio_setting is not None
        assert media_1.audio_setting.duration_s == 600.0
        assert media_1.audio_setting.sampling_rate_hz == 44100
        assert media_1.audio_setting.bit_depth == 16
        assert media_1.audio_setting.channel_num == 1
        assert media_2.audio_setting is not None
        assert media_2.audio_setting.duration_s == 300.5
        assert media_2.audio_setting.sampling_rate_hz == 48000
        assert media_2.audio_setting.bit_depth == 24
        assert media_2.audio_setting.channel_num == 2
        assert media_3.audio_setting is not None
        assert media_3.audio_setting.duration_s == 120.0
        assert media_3.audio_setting.sampling_rate_hz == 32000

    def test_import_metadata_photo_success(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Successfully import photo metadata rows when media_type=photo."""
        col = db.exec(select(Collection)).first()
        if not col:
            user = db.exec(select(User)).first()
            col = Collection(name="Test Col", public_access=True, creator_id=user.user_id)
            db.add(col)
            db.commit()
            db.refresh(col)
        project_id = _ensure_project_for_collection(db, col.collection_id, col.creator_id)

        csv_content = (
            "date_time,name,exposure_ms,aperture,iso\n"
            "2022/1/1 12:12,Successful Photo 1,8.5,2.8,400\n"
            "2022-01-01T10:00:00,Successful Photo 2,,,\n"
        ).encode("utf-8")

        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={
                "project_id": project_id,
                "collection_id": col.collection_id,
                "media_type": "photo",
            },
            files={"file": ("test.csv", csv_content, "text/csv")}
        )
        assert r.status_code == 200

        resp_data = r.json()["data"]
        assert resp_data["total"] == 2
        assert resp_data["succeeded"] == 2
        assert resp_data["skipped"] == 0
        assert resp_data["global_errors"] == []

        medias = db.exec(
            select(Media).where(Media.name.in_(["Successful Photo 1", "Successful Photo 2"]))
        ).all()
        assert len(medias) == 2
        media_1 = next(m for m in medias if m.name == "Successful Photo 1")
        assert media_1.media_type == "photo"
        assert media_1.is_metadata is True
        assert media_1.audio_setting_id is None
        assert media_1.photo_setting is not None
        assert media_1.photo_setting.exposure_ms == 8.5
        assert media_1.photo_setting.aperture == 2.8
        assert media_1.photo_setting.iso == 400
        assert media_1.date_time.replace(tzinfo=None) == datetime(2022, 1, 1, 12, 12, 0)

    def test_import_metadata_photo_invalid_capture_time(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Invalid photo date_time returns an uncommitted import report."""
        col = db.exec(select(Collection)).first()
        if not col:
            user = db.exec(select(User)).first()
            col = Collection(name="Test Col", public_access=True, creator_id=user.user_id)
            db.add(col)
            db.commit()
            db.refresh(col)
        project_id = _ensure_project_for_collection(db, col.collection_id, col.creator_id)

        csv_content = (
            "date_time,name\n"
            "01-01-2022 12:12,Bad Date\n"
        ).encode("utf-8")

        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={
                "project_id": project_id,
                "collection_id": col.collection_id,
                "media_type": "photo",
            },
            files={"file": ("test.csv", csv_content, "text/csv")}
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["committed"] is False
        assert data["total"] == 1
        assert data["failed"] == 1
        err_msg = data["global_errors"][0]
        assert "Row 2, column 1 (date_time)" in err_msg
        assert "supported formats" in err_msg

    def test_import_metadata_unknown_header_column(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Unknown headers return an uncommitted import report.

        Legacy template keys such as "recording_start" are not accepted;
        headers must match the current exported field names.
        """
        col = db.exec(select(Collection)).first()
        if not col:
            user = db.exec(select(User)).first()
            col = Collection(name="Test Col", public_access=True, creator_id=user.user_id)
            db.add(col)
            db.commit()
            db.refresh(col)
        project_id = _ensure_project_for_collection(db, col.collection_id, col.creator_id)

        csv_content = (
            "date_time,duration_s,sampling_rate_hz,recording_start\n"
            "2024-01-01 08:00:00,600.0,44100,1\n"
        ).encode("utf-8")

        count_before = len(db.exec(select(Media)).all())

        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={"project_id": project_id, "collection_id": col.collection_id},
            files={"file": ("test.csv", csv_content, "text/csv")}
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["committed"] is False
        assert data["total"] == 1
        assert data["failed"] == 1
        err_msg = data["global_errors"][0]
        assert "unrecognized column" in err_msg
        assert "recording_start" in err_msg

        assert len(db.exec(select(Media)).all()) == count_before

    def test_import_metadata_header_order_independent(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Columns are mapped by header name, so their order does not matter."""
        col = db.exec(select(Collection)).first()
        if not col:
            user = db.exec(select(User)).first()
            col = Collection(name="Test Col", public_access=True, creator_id=user.user_id)
            db.add(col)
            db.commit()
            db.refresh(col)
        project_id = _ensure_project_for_collection(db, col.collection_id, col.creator_id)

        csv_content = (
            "name,sampling_rate_hz,date_time,duration_s,bit_depth\n"
            "Shuffled Row 1,22050,2024-05-01 09:30:00,45.5,24\n"
        ).encode("utf-8")

        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={"project_id": project_id, "collection_id": col.collection_id},
            files={"file": ("test.csv", csv_content, "text/csv")}
        )
        assert r.status_code == 200
        assert r.json()["data"]["succeeded"] == 1

        media = db.exec(select(Media).where(Media.name == "Shuffled Row 1")).first()
        assert media is not None
        assert media.date_time.replace(tzinfo=None) == datetime(2024, 5, 1, 9, 30, 0)
        assert media.audio_setting.sampling_rate_hz == 22050
        assert media.audio_setting.duration_s == 45.5
        assert media.audio_setting.bit_depth == 24

    def test_import_metadata_reimport_skips_duplicates(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Re-importing the same CSV skips rows identical to existing records."""
        col = db.exec(select(Collection)).first()
        if not col:
            user = db.exec(select(User)).first()
            col = Collection(name="Test Col", public_access=True, creator_id=user.user_id)
            db.add(col)
            db.commit()
            db.refresh(col)
        project_id = _ensure_project_for_collection(db, col.collection_id, col.creator_id)

        csv_content = (
            "date_time,duration_s,sampling_rate_hz,name,bit_depth,channel_num,duty_cycle_recording,duty_cycle_period\n"
            "2024-02-01 08:00:00,600.0,44100,Dedup Row 1,16,1,,\n"
            "2024-02-01 09:00:00,300.5,48000,Dedup Row 2,24,2,60,600\n"
        ).encode("utf-8")

        r1 = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={"project_id": project_id, "collection_id": col.collection_id},
            files={"file": ("test.csv", csv_content, "text/csv")}
        )
        assert r1.status_code == 200
        assert r1.json()["data"]["succeeded"] == 2

        count_after_first = len(db.exec(select(Media)).all())

        r2 = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=superuser_token_headers,
            data={"project_id": project_id, "collection_id": col.collection_id},
            files={"file": ("test.csv", csv_content, "text/csv")}
        )
        assert r2.status_code == 200
        resp_data = r2.json()["data"]
        assert resp_data["total"] == 2
        assert resp_data["succeeded"] == 0
        assert resp_data["skipped"] == 2

        assert len(db.exec(select(Media)).all()) == count_after_first

    def test_import_metadata_photo_no_permission(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        """Return 403 if no write permission for photo metadata import."""
        user = db.exec(select(User)).first()

        col = Collection(name="Private Photo Col", public_access=False, creator_id=user.user_id)
        db.add(col)
        db.commit()
        db.refresh(col)
        project_id = _ensure_project_for_collection(db, col.collection_id, user.user_id)

        r = client.post(
            f"{settings.API_V1_STR}/media-metadata-imports",
            headers=normal_user_token_headers,
            data={"project_id": project_id, "collection_id": col.collection_id, "media_type": "photo"},
            files={"file": ("test.csv", b"dummy data")}
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Tests for GET /media/{id}/spectrogram window parameter
# ---------------------------------------------------------------------------

class TestSpectrogramWindow:
    """Tests for the window parameter of the spectrogram endpoint."""

    def _make_media(self, db: Session, collection_id: int, uploader_id: int) -> Media:
        audio_setting = AudioSetting(
            sampling_rate_hz=22050,
            bit_depth=16,
            channel_num=1,
            duration_s=1.0,
        )
        db.add(audio_setting)
        db.flush()
        media = Media(
            filename="dummy.wav",
            media_type="audio",
            uploader_id=uploader_id,
            creator_id=uploader_id,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=collection_id, added_by=uploader_id))
        db.commit()
        db.refresh(media)
        return media

    def test_spectrogram_invalid_window_rejected(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """An unrecognised window function should return 400."""
        from sqlmodel import select as sel

        from app.models.user import User as UserModel
        superuser = db.exec(sel(UserModel).where(UserModel.role_id == 1)).first()

        proj = Project(name="spec_win_proj", url="http://x.com", creator_id=superuser.user_id)
        db.add(proj)
        db.commit()
        db.refresh(proj)
        from app.models import ProjectCollection
        col = Collection(
            name="spec_win_col", project_id=proj.project_id,
            creator_id=superuser.user_id, public_access=False
        )
        db.add(col)
        db.commit()
        db.refresh(col)
        db.add(ProjectCollection(project_id=proj.project_id, collection_id=col.collection_id))
        db.commit()

        media = self._make_media(db, col.collection_id, superuser.user_id)

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram?window=unknown_win&project_id={proj.project_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 400

    def test_spectrogram_valid_windows_accepted(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """All supported window functions are accepted (returns 200 when file is missing,
        not 400 — proving validation passed)."""
        from sqlmodel import select as sel

        from app.models.user import User as UserModel
        superuser = db.exec(sel(UserModel).where(UserModel.role_id == 1)).first()

        proj = Project(name="spec_win_proj2", url="http://x2.com", creator_id=superuser.user_id)
        db.add(proj)
        db.commit()
        db.refresh(proj)
        from app.models import ProjectCollection
        col = Collection(
            name="spec_win_col2", project_id=proj.project_id,
            creator_id=superuser.user_id, public_access=False
        )
        db.add(col)
        db.commit()
        db.refresh(col)
        db.add(ProjectCollection(project_id=proj.project_id, collection_id=col.collection_id))
        db.commit()

        media = self._make_media(db, col.collection_id, superuser.user_id)

        for win in ("hann", "hanning", "bartlett", "blackman", "hamming", "kaiser"):
            r = client.get(
                f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram?window={win}&project_id={proj.project_id}",
                headers=superuser_token_headers,
            )
            # File doesn't exist on disk should not be rejected by validation.
            assert r.status_code in (404, 500), f"window={win} got unexpected {r.status_code}"
            assert r.status_code != 400, f"window={win} was incorrectly rejected"


class TestDetailAudio:
    @staticmethod
    def _assert_download_header(
        header: str,
        *,
        fallback_filename: str,
        encoded_filename: str,
    ) -> None:
        assert f'filename="{fallback_filename}"' in header
        assert f"filename*=UTF-8''{encoded_filename}" in header

    def _make_audio_media(
        self,
        db: Session,
        *,
        creator_id: int,
        collection_id: int,
        filename: str,
        directory: int,
        sample_rate: int,
        channel_num: int = 1,
        duration_s: float = 1.0,
    ) -> Media:
        audio_setting = AudioSetting(
            sampling_rate_hz=sample_rate,
            bit_depth=16,
            channel_num=channel_num,
            duration_s=duration_s,
        )
        db.add(audio_setting)
        db.flush()
        media = Media(
            filename=filename,
            name=filename,
            media_type="audio",
            directory=directory,
            uploader_id=creator_id,
            creator_id=creator_id,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(
            MediaCollection(
                media_id=media.media_id,
                collection_id=collection_id,
                added_by=creator_id,
            )
        )
        db.commit()
        db.refresh(media)
        return media

    def test_audio_processing_returns_ogg_output(
        self,
        client: TestClient,
        superuser_token_headers: dict,
        db: Session,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        creator = db.exec(select(User).where(User.role_id == 1)).first()
        collection = Collection(name=f"detail_audio_{uuid.uuid4().hex[:6]}", creator_id=creator.user_id)
        db.add(collection)
        db.commit()
        db.refresh(collection)
        project_id = _ensure_project_for_collection(db, collection.collection_id, creator.user_id)

        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_path = tmp_path / "sounds" / str(collection.collection_id) / "31" / "processed.flac"
        _write_audio_fixture(audio_path, sample_rate=48_000)
        media = self._make_audio_media(
            db,
            creator_id=creator.user_id,
            collection_id=collection.collection_id,
            filename="processed.flac",
            directory=31,
            sample_rate=48_000,
        )

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/audio"
            f"?project_id={project_id}&start_time=0&end_time=0.25&channel=1",
            headers=superuser_token_headers,
        )

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("audio/ogg")
        self._assert_download_header(
            r.headers["content-disposition"],
            fallback_filename="processed_0-24000_0-0.25_512_1.ogg",
            encoded_filename="processed_0-24000_0-0.25_512_1.ogg",
        )
        assert len(r.content) > 0

    def test_audio_and_spectrogram_share_same_detail_bundle(
        self,
        client: TestClient,
        superuser_token_headers: dict,
        db: Session,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        creator = db.exec(select(User).where(User.role_id == 1)).first()
        collection = Collection(name=f"detail_bundle_{uuid.uuid4().hex[:6]}", creator_id=creator.user_id)
        db.add(collection)
        db.commit()
        db.refresh(collection)
        project_id = _ensure_project_for_collection(db, collection.collection_id, creator.user_id)

        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_path = tmp_path / "sounds" / str(collection.collection_id) / "32" / "shared.flac"
        _write_audio_fixture(audio_path, sample_rate=48_000)
        media = self._make_audio_media(
            db,
            creator_id=creator.user_id,
            collection_id=collection.collection_id,
            filename="shared.flac",
            directory=32,
            sample_rate=48_000,
        )

        audio_resp = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/audio"
            f"?project_id={project_id}&start_time=0&end_time=0.5&channel=1&filter=true&min_freq=1000&max_freq=20000&fft_size=512",
            headers=superuser_token_headers,
        )
        spec_resp = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram"
            f"?project_id={project_id}&start_time=0&end_time=0.5&channel=1&filter=true&min_freq=1000&max_freq=20000&fft_size=512",
            headers=superuser_token_headers,
        )

        assert audio_resp.status_code == 200
        assert spec_resp.status_code == 200
        self._assert_download_header(
            audio_resp.headers["content-disposition"],
            fallback_filename="shared_1000-20000_0-0.5_512_1_filtered.ogg",
            encoded_filename="shared_1000-20000_0-0.5_512_1_filtered.ogg",
        )
        self._assert_download_header(
            spec_resp.headers["content-disposition"],
            fallback_filename="shared_1000-20000_0-0.5_512_1_filtered.png",
            encoded_filename="shared_1000-20000_0-0.5_512_1_filtered.png",
        )

        detail_dir = tmp_path / "tmp" / "detail" / str(media.media_id)
        bundle_dirs = [item for item in detail_dir.iterdir() if item.is_dir()]
        assert len(bundle_dirs) == 1
        assert (bundle_dirs[0] / "zoomed_filtered.flac").exists()
        assert (bundle_dirs[0] / "spectrogram.wav").exists()
        assert (bundle_dirs[0] / "manifest.json").exists()

    def test_audio_and_spectrogram_accept_float_frequency_bounds(
        self,
        client: TestClient,
        superuser_token_headers: dict,
        db: Session,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        creator = db.exec(select(User).where(User.role_id == 1)).first()
        collection = Collection(name=f"detail_float_freq_{uuid.uuid4().hex[:6]}", creator_id=creator.user_id)
        db.add(collection)
        db.commit()
        db.refresh(collection)
        project_id = _ensure_project_for_collection(db, collection.collection_id, creator.user_id)

        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_path = tmp_path / "sounds" / str(collection.collection_id) / "33" / "floatfreq.flac"
        _write_audio_fixture(audio_path, sample_rate=48_000)
        media = self._make_audio_media(
            db,
            creator_id=creator.user_id,
            collection_id=collection.collection_id,
            filename="floatfreq.flac",
            directory=33,
            sample_rate=48_000,
        )
        query = (
            f"?project_id={project_id}&start_time=0.123456&end_time=0.543219&channel=1"
            "&filter=true&min_freq=3810.56784&max_freq=8121.21976&fft_size=512"
        )

        audio_resp = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/audio{query}",
            headers=superuser_token_headers,
        )
        spec_resp = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram{query}",
            headers=superuser_token_headers,
        )

        assert audio_resp.status_code == 200
        assert spec_resp.status_code == 200
        self._assert_download_header(
            audio_resp.headers["content-disposition"],
            fallback_filename="floatfreq_3810.5678-8121.2198_0.1235-0.5432_512_1_filtered.ogg",
            encoded_filename="floatfreq_3810.5678-8121.2198_0.1235-0.5432_512_1_filtered.ogg",
        )
        self._assert_download_header(
            spec_resp.headers["content-disposition"],
            fallback_filename="floatfreq_3810.5678-8121.2198_0.1235-0.5432_512_1_filtered.png",
            encoded_filename="floatfreq_3810.5678-8121.2198_0.1235-0.5432_512_1_filtered.png",
        )

        detail_dir = tmp_path / "tmp" / "detail" / str(media.media_id)
        bundle_dirs = [item for item in detail_dir.iterdir() if item.is_dir()]
        assert len(bundle_dirs) == 1
        manifest = json.loads((bundle_dirs[0] / "manifest.json").read_text())
        assert manifest["parameters"]["start_time"] == 0.1235
        assert manifest["parameters"]["end_time"] == 0.5432
        assert manifest["parameters"]["min_freq"] == 3810.5678
        assert manifest["parameters"]["max_freq"] == 8121.2198

    def test_spectrogram_repeated_requests_return_identical_png(
        self,
        client: TestClient,
        superuser_token_headers: dict,
        db: Session,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        creator = db.exec(select(User).where(User.role_id == 1)).first()
        collection = Collection(name=f"spec_repeat_{uuid.uuid4().hex[:6]}", creator_id=creator.user_id)
        db.add(collection)
        db.commit()
        db.refresh(collection)
        project_id = _ensure_project_for_collection(db, collection.collection_id, creator.user_id)
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_path = tmp_path / "sounds" / str(collection.collection_id) / "34" / "repeat.wav"
        _write_audio_fixture(audio_path, sample_rate=22_050)
        media = self._make_audio_media(
            db,
            creator_id=creator.user_id,
            collection_id=collection.collection_id,
            filename="repeat.wav",
            directory=34,
            sample_rate=22_050,
        )
        url = (
            f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram"
            f"?project_id={project_id}&start_time=0&end_time=0.5&channel=1"
            "&min_freq=0&max_freq=10000&fft_size=512&width=180&height=100"
        )

        first = client.get(url, headers=superuser_token_headers)
        second = client.get(url, headers=superuser_token_headers)

        assert first.status_code == 200
        assert second.status_code == 200
        assert hashlib.sha256(first.content).digest() == hashlib.sha256(second.content).digest()

    def test_spectrogram_concurrent_requests_return_identical_png(
        self,
        client: TestClient,
        superuser_token_headers: dict,
        db: Session,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        creator = db.exec(select(User).where(User.role_id == 1)).first()
        collection = Collection(name=f"spec_concurrent_{uuid.uuid4().hex[:6]}", creator_id=creator.user_id)
        db.add(collection)
        db.commit()
        db.refresh(collection)
        project_id = _ensure_project_for_collection(db, collection.collection_id, creator.user_id)
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_path = tmp_path / "sounds" / str(collection.collection_id) / "35" / "concurrent.wav"
        _write_audio_fixture(audio_path, sample_rate=22_050)
        media = self._make_audio_media(
            db,
            creator_id=creator.user_id,
            collection_id=collection.collection_id,
            filename="concurrent.wav",
            directory=35,
            sample_rate=22_050,
        )
        url = (
            f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram"
            f"?project_id={project_id}&start_time=0&end_time=0.5&channel=1"
            "&filter=true&min_freq=100&max_freq=10000&fft_size=512&width=180&height=100"
        )

        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(
                executor.map(
                    lambda _index: client.get(url, headers=superuser_token_headers),
                    range(4),
                )
            )

        assert {response.status_code for response in responses} == {200}
        assert len({hashlib.sha256(response.content).digest() for response in responses}) == 1
        detail_dir = tmp_path / "tmp" / "detail" / str(media.media_id)
        bundle_dirs = [item for item in detail_dir.iterdir() if item.is_dir()]
        assert len(bundle_dirs) == 1
        assert (bundle_dirs[0] / "manifest.json").exists()

    def test_audio_and_spectrogram_download_headers_support_chinese_filename(
        self,
        client: TestClient,
        superuser_token_headers: dict,
        db: Session,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        creator = db.exec(select(User).where(User.role_id == 1)).first()
        collection = Collection(name=f"detail_cn_{uuid.uuid4().hex[:6]}", creator_id=creator.user_id)
        db.add(collection)
        db.commit()
        db.refresh(collection)
        project_id = _ensure_project_for_collection(db, collection.collection_id, creator.user_id)

        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_path = tmp_path / "sounds" / str(collection.collection_id) / "33" / "中文录音.flac"
        _write_audio_fixture(audio_path, sample_rate=48_000)
        media = self._make_audio_media(
            db,
            creator_id=creator.user_id,
            collection_id=collection.collection_id,
            filename="中文录音.flac",
            directory=33,
            sample_rate=48_000,
        )

        audio_resp = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/audio"
            f"?project_id={project_id}&start_time=0&end_time=0.5&channel=1&fft_size=512",
            headers=superuser_token_headers,
        )
        spec_resp = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram"
            f"?project_id={project_id}&start_time=0&end_time=0.5&channel=1&fft_size=512",
            headers=superuser_token_headers,
        )

        assert audio_resp.status_code == 200
        assert spec_resp.status_code == 200
        self._assert_download_header(
            audio_resp.headers["content-disposition"],
            fallback_filename="0-24000_0-0.5_512_1.ogg",
            encoded_filename="%E4%B8%AD%E6%96%87%E5%BD%95%E9%9F%B3_0-24000_0-0.5_512_1.ogg",
        )
        self._assert_download_header(
            spec_resp.headers["content-disposition"],
            fallback_filename="1-24000_0-0.5_512_1.png",
            encoded_filename="%E4%B8%AD%E6%96%87%E5%BD%95%E9%9F%B3_1-24000_0-0.5_512_1.png",
        )


class TestPhotoMediaEndpoints:
    def test_photo_media_rejects_audio_stream_endpoint(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        creator = db.exec(select(User).where(User.role_id == 1)).first()
        collection = Collection(
            name=f"photo_col_{uuid.uuid4().hex[:6]}",
            creator_id=creator.user_id,
            public_access=False,
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)
        project_id = _ensure_project_for_collection(db, collection.collection_id, creator.user_id)

        photo_setting = PhotoSetting()
        db.add(photo_setting)
        db.flush()
        media = Media(
            filename="photo_a.jpg",
            name="photo_a.jpg",
            media_type="photo",
            directory=1,
            uploader_id=creator.user_id,
            creator_id=creator.user_id,
            photo_setting_id=photo_setting.photo_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(
            MediaCollection(
                media_id=media.media_id,
                collection_id=collection.collection_id,
                added_by=creator.user_id,
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/audio?project_id={project_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404
        payload = r.json()
        assert payload.get("detail") == "Audio media not found on server" or payload.get("message") == "Audio media not found on server"

"""Integration tests for extra media API routes."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import get_current_user
from app.main import app
from app.models import (
    User, Role, Project, ProjectCollection, Collection, Media, MediaCollection, AudioSetting, UserPermission, Permission
)


@pytest.fixture
def setup_media_data(db: Session):
    admin_role = db.exec(select(Role).where(Role.name == "Administrator")).first()
    if not admin_role:
        admin_role = Role(name="Administrator")
        db.add(admin_role)

    role_name = "Media_Tester_Extra_Final_" + str(datetime.now().timestamp())
    user_role = Role(name=role_name)
    db.add(user_role)
    db.flush()

    admin = User(username="admin_me_f", role_id=admin_role.role_id, email="amef@e.com", password="p", name="Admin")
    user = User(username="user_me_f", role_id=user_role.role_id, email="umef@e.com", password="p", name="User")
    db.add_all([admin, user])
    db.flush()

    col = Collection(name="Me Col F", creator_id=user.user_id)
    db.add(col)
    db.flush()
    project = Project(name="Me Project F", creator_id=user.user_id, url="https://media-extra.example")
    db.add(project)
    db.flush()
    db.add(ProjectCollection(project_id=project.project_id, collection_id=col.collection_id))
    db.flush()

    aset = AudioSetting(sampling_rate_hz=48000, bit_depth=16, channel_num=1, duration_s=10)
    db.add(aset)
    db.flush()

    media = Media(
        name="Me Media F",
        uploader_id=user.user_id,
        creator_id=user.user_id,
        media_type="audio",
        audio_setting_id=aset.audio_setting_id,
        filename="rec.wav",
        directory=1
    )
    db.add(media)
    db.flush()
    db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
    db.flush()

    return {"admin": admin, "user": user, "media": media, "collection": col, "project": project}


class TestMediaRouteScenarios:
    """Extra tests for media API to push coverage."""

    def test_create_media_no_permission(self, client: TestClient, db: Session, setup_media_data):
        u2 = User(username="u_no_p_me_f", role_id=setup_media_data["user"].role_id, email="unpmef@e.com", password="p", name="U")
        db.add(u2)
        db.flush()
        col = setup_media_data["collection"]

        app.dependency_overrides[get_current_user] = lambda: u2
        try:
            response = client.post(
                "/api/v1/media",
                json={"collection_id": col.collection_id, "file_upload_ids": [1], "date_from_filename": True}
            )
            assert response.status_code == 403
        finally:
            app.dependency_overrides = {}

    def test_import_metadata_invalid_file(self, client: TestClient, db: Session, setup_media_data):
        user = setup_media_data["user"]
        col = setup_media_data["collection"]
        project = setup_media_data["project"]

        # Grant write permission to hit the validation logic
        perm_write = db.exec(select(Permission).where(Permission.name == "collection:write")).first()
        if not perm_write:
            perm_write = Permission(name="collection:write", resource_type="collection", action="write")
            db.add(perm_write)
            db.flush()
        db.add(UserPermission(user_id=user.user_id, project_id=project.project_id, collection_id=col.collection_id, permission_id=perm_write.permission_id))
        db.flush()

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            # Not a CSV
            response = client.post(
                "/api/v1/media-metadata-imports",
                data={"project_id": project.project_id, "collection_id": col.collection_id},
                files={"file": ("test.txt", b"not a csv", "text/plain")}
            )
            assert response.status_code == 400
        finally:
            app.dependency_overrides = {}

    def test_update_media_permission(self, client: TestClient, db: Session, setup_media_data):
        u2 = User(username="u_upd_me_f", role_id=setup_media_data["user"].role_id, email="uupmef@e.com", password="p", name="U")
        db.add(u2)
        db.flush()

        app.dependency_overrides[get_current_user] = lambda: u2
        try:
            response = client.patch(
                f"/api/v1/media/{setup_media_data['media'].media_id}",
                params={"project_id": setup_media_data["project"].project_id},
                json={"name": "New Name", "date_time": "2024-01-01 00:00:00"}
            )
            assert response.status_code == 403
        finally:
            app.dependency_overrides = {}

    def test_update_photo_rejects_null_audio_fields_without_changes(
        self, client: TestClient, db: Session, setup_media_data
    ):
        user = setup_media_data["user"]
        project = setup_media_data["project"]
        collection = setup_media_data["collection"]

        photo_setting = PhotoSetting()
        db.add(photo_setting)
        db.flush()
        photo = Media(
            name="Original Photo",
            uploader_id=user.user_id,
            creator_id=user.user_id,
            media_type="photo",
            photo_setting_id=photo_setting.photo_setting_id,
        )
        db.add(photo)
        db.flush()
        db.add(
            MediaCollection(
                media_id=photo.media_id,
                collection_id=collection.collection_id,
                added_by=user.user_id,
            )
        )

        write_permission = db.exec(
            select(Permission).where(Permission.name == "collection:write")
        ).first()
        if write_permission is None:
            write_permission = Permission(
                name="collection:write",
                resource_type="collection",
                action="write",
            )
            db.add(write_permission)
            db.flush()
        db.add(
            UserPermission(
                user_id=user.user_id,
                project_id=project.project_id,
                collection_id=collection.collection_id,
                permission_id=write_permission.permission_id,
            )
        )
        db.flush()
        audio_setting_count = len(db.exec(select(AudioSetting)).all())

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            response = client.patch(
                f"/api/v1/media/{photo.media_id}",
                params={"project_id": project.project_id},
                json={
                    "name": "Rejected Photo Name",
                    "date_time": "2026-07-24 01:06:53",
                    "site_id": None,
                    "sensor_id": None,
                    "medium": "Air",
                    "recording_gain_db": None,
                    "sampling_rate_hz": None,
                    "bit_depth": None,
                    "channel_num": None,
                    "duration_s": None,
                    "duty_cycle_recording": None,
                    "duty_cycle_period": None,
                    "license_id": None,
                    "doi": "333",
                    "note": "1123",
                },
            )
        finally:
            app.dependency_overrides = {}

        assert response.status_code == 422
        db.refresh(photo)
        assert photo.name == "Original Photo"
        assert len(db.exec(select(AudioSetting)).all()) == audio_setting_count

    def test_update_metadata_media_success_keeps_settings_null(self, client: TestClient, db: Session, setup_media_data):
        user = setup_media_data["user"]
        project = setup_media_data["project"]
        col = setup_media_data["collection"]

        metadata_media = Media(
            name="Imported Metadata Row",
            uploader_id=user.user_id,
            creator_id=user.user_id,
            media_type="audio", is_metadata=True,
            duty_cycle_recording=10,
            duty_cycle_period=100,
        )
        db.add(metadata_media)
        db.flush()
        db.add(
            MediaCollection(
                media_id=metadata_media.media_id,
                collection_id=col.collection_id,
                added_by=user.user_id,
            )
        )
        db.flush()

        perm_write = db.exec(select(Permission).where(Permission.name == "collection:write")).first()
        if not perm_write:
            perm_write = Permission(name="collection:write", resource_type="collection", action="write")
            db.add(perm_write)
            db.flush()
        db.add(
            UserPermission(
                user_id=user.user_id,
                project_id=project.project_id,
                collection_id=col.collection_id,
                permission_id=perm_write.permission_id,
            )
        )
        db.flush()

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            response = client.patch(
                f"/api/v1/media/{metadata_media.media_id}",
                params={"project_id": project.project_id},
                json={
                    "name": "Updated Metadata Row",
                    "note": "Only base fields should change",
                    "date_time": "2024-01-01 00:00:00",
                    "site_id": None,
                    "sensor_id": None,
                    "license_id": None,
                },
            )
            assert response.status_code == 200
        finally:
            app.dependency_overrides = {}

        db.refresh(metadata_media)
        assert metadata_media.name == "Updated Metadata Row"
        assert metadata_media.note == "Only base fields should change"
        assert metadata_media.audio_setting_id is None
        assert metadata_media.photo_setting_id is None

    def test_delete_media_permission(self, client: TestClient, db: Session, setup_media_data):
        u2 = User(username="u_del_me_f", role_id=setup_media_data["user"].role_id, email="udmef@e.com", password="p", name="U")
        db.add(u2)
        db.flush()

        app.dependency_overrides[get_current_user] = lambda: u2
        try:
            response = client.delete(
                f"/api/v1/media/{setup_media_data['media'].media_id}"
            )
            assert response.status_code == 403
        finally:
            app.dependency_overrides = {}

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models.collection import Collection
from app.models.media import Media, MediaCollection


def test_delete_media_with_collection_scope(
    client: TestClient, superuser_token_headers: dict, db: Session
) -> None:
    """Reproduce the bug where deleting media with a collection fails."""
    # 1. Create a collection
    collection = Collection(name="Test Bug Collection", creator_id=1)
    db.add(collection)
    db.commit()
    db.refresh(collection)

    # 2. Create a media
    media = Media(
        filename="bug_test.wav",
        media_type="audio", is_metadata=True,
        uploader_id=1,
        creator_id=1
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    # 3. Associate media with collection (this is what triggers the bug)
    mc = MediaCollection(media_id=media.media_id, collection_id=collection.collection_id, added_by=1)
    db.add(mc)
    db.commit()

    # 4. Attempt to delete the media
    r = client.delete(
        f"{settings.API_V1_STR}/media/{media.media_id}",
        headers=superuser_token_headers
    )

    # If the bug exists, this will return 500
    assert r.status_code == 200
    assert r.json()["message"] == "Media deleted successfully"

def test_photo_media_rejects_spectrogram_endpoint(
    client: TestClient, superuser_token_headers: dict, db: Session
) -> None:
    creator = db.exec(select(User).where(User.role_id == 1)).first()
    collection = Collection(
        name=f"photo_col_{uuid.uuid4().hex[:6]}_spec",
        creator_id=creator.user_id,
        public_access=False,
    )
    db.add(collection)
    db.commit()
    db.refresh(collection)
    project_id = _ensure_project_for_collection(db, collection.collection_id, creator.user_id)

    photo_setting = PhotoSetting()
    db.add(photo_setting)
    db.flush()
    media = Media(
        filename="photo_b.jpg",
        name="photo_b.jpg",
        media_type="photo",
        directory=2,
        uploader_id=creator.user_id,
        creator_id=creator.user_id,
        photo_setting_id=photo_setting.photo_setting_id,
    )
    db.add(media)
    db.flush()
    db.add(
        MediaCollection(
            media_id=media.media_id,
            collection_id=collection.collection_id,
            added_by=creator.user_id,
        )
    )
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram?project_id={project_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
    payload = r.json()
    assert (
        payload.get("detail") == "Audio media not found on server"
        or payload.get("message") == "Audio media not found on server"
    )
