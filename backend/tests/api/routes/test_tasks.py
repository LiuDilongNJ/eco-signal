"""
Tests for Task Assignment API routes.

Covers:
- GET /media/{media_id}/task-assignee-options
- GET /media/{media_id}/tasks
- PUT /media/{media_id}/tasks
"""
import csv
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Collection, Project, ProjectCollection, Role, Task, User
from app.models.media import AudioSetting, Media, MediaCollection, PhotoSetting


# Helpers

def _create_media_with_collection(db: Session) -> tuple[Media, Collection]:
    """Create a Media record linked to a public Collection."""
    user = db.exec(select(User)).first()

    col = Collection(
        name="Task Test Collection",
        public_access=True,
        creator_id=user.user_id,
    )
    db.add(col)
    db.flush()

    audio = AudioSetting(sampling_rate_hz=44100, duration_s=10.0)
    db.add(audio)
    db.flush()

    media = Media(
        media_type="audio",
        filename="task_test.wav",
        uploader_id=user.user_id,
        audio_setting_id=audio.audio_setting_id,
    )
    db.add(media)
    db.flush()

    mc = MediaCollection(
        media_id=media.media_id,
        collection_id=col.collection_id,
        added_by=user.user_id,
    )
    db.add(mc)
    db.commit()
    db.refresh(media)
    db.refresh(col)
    return media, col


def _create_project_for_collection(db: Session, collection: Collection) -> Project:
    """Create a project and link the supplied collection to it."""
    project = Project(
        name=f"Task Test Project {collection.collection_id}",
        url=f"https://tasks-{collection.collection_id}.example.com",
        creator_id=collection.creator_id,
    )
    db.add(project)
    db.flush()
    db.add(
        ProjectCollection(
            project_id=project.project_id,
            collection_id=collection.collection_id,
        )
    )
    db.commit()
    db.refresh(project)
    return project


def _create_task(
    db: Session,
    media_id: int,
    assigner_id: int,
    assignee_id: int,
    comment: str = "",
) -> Task:
    """Create a Task record directly in the DB."""
    task = Task(
        type="media",
        media_id=media_id,
        assigner_id=assigner_id,
        assignee_id=assignee_id,
        status="assigned",
        comment=comment,
        datetime=datetime.now(timezone.utc),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _create_user(db: Session, role_id: int, username: str, name: str) -> User:
    """Create a user for task route tests."""
    user = User(
        username=username,
        name=name,
        email=f"{username}@example.com",
        role_id=role_id,
        password="hashed_password",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# GET /media/{media_id}/task-assignee-options

class TestAssignableUsers:
    """Tests for getting assignable users for a media."""

    def test_requires_auth(self, client: TestClient) -> None:
        """Endpoint requires authentication."""
        r = client.get(f"{settings.API_V1_STR}/media/1/task-assignee-options")
        assert r.status_code == 401

    def test_media_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Return 404 when media does not exist."""
        r = client.get(
            f"{settings.API_V1_STR}/media/999999/task-assignee-options?project_id=1",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404

    def test_admin_can_get_assignable_users(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can retrieve the assignable user list."""
        media, _ = _create_media_with_collection(db)

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/task-assignee-options?project_id=1",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert isinstance(data, list)
        # Each item must have required fields
        for item in data:
            assert "user_id" in item
            assert "username" in item
            assert "task_count" in item

    def test_task_count_reflects_existing_tasks(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """task_count is non-zero for users already assigned to this media."""
        media, _ = _create_media_with_collection(db)
        admin = db.exec(select(User).where(User.role_id == 1)).first()

        # Assign admin to media
        _create_task(db, media.media_id, admin.user_id, admin.user_id, "pre-existing")

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/task-assignee-options?project_id=1",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        admin_entry = next((u for u in data if u["user_id"] == admin.user_id), None)
        assert admin_entry is not None
        assert admin_entry["task_count"] >= 1


# GET /media/{media_id}/tasks

class TestGetMediaTasks:
    """Tests for listing tasks assigned to a media."""

    def test_requires_auth(self, client: TestClient) -> None:
        """Endpoint requires authentication."""
        r = client.get(f"{settings.API_V1_STR}/media/1/tasks")
        assert r.status_code == 401

    def test_media_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Return 404 when media does not exist."""
        r = client.get(
            f"{settings.API_V1_STR}/media/999999/tasks?project_id=1",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404

    def test_empty_task_list(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Return empty list when no tasks exist for this media."""
        media, _ = _create_media_with_collection(db)

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/tasks?project_id=1",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.json()["data"] == []

    def test_returns_existing_tasks(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Return tasks with assigner/assignee name info."""
        media, _ = _create_media_with_collection(db)
        admin = db.exec(select(User).where(User.role_id == 1)).first()

        task = _create_task(db, media.media_id, admin.user_id, admin.user_id, "check this")

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/tasks?project_id=1",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        t = data[0]
        assert t["task_id"] == task.task_id
        assert t["media_id"] == media.media_id
        assert t["comment"] == "check this"
        assert t["status"] == "assigned"
        assert "assigner_name" in t
        assert "assignee_name" in t


class TestTasksList:
    """Tests for GET /tasks list filters."""

    def test_filters_by_assigner_and_assignee_id_exactly(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        role = Role(name="Task Route Role")
        db.add(role)
        db.commit()
        db.refresh(role)
        assigner_one = _create_user(db, role.role_id, "route_assigner_one", "Same Name")
        assigner_two = _create_user(db, role.role_id, "route_assigner_two", "Same Name")
        assignee_one = _create_user(db, role.role_id, "route_assignee_one", "Worker")
        assignee_two = _create_user(db, role.role_id, "route_assignee_two", "Worker")
        media_one, _ = _create_media_with_collection(db)
        media_two, _ = _create_media_with_collection(db)
        selected = _create_task(
            db,
            media_one.media_id,
            assigner_one.user_id,
            assignee_one.user_id,
            "selected",
        )
        _create_task(
            db,
            media_two.media_id,
            assigner_two.user_id,
            assignee_two.user_id,
            "other",
        )

        response = client.get(
            f"{settings.API_V1_STR}/tasks?assigner_id={assigner_one.user_id}&assignee_id={assignee_one.user_id}",
            headers=superuser_token_headers,
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["page_info"]["total"] == 1
        assert [item["task_id"] for item in payload["data"]] == [selected.task_id]


# PUT /media/{media_id}/tasks

class TestAssignTasks:
    """Tests for the batch assign endpoint."""

    def test_requires_auth(self, client: TestClient) -> None:
        """Endpoint requires authentication."""
        r = client.put(
            f"{settings.API_V1_STR}/media/1/tasks",
            json={"type": "media", "assignments": [{"user_id": 1}]},
        )
        assert r.status_code == 401

    def test_media_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Return 404 when media does not exist."""
        r = client.put(
            f"{settings.API_V1_STR}/media/999999/tasks?project_id=1",
            headers=superuser_token_headers,
            json={"type": "media", "assignments": [{"user_id": 1}]},
        )
        assert r.status_code == 404

    def test_empty_assignments_rejected(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Return 400 when assignments list is empty."""
        media, _ = _create_media_with_collection(db)
        r = client.put(
            f"{settings.API_V1_STR}/media/{media.media_id}/tasks?project_id=1",
            headers=superuser_token_headers,
            json={"type": "media", "assignments": []},
        )
        assert r.status_code == 422

    def test_create_new_assignments(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Successfully create new task assignments."""
        media, _ = _create_media_with_collection(db)
        admin = db.exec(select(User).where(User.role_id == 1)).first()

        r = client.put(
            f"{settings.API_V1_STR}/media/{media.media_id}/tasks?project_id=1",
            headers=superuser_token_headers,
            json={
                "type": "media",
                "assignments": [
                    {"user_id": admin.user_id, "comment": "Please review"}
                ],
            },
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["assigned_count"] == 1

        # Verify in DB
        task = db.exec(
            select(Task).where(
                Task.media_id == media.media_id,
                Task.assignee_id == admin.user_id,
            )
        ).first()
        assert task is not None
        assert task.comment == "Please review"
        assert task.status == "assigned"

    def test_upsert_updates_existing_task(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Re-assigning the same user updates comment instead of creating duplicate."""
        media, _ = _create_media_with_collection(db)
        admin = db.exec(select(User).where(User.role_id == 1)).first()

        # Pre-create a task
        _create_task(db, media.media_id, admin.user_id, admin.user_id, "old comment")

        # Re-assign with new comment
        r = client.put(
            f"{settings.API_V1_STR}/media/{media.media_id}/tasks?project_id=1",
            headers=superuser_token_headers,
            json={
                "type": "media",
                "assignments": [
                    {"user_id": admin.user_id, "comment": "updated comment"}
                ],
            },
        )
        assert r.status_code == 200

        # Should still be only 1 task
        tasks = db.exec(
            select(Task).where(
                Task.media_id == media.media_id,
                Task.assignee_id == admin.user_id,
            )
        ).all()
        assert len(tasks) == 1
        assert tasks[0].comment == "updated comment"

    def test_assign_multiple_users(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Assign the same media to multiple users at once."""
        media, _ = _create_media_with_collection(db)
        users = db.exec(select(User)).all()
        if len(users) < 2:
            # Need at least 2 users for this test
            return

        assignments = [
            {"user_id": u.user_id, "comment": f"Task for {u.username}"}
            for u in users[:2]
        ]

        r = client.put(
            f"{settings.API_V1_STR}/media/{media.media_id}/tasks?project_id=1",
            headers=superuser_token_headers,
            json={"type": "media", "assignments": assignments},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["assigned_count"] == 2

    def test_unknown_assignee_rejected(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        media, _ = _create_media_with_collection(db)

        response = client.put(
            f"{settings.API_V1_STR}/media/{media.media_id}/tasks?project_id=1",
            headers=superuser_token_headers,
            json={"type": "media", "assignments": [{"user_id": 999999}]},
        )

        assert response.status_code == 404
        assert response.json()["message"] == "Assignee not found"


# GET /tasks/ (List & Export) and Detail/Delete

class TestTaskManagementAPI:
    def test_list_requires_auth(self, client: TestClient) -> None:
        r = client.get(f"{settings.API_V1_STR}/tasks")
        assert r.status_code == 401

    def test_admin_gets_all_tasks(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        media, _ = _create_media_with_collection(db)
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        _create_task(db, media.media_id, admin.user_id, admin.user_id, "admin check general")

        r = client.get(
            f"{settings.API_V1_STR}/tasks",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        items = r.json()["data"]
        assert len(items) >= 1
        assert "media_name" in items[0]
        assert items[0]["media_type"] == "audio"
        assert items[0]["comment"] is not None

    def test_list_filters_and_orders_by_media_type(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        audio, collection = _create_media_with_collection(db)
        project = _create_project_for_collection(db, collection)
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        photo_setting = PhotoSetting()
        db.add(photo_setting)
        db.flush()
        photo = Media(
            media_type="photo",
            filename="task-photo.png",
            name="task-photo.png",
            uploader_id=admin.user_id,
            photo_setting_id=photo_setting.photo_setting_id,
        )
        db.add(photo)
        db.flush()
        db.add(MediaCollection(media_id=photo.media_id, collection_id=collection.collection_id, added_by=admin.user_id))
        _create_task(db, audio.media_id, admin.user_id, admin.user_id, "audio task")
        db.commit()
        _create_task(db, photo.media_id, admin.user_id, admin.user_id, "photo task")

        response = client.get(
            f"{settings.API_V1_STR}/tasks",
            params={"project_id": project.project_id, "media_type": "photo", "order_by": "media_type"},
            headers=superuser_token_headers,
        )

        assert response.status_code == 200
        assert response.json()["page_info"]["total"] == 1
        assert [item["media_type"] for item in response.json()["data"]] == ["photo"]

        ordered = client.get(
            f"{settings.API_V1_STR}/tasks",
            params={"project_id": project.project_id, "order_by": "media_type", "order_dir": "desc"},
            headers=superuser_token_headers,
        )
        assert [item["media_type"] for item in ordered.json()["data"]] == ["photo", "audio"]

    def test_export_tasks(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        media, collection = _create_media_with_collection(db)
        project = _create_project_for_collection(db, collection)
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        task = _create_task(db, media.media_id, admin.user_id, admin.user_id, "export check")

        r = client.get(
            f"{settings.API_V1_STR}/tasks/exports",
            headers=superuser_token_headers,
            params={"project_id": project.project_id},
        )
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        assert r.headers.get("content-disposition") == (
            'attachment; filename="tasks.csv"; '
            "filename*=UTF-8''tasks.csv"
        )

        content = r.text
        header = next(csv.reader([content.splitlines()[0].lstrip("\ufeff")]))
        assert header == [
            "task_id", "type", "media_name", "media_type", "annotation_id",
            "assigner_name", "assigner_id", "assignee_name", "assignee_id", "status",
            "comment", "creation_date",
        ]
        assert str(task.task_id) in content
        assert "export check" in content

    def test_export_tasks_requires_project_id(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        r = client.get(
            f"{settings.API_V1_STR}/tasks/exports",
            headers=superuser_token_headers,
        )

        assert r.status_code == 422

    def test_export_tasks_rejects_invalid_order_direction(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        r = client.get(
            f"{settings.API_V1_STR}/tasks/exports",
            headers=superuser_token_headers,
            params={"project_id": 1, "order_dir": "sideways"},
        )

        assert r.status_code == 422

    def test_export_tasks_filters_by_project(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        selected_media, selected_collection = _create_media_with_collection(db)
        selected_project = _create_project_for_collection(db, selected_collection)
        other_media, other_collection = _create_media_with_collection(db)
        _create_project_for_collection(db, other_collection)
        _create_task(db, selected_media.media_id, admin.user_id, admin.user_id, "selected project task")
        _create_task(db, other_media.media_id, admin.user_id, admin.user_id, "other project task")

        r = client.get(
            f"{settings.API_V1_STR}/tasks/exports",
            headers=superuser_token_headers,
            params={"project_id": selected_project.project_id},
        )

        assert r.status_code == 200
        assert "selected project task" in r.text
        assert "other project task" not in r.text

    def test_export_tasks_filters_by_collection(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        selected_media, selected_collection = _create_media_with_collection(db)
        project = _create_project_for_collection(db, selected_collection)
        other_media, other_collection = _create_media_with_collection(db)
        db.add(
            ProjectCollection(
                project_id=project.project_id,
                collection_id=other_collection.collection_id,
            )
        )
        db.commit()
        _create_task(db, selected_media.media_id, admin.user_id, admin.user_id, "selected collection task")
        _create_task(db, other_media.media_id, admin.user_id, admin.user_id, "other collection task")

        r = client.get(
            f"{settings.API_V1_STR}/tasks/exports",
            headers=superuser_token_headers,
            params={
                "project_id": project.project_id,
                "collection_id": selected_collection.collection_id,
            },
        )

        assert r.status_code == 200
        assert "selected collection task" in r.text
        assert "other collection task" not in r.text

    def test_export_tasks_rejects_collection_from_another_project(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        _, selected_collection = _create_media_with_collection(db)
        selected_project = _create_project_for_collection(db, selected_collection)
        _, other_collection = _create_media_with_collection(db)
        _create_project_for_collection(db, other_collection)

        r = client.get(
            f"{settings.API_V1_STR}/tasks/exports",
            headers=superuser_token_headers,
            params={
                "project_id": selected_project.project_id,
                "collection_id": other_collection.collection_id,
            },
        )

        assert r.status_code == 400
        assert r.json()["message"] == "collection_id does not belong to the given project_id"

    def test_export_tasks_regular_user_is_limited_to_visible_tasks(
        self,
        client: TestClient,
        normal_user_token_headers: dict,
        db: Session,
    ) -> None:
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        normal_user = db.exec(
            select(User).where(User.email == settings.EMAIL_TEST_USER)
        ).first()
        visible_media, visible_collection = _create_media_with_collection(db)
        project = _create_project_for_collection(db, visible_collection)
        hidden_media, hidden_collection = _create_media_with_collection(db)
        db.add(
            ProjectCollection(
                project_id=project.project_id,
                collection_id=hidden_collection.collection_id,
            )
        )
        db.commit()
        _create_task(db, visible_media.media_id, admin.user_id, normal_user.user_id, "visible assigned task")
        _create_task(db, hidden_media.media_id, admin.user_id, admin.user_id, "hidden unassigned task")

        r = client.get(
            f"{settings.API_V1_STR}/tasks/exports",
            headers=normal_user_token_headers,
            params={"project_id": project.project_id},
        )

        assert r.status_code == 200
        assert "visible assigned task" in r.text
        assert "hidden unassigned task" not in r.text

    def test_get_task_detail(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        media, _ = _create_media_with_collection(db)
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        task = _create_task(db, media.media_id, admin.user_id, admin.user_id, "detail check")

        r = client.get(
            f"{settings.API_V1_STR}/tasks/{task.task_id}?project_id=1",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["task_id"] == task.task_id
        assert data["comment"] == "detail check"

    def test_delete_task_by_admin(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        media, _ = _create_media_with_collection(db)
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        task = _create_task(db, media.media_id, admin.user_id, admin.user_id, "delete check")

        r = client.delete(
            f"{settings.API_V1_STR}/tasks/{task.task_id}?project_id=1",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200

        # Verify deletion
        task_in_db = db.get(Task, task.task_id)
        assert task_in_db is None

    def test_normal_user_cannot_delete_unless_assigner(self, client: TestClient, normal_user_token_headers: dict, db: Session) -> None:
        media, _ = _create_media_with_collection(db)
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        task = _create_task(db, media.media_id, admin.user_id, admin.user_id, "normal user delete check")
        
        r = client.delete(
            f"{settings.API_V1_STR}/tasks/{task.task_id}?project_id=1",
            headers=normal_user_token_headers,
        )
        # Assuming normal user doesn't have assigner status for this task
        assert r.status_code in [403, 404]


class TestTaskImports:
    def _import_tasks(
        self,
        client: TestClient,
        headers: dict,
        project_id: int,
        collection_id: int,
        csv_text: str,
        *,
        dry_run: bool,
    ):
        return client.post(
            f"{settings.API_V1_STR}/tasks/imports",
            headers=headers,
            data={
                "project_id": str(project_id),
                "collection_id": str(collection_id),
                "dry_run": "true" if dry_run else "false",
            },
            files={"file": ("tasks.csv", csv_text.encode(), "text/csv")},
        )

    def test_unknown_assignee_fails_dry_run(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        media, collection = _create_media_with_collection(db)
        project = _create_project_for_collection(db, collection)
        csv_text = (
            "media_id,type,annotation_id,assignee_id,comment\n"
            f"{media.media_id},media,,999999,Review this recording\n"
        )

        response = self._import_tasks(
            client,
            superuser_token_headers,
            project.project_id,
            collection.collection_id,
            csv_text,
            dry_run=True,
        )

        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["failed"] == 1
        assert payload["committed"] is False
        assert payload["rows"][0]["reason"] == "Assignee not found"

    def test_two_assignees_same_media_dry_run_then_commit(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        media, collection = _create_media_with_collection(db)
        project = _create_project_for_collection(db, collection)
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        assignee_a = _create_user(db, admin.role_id, "task_import_a", "Import A")
        assignee_b = _create_user(db, admin.role_id, "task_import_b", "Import B")
        csv_text = (
            "media_id,type,annotation_id,assignee_id,comment\n"
            f"{media.media_id},media,,{assignee_a.user_id},Review this recording\n"
            f"{media.media_id},media,,{assignee_b.user_id},Review this recording too\n"
        )

        validation = self._import_tasks(
            client,
            superuser_token_headers,
            project.project_id,
            collection.collection_id,
            csv_text,
            dry_run=True,
        )
        assert validation.status_code == 200
        assert validation.json()["data"]["failed"] == 0
        assert validation.json()["data"]["succeeded"] == 2

        committed = self._import_tasks(
            client,
            superuser_token_headers,
            project.project_id,
            collection.collection_id,
            csv_text,
            dry_run=False,
        )
        assert committed.status_code == 200
        payload = committed.json()["data"]
        assert payload["committed"] is True
        assert payload["succeeded"] == 2
        assert payload["failed"] == 0

        tasks = db.exec(select(Task).where(Task.media_id == media.media_id)).all()
        assert {task.assignee_id for task in tasks} == {assignee_a.user_id, assignee_b.user_id}
