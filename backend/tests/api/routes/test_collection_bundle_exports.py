from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import get_task_publisher
from app.core.config import settings
from app.enums import QueueStatus, WorkerTaskType
from app.main import app
from app.models import (
    Collection,
    CollectionBundleExport,
    Permission,
    Project,
    ProjectCollection,
    Queue,
    UserPermission,
)
from app.repositories import user_repository
from app.schemas import UserCreate
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


class FakePublisher:
    def __init__(self) -> None:
        self.enqueue_task = AsyncMock()


def _seed_scope(db: Session) -> tuple[Project, Collection]:
    suffix = uuid4().hex[:8]
    project = Project(
        name=f"Bundle Project {suffix}",
        url=f"https://bundle-{suffix}.example",
        creator_id=1,
    )
    collection = Collection(
        name=f"Bundle Collection {suffix}",
        creator_id=1,
    )
    db.add(project)
    db.add(collection)
    db.commit()
    db.refresh(project)
    db.refresh(collection)
    db.add(
        ProjectCollection(
            project_id=project.project_id,
            collection_id=collection.collection_id,
        )
    )
    db.commit()
    return project, collection


def _create_user_headers(
    db: Session,
    client: TestClient,
    *,
    project_id: int | None = None,
) -> dict[str, str]:
    password = "testpassword123"
    user = user_repository.create(
        session=db,
        obj_in=UserCreate(
            username=random_lower_string()[:20],
            name="Bundle User",
            email=random_email(),
            password=password,
        ),
    )
    if project_id is not None:
        permission = db.exec(
            select(Permission).where(Permission.name == "project:write")
        ).one()
        db.add(
            UserPermission(
                user_id=user.user_id,
                project_id=project_id,
                permission_id=permission.permission_id,
            )
        )
        db.commit()
    return user_authentication_headers(
        client=client,
        username=user.username,
        password=password,
    )


def test_create_collection_bundle_export_queues_worker(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    project, collection = _seed_scope(db)
    publisher = FakePublisher()
    async def override_publisher():
        yield publisher

    app.dependency_overrides[get_task_publisher] = override_publisher
    try:
        response = client.post(
            f"{settings.API_V1_STR}/collection-bundle-exports",
            headers=superuser_token_headers,
            json={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
            },
        )
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "queued"
    assert payload["project_id"] == project.project_id
    assert payload["collection_id"] == collection.collection_id
    publisher.enqueue_task.assert_awaited_once()
    args = publisher.enqueue_task.await_args
    assert args.args[0] == WorkerTaskType.EXPORT_COLLECTION_BUNDLE
    assert args.kwargs["export_id"] == payload["export_id"]
    assert args.kwargs["queue_id"] == payload["queue_id"]


def test_create_collection_bundle_export_rejects_project_mismatch(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    project, _ = _seed_scope(db)
    _, other_collection = _seed_scope(db)

    response = client.post(
        f"{settings.API_V1_STR}/collection-bundle-exports",
        headers=superuser_token_headers,
        json={
            "project_id": project.project_id,
            "collection_id": other_collection.collection_id,
        },
    )

    assert response.status_code == 400
    assert response.json()["message"] == "collection_id does not belong to the given project_id"


def test_create_collection_bundle_export_requires_project_write(
    client: TestClient,
    db: Session,
) -> None:
    project, collection = _seed_scope(db)
    headers = _create_user_headers(db, client)

    response = client.post(
        f"{settings.API_V1_STR}/collection-bundle-exports",
        headers=headers,
        json={
            "project_id": project.project_id,
            "collection_id": collection.collection_id,
        },
    )

    assert response.status_code == 403


def test_collection_bundle_export_rejects_other_user(
    client: TestClient,
    db: Session,
) -> None:
    project, collection = _seed_scope(db)
    owner_headers = _create_user_headers(db, client, project_id=project.project_id)
    other_headers = _create_user_headers(db, client, project_id=project.project_id)
    publisher = FakePublisher()

    async def override_publisher():
        yield publisher

    app.dependency_overrides[get_task_publisher] = override_publisher
    try:
        created = client.post(
            f"{settings.API_V1_STR}/collection-bundle-exports",
            headers=owner_headers,
            json={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
            },
        )
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)

    response = client.get(
        f"{settings.API_V1_STR}/collection-bundle-exports/{created.json()['data']['export_id']}",
        headers=other_headers,
    )
    assert response.status_code == 403


def test_collection_bundle_export_download(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch,
    tmp_path: Path,
) -> None:
    project, collection = _seed_scope(db)
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
    queue = Queue(
        type="offline_export",
        user_id=1,
        total=1,
        completed=1,
        status=QueueStatus.COMPLETED,
    )
    db.add(queue)
    db.commit()
    db.refresh(queue)
    relative_path = Path("offline_exports") / "1" / "ready.zip"
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"bundle-content")
    record = CollectionBundleExport(
        project_id=project.project_id,
        collection_id=collection.collection_id,
        user_id=1,
        queue_id=queue.queue_id,
        status="completed",
        filename="collection.zip",
        path=relative_path.as_posix(),
        size_b=target.stat().st_size,
        creation_date=datetime.now(UTC).replace(tzinfo=None),
        completion_date=datetime.now(UTC).replace(tzinfo=None),
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    response = client.get(
        f"{settings.API_V1_STR}/collection-bundle-exports/{record.export_id}/file",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.content == b"bundle-content"
    assert response.headers["content-type"] == "application/zip"


def test_collection_bundle_export_expired_download_returns_gone(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch,
    tmp_path: Path,
) -> None:
    project, collection = _seed_scope(db)
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
    queue = Queue(type="offline_export", user_id=1, total=1, status=QueueStatus.COMPLETED)
    db.add(queue)
    db.commit()
    db.refresh(queue)
    target = tmp_path / "offline_exports" / "expired.zip"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"expired")
    record = CollectionBundleExport(
        project_id=project.project_id,
        collection_id=collection.collection_id,
        user_id=1,
        queue_id=queue.queue_id,
        status="completed",
        filename="expired.zip",
        path="offline_exports/expired.zip",
        creation_date=datetime.now(UTC).replace(tzinfo=None),
        expires_at=(datetime.now(UTC) - timedelta(minutes=1)).replace(tzinfo=None),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    response = client.get(
        f"{settings.API_V1_STR}/collection-bundle-exports/{record.export_id}/file",
        headers=superuser_token_headers,
    )

    assert response.status_code == 410
    assert not target.exists()
