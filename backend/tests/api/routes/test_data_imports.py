import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.deps import get_redis_client
from app.core.config import settings
from app.main import app
from app.models import Project
from app.repositories import user_repository
from app.schemas import UserCreate
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)


async def _fake_redis_dependency(redis: FakeRedis):
    yield redis


def _override_redis(redis: FakeRedis):
    async def _dep():
        yield redis

    return _dep


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


def _create_plain_user(db: Session, client: TestClient) -> dict[str, str]:
    user_in = UserCreate(
        username=random_lower_string()[:20],
        name="Import User",
        email=random_email(),
        password="testpassword123",
    )
    user = user_repository.create(session=db, obj_in=user_in)
    return user_authentication_headers(
        client=client,
        username=user.username,
        password="testpassword123",
    )


def test_create_data_import_rejects_missing_project(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    redis = FakeRedis()
    app.dependency_overrides[get_redis_client] = _override_redis(redis)
    try:
        response = client.post(
            f"{settings.API_V1_STR}/data-imports",
            headers=superuser_token_headers,
            json={"project_id": 999999},
        )
    finally:
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 404
    assert (
        response.json().get("detail") == "Project not found"
        or response.json().get("message") == "Project not found"
    )


def test_create_data_import_rejects_without_project_write(
    client: TestClient,
    db: Session,
) -> None:
    project = _create_project(db)
    headers = _create_plain_user(db, client)
    redis = FakeRedis()
    app.dependency_overrides[get_redis_client] = _override_redis(redis)
    try:
        response = client.post(
            f"{settings.API_V1_STR}/data-imports",
            headers=headers,
            json={"project_id": project.project_id},
        )
    finally:
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 403


def test_create_data_import_returns_batch_id(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    project = _create_project(db)
    redis = FakeRedis()
    app.dependency_overrides[get_redis_client] = _override_redis(redis)
    try:
        response = client.post(
            f"{settings.API_V1_STR}/data-imports",
            headers=superuser_token_headers,
            json={"project_id": project.project_id},
        )
    finally:
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["project_id"] == project.project_id
    assert payload["status"] == "uploading"
    assert len(payload["batch_id"]) == 36


def test_get_data_import_returns_status(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    project = _create_project(db)
    redis = FakeRedis()
    app.dependency_overrides[get_redis_client] = _override_redis(redis)
    try:
        create_response = client.post(
            f"{settings.API_V1_STR}/data-imports",
            headers=superuser_token_headers,
            json={"project_id": project.project_id},
        )
        batch_id = create_response.json()["data"]["batch_id"]

        response = client.get(
            f"{settings.API_V1_STR}/data-imports/{batch_id}",
            headers=superuser_token_headers,
        )
    finally:
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["batch_id"] == batch_id
    assert payload["project_id"] == project.project_id
    assert payload["status"] == "uploading"


def test_get_data_import_returns_queue_id_when_queued(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    project = _create_project(db)
    redis = FakeRedis()
    batch_id = "offline-batch"
    redis.store[f"offline-import:{batch_id}"] = (
        '{"batch_id":"offline-batch","project_id":%d,"uploader_id":1,'
        '"file_upload_id":22,"queue_id":33,"status":"queued","error":null,'
        '"summary_json":null,"cleanup_after":null,'
        '"creation_date":"2026-05-18 10:00:00","update_date":"2026-05-18 10:01:00"}'
    ) % project.project_id
    app.dependency_overrides[get_redis_client] = _override_redis(redis)
    try:
        response = client.get(
            f"{settings.API_V1_STR}/data-imports/{batch_id}",
            headers=superuser_token_headers,
        )
    finally:
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["queue_id"] == 33
    assert payload["file_upload_id"] == 22
    assert payload["status"] == "queued"
