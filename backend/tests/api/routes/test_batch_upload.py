"""
Tests for batch upload flow.
"""
import hashlib
import uuid
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session

from app.api.deps import get_redis_client, get_task_publisher
from app.core.config import settings
from app.main import app
from app.models import Collection, FileUpload, Media, MediaCollection, PhotoSetting, Project


def _create_project(db: Session) -> Project:
    project = Project(
        name=f"Import Project {uuid.uuid4().hex[:6]}",
        url=f"https://import-{uuid.uuid4().hex[:6]}.example",
        creator_id=1,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.jobs: list[tuple[str, dict]] = []

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def enqueue_task(self, task_name, **kwargs):
        self.jobs.append((task_name, kwargs))


async def _fake_redis_dependency(redis: FakeRedis):
    yield redis


def _override_redis(redis: FakeRedis):
    async def _dep():
        yield redis

    return _dep


def test_batch_init(client: TestClient, superuser_token_headers: dict) -> None:
    """Test generating a batch ID."""
    r = client.post(f"{settings.API_V1_STR}/file-upload-batches", headers=superuser_token_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert "batch_id" in data
    # uuid should be a valid UUID string
    assert len(data["batch_id"]) == 36


def test_chunk_upload_and_media_create_with_batch(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    """
    Full batch flow:
    1. Get batch_id
    2. Upload two files (single-chunk each), verify file_upload_id is returned
    3. Call POST /media with both file_upload_ids
    4. Verify both are in the queued list
    """
    redis = FakeRedis()
    app.dependency_overrides[get_redis_client] = _override_redis(redis)
    app.dependency_overrides[get_task_publisher] = _override_redis(redis)
    try:
        # Step 1: Get batch_id
        r = client.post(f"{settings.API_V1_STR}/file-upload-batches", headers=superuser_token_headers)
        batch_id = r.json()["data"]["batch_id"]

        file_upload_ids = []

        # Step 2: Upload two single-chunk files
        for i in range(2):
            filename = f"batch_test_{uuid.uuid4().hex[:6]}.wav"
            r = client.post(
                f"{settings.API_V1_STR}/file-upload-batches/{batch_id}/chunks",
                headers=superuser_token_headers,
                data={"filename": filename, "chunk_index": 0, "total_chunks": 1, "batch_id": batch_id},
                files={"file": ("chunk", b"audio data here")},
            )
            assert r.status_code == 200
            data = r.json()["data"]
            assert data["is_complete"] is True
            assert "file_upload_id" in data
            assert "queue_id" not in data
            file_upload_ids.append(data["file_upload_id"])

        # Step 3: Call POST /media with both file_upload_ids

        async def mock_redis():
            mock = AsyncMock()
            mock.enqueue_task = AsyncMock()
            yield mock

        app.dependency_overrides[get_task_publisher] = mock_redis
        r = client.post(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            json={
                "collection_id": 1,
                "file_upload_ids": file_upload_ids,
                "date_from_filename": True,
            },
        )
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert r.status_code == 200
    data = r.json()["data"]
    assert set(data["queued"]) == set(file_upload_ids)
    assert data["failed"] == []


def test_duplicate_file_in_same_batch_rejected(
    client: TestClient,
    superuser_token_headers: dict,
) -> None:
    """Uploading the same filename twice in the same batch returns 409 on the second call."""
    redis = FakeRedis()
    app.dependency_overrides[get_redis_client] = _override_redis(redis)
    app.dependency_overrides[get_task_publisher] = _override_redis(redis)
    try:
        r = client.post(f"{settings.API_V1_STR}/file-upload-batches", headers=superuser_token_headers)
        batch_id = r.json()["data"]["batch_id"]
        filename = f"dup_{uuid.uuid4().hex[:6]}.wav"

        # First upload completes successfully
        r1 = client.post(
            f"{settings.API_V1_STR}/file-upload-batches/{batch_id}/chunks",
            headers=superuser_token_headers,
            data={"filename": filename, "chunk_index": 0, "total_chunks": 1, "batch_id": batch_id},
            files={"file": ("chunk", b"first upload")},
        )
        assert r1.status_code == 200
        assert r1.json()["data"]["is_complete"] is True

        # Second upload of the same filename in the same batch must fail
        r2 = client.post(
            f"{settings.API_V1_STR}/file-upload-batches/{batch_id}/chunks",
            headers=superuser_token_headers,
            data={"filename": filename, "chunk_index": 0, "total_chunks": 1, "batch_id": batch_id},
            files={"file": ("chunk", b"second upload")},
        )
        assert r2.status_code == 409
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)
        app.dependency_overrides.pop(get_redis_client, None)


@pytest.mark.parametrize(
    ("suffix", "format_name"),
    [("jpg", "JPEG"), ("png", "PNG"), ("tiff", "TIFF")],
)
def test_photo_chunk_upload_merges_and_validates_synchronously(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
    suffix: str,
    format_name: str,
) -> None:
    redis = FakeRedis()
    app.dependency_overrides[get_redis_client] = _override_redis(redis)
    app.dependency_overrides[get_task_publisher] = _override_redis(redis)
    image = BytesIO()
    Image.new("RGB", (4, 3), "green").save(image, format_name)
    try:
        batch_response = client.post(
            f"{settings.API_V1_STR}/file-upload-batches",
            headers=superuser_token_headers,
        )
        batch_id = batch_response.json()["data"]["batch_id"]
        response = client.post(
            f"{settings.API_V1_STR}/file-upload-batches/{batch_id}/chunks",
            headers=superuser_token_headers,
            data={
                "filename": f"camera_{uuid.uuid4().hex[:8]}.{suffix}",
                "media_type": "photo",
                "chunk_index": 0,
                "total_chunks": 1,
            },
            files={"file": ("chunk", image.getvalue())},
        )
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 200
    assert response.json()["data"]["file_upload_id"] > 0
    assert redis.jobs == []
    file_upload = db.get(FileUpload, response.json()["data"]["file_upload_id"])
    assert file_upload is not None
    assert file_upload.status == 1
    assert file_upload.path == ""


def test_photo_chunk_upload_accepts_mpo_with_jpeg_extension(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    redis = FakeRedis()
    app.dependency_overrides[get_redis_client] = _override_redis(redis)
    app.dependency_overrides[get_task_publisher] = _override_redis(redis)
    image = BytesIO()
    primary = Image.new("RGB", (4, 3), "green")
    secondary = Image.new("RGB", (2, 2), "blue")
    primary.save(image, "MPO", save_all=True, append_images=[secondary])
    try:
        batch_response = client.post(
            f"{settings.API_V1_STR}/file-upload-batches",
            headers=superuser_token_headers,
        )
        batch_id = batch_response.json()["data"]["batch_id"]
        response = client.post(
            f"{settings.API_V1_STR}/file-upload-batches/{batch_id}/chunks",
            headers=superuser_token_headers,
            data={
                "filename": f"camera_{uuid.uuid4().hex[:8]}.jpg",
                "media_type": "photo",
                "chunk_index": 0,
                "total_chunks": 1,
            },
            files={"file": ("chunk", image.getvalue())},
        )
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 200
    file_upload = db.get(FileUpload, response.json()["data"]["file_upload_id"])
    assert file_upload is not None
    assert file_upload.filename.endswith(".jpg")
    assert file_upload.path == ""


def test_photo_chunk_upload_defers_duplicate_detection_until_media_processing(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    """Chunk upload only stages photos; duplicate handling runs in the media job."""
    collection = Collection(name=f"Dup Detect Col {uuid.uuid4().hex[:6]}", creator_id=1)
    db.add(collection)
    db.commit()
    db.refresh(collection)

    image_bytes = BytesIO()
    Image.new("RGB", (4, 3), "blue").save(image_bytes, "JPEG")
    image_bytes = image_bytes.getvalue()
    md5_hash = hashlib.md5(image_bytes).hexdigest()

    photo_setting = PhotoSetting()
    db.add(photo_setting)
    db.commit()
    db.refresh(photo_setting)
    existing_media = Media(
        media_type="photo",
        md5_hash=md5_hash,
        uploader_id=1,
        photo_setting_id=photo_setting.photo_setting_id,
    )
    db.add(existing_media)
    db.commit()
    db.refresh(existing_media)
    db.add(
        MediaCollection(
            media_id=existing_media.media_id,
            collection_id=collection.collection_id,
            added_by=1,
        )
    )
    db.commit()

    redis = FakeRedis()
    app.dependency_overrides[get_redis_client] = _override_redis(redis)
    app.dependency_overrides[get_task_publisher] = _override_redis(redis)
    try:
        batch_response = client.post(
            f"{settings.API_V1_STR}/file-upload-batches",
            headers=superuser_token_headers,
        )
        batch_id = batch_response.json()["data"]["batch_id"]
        response = client.post(
            f"{settings.API_V1_STR}/file-upload-batches/{batch_id}/chunks",
            headers=superuser_token_headers,
            data={
                "filename": f"camera_{uuid.uuid4().hex[:8]}.jpg",
                "media_type": "photo",
                "chunk_index": 0,
                "total_chunks": 1,
                "collection_id": collection.collection_id,
            },
            files={"file": ("chunk", image_bytes)},
        )
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 200
    data = response.json()["data"]
    assert "is_duplicate" not in data

    file_upload = db.get(FileUpload, data["file_upload_id"])
    assert file_upload is not None
    assert file_upload.status == 1
    assert file_upload.media_id is None
    assert file_upload.path == ""


def test_photo_chunk_upload_stages_photo_for_any_collection(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    """The collection does not alter the staging result before media processing."""
    matching_collection = Collection(name=f"Dup Col A {uuid.uuid4().hex[:6]}", creator_id=1)
    other_collection = Collection(name=f"Dup Col B {uuid.uuid4().hex[:6]}", creator_id=1)
    db.add_all([matching_collection, other_collection])
    db.commit()
    db.refresh(matching_collection)
    db.refresh(other_collection)

    image_bytes = BytesIO()
    Image.new("RGB", (4, 3), "red").save(image_bytes, "PNG")
    image_bytes = image_bytes.getvalue()
    md5_hash = hashlib.md5(image_bytes).hexdigest()

    photo_setting = PhotoSetting()
    db.add(photo_setting)
    db.commit()
    db.refresh(photo_setting)
    existing_media = Media(
        media_type="photo",
        md5_hash=md5_hash,
        uploader_id=1,
        photo_setting_id=photo_setting.photo_setting_id,
    )
    db.add(existing_media)
    db.commit()
    db.refresh(existing_media)
    db.add(
        MediaCollection(
            media_id=existing_media.media_id,
            collection_id=matching_collection.collection_id,
            added_by=1,
        )
    )
    db.commit()

    redis = FakeRedis()
    app.dependency_overrides[get_redis_client] = _override_redis(redis)
    app.dependency_overrides[get_task_publisher] = _override_redis(redis)
    try:
        batch_response = client.post(
            f"{settings.API_V1_STR}/file-upload-batches",
            headers=superuser_token_headers,
        )
        batch_id = batch_response.json()["data"]["batch_id"]
        response = client.post(
            f"{settings.API_V1_STR}/file-upload-batches/{batch_id}/chunks",
            headers=superuser_token_headers,
            data={
                "filename": f"camera_{uuid.uuid4().hex[:8]}.png",
                "media_type": "photo",
                "chunk_index": 0,
                "total_chunks": 1,
                "collection_id": other_collection.collection_id,
            },
            files={"file": ("chunk", image_bytes)},
        )
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 200
    data = response.json()["data"]
    assert not data.get("is_duplicate")

    file_upload = db.get(FileUpload, data["file_upload_id"])
    assert file_upload is not None
    assert file_upload.status == 1
    assert file_upload.path == ""


def test_photo_chunk_upload_rejects_audio_extension(
    client: TestClient,
    superuser_token_headers: dict,
) -> None:
    redis = FakeRedis()
    app.dependency_overrides[get_redis_client] = _override_redis(redis)
    try:
        batch_response = client.post(
            f"{settings.API_V1_STR}/file-upload-batches",
            headers=superuser_token_headers,
        )
        batch_id = batch_response.json()["data"]["batch_id"]
        response = client.post(
            f"{settings.API_V1_STR}/file-upload-batches/{batch_id}/chunks",
            headers=superuser_token_headers,
            data={
                "filename": "camera.wav",
                "media_type": "photo",
                "chunk_index": 0,
                "total_chunks": 1,
            },
            files={"file": ("chunk", b"not a photo")},
        )
    finally:
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 400
    assert response.json()["message"] == "unsupported_file_type"


def test_offline_import_batch_rejects_non_zip_upload(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    project = _create_project(db)
    redis = FakeRedis()
    app.dependency_overrides[get_redis_client] = _override_redis(redis)
    app.dependency_overrides[get_task_publisher] = _override_redis(redis)
    try:
        create_response = client.post(
            f"{settings.API_V1_STR}/data-imports",
            headers=superuser_token_headers,
            json={"project_id": project.project_id},
        )
        batch_id = create_response.json()["data"]["batch_id"]

        response = client.post(
            f"{settings.API_V1_STR}/file-upload-batches/{batch_id}/chunks",
            headers=superuser_token_headers,
            data={"filename": "not-a-bundle.wav", "chunk_index": 0, "total_chunks": 1, "batch_id": batch_id},
            files={"file": ("chunk", b"audio data here")},
        )
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 400
    assert (
        response.json().get("detail") == "Offline import batches only accept .zip files"
        or response.json().get("message") == "Offline import batches only accept .zip files"
    )
