"""Unit tests for TaskRepository task-list filters."""

from datetime import UTC, datetime

import pytest
from sqlmodel import Session

from app.models import (
    Collection,
    Media,
    MediaCollection,
    Project,
    ProjectCollection,
    Role,
    Task,
    User,
)
from app.repositories.task_repository import task_repository


@pytest.fixture
def task_setup(db: Session):
    role = Role(name="Task Repo Role")
    db.add(role)
    db.flush()
    owner = _user(db, role.role_id, "task_repo_owner", "Task Repo Owner")

    project = Project(
        name="Task Repo Project",
        url="https://task-repo.test",
        creator_id=owner.user_id,
    )
    collection = Collection(name="Task Repo Collection", creator_id=owner.user_id)
    db.add_all([project, collection])
    db.flush()
    db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
    db.flush()

    return {"role": role, "owner": owner, "project": project, "collection": collection}


def _user(db: Session, role_id: int, username: str, name: str) -> User:
    user = User(
        username=username,
        name=name,
        email=f"{username}@example.com",
        role_id=role_id,
        password="hashed_password",
    )
    db.add(user)
    db.flush()
    return user


def _media(db: Session, collection_id: int, creator_id: int, filename: str) -> Media:
    media = Media(filename=filename, media_type="audio", is_metadata=True, creator_id=creator_id)
    db.add(media)
    db.flush()
    db.add(
        MediaCollection(
            media_id=media.media_id,
            collection_id=collection_id,
            added_by=creator_id,
        )
    )
    db.flush()
    return media


def _task(
    db: Session,
    *,
    media_id: int,
    assigner_id: int,
    assignee_id: int,
    status: str = "assigned",
) -> Task:
    task = Task(
        type="media",
        media_id=media_id,
        assigner_id=assigner_id,
        assignee_id=assignee_id,
        status=status,
        datetime=datetime.now(UTC),
    )
    db.add(task)
    db.flush()
    return task


class TestTaskRepository:

    def test_get_task_list_person_id_filters_are_exact_for_same_names(
        self, db: Session, task_setup
    ):
        role = task_setup["role"]
        collection = task_setup["collection"]

        assigner_one = _user(db, role.role_id, "same_assigner_one", "Same Name")
        assigner_two = _user(db, role.role_id, "same_assigner_two", "Same Name")
        assignee_one = _user(db, role.role_id, "same_assignee_one", "Worker")
        assignee_two = _user(db, role.role_id, "same_assignee_two", "Worker")
        media_one = _media(db, collection.collection_id, assigner_one.user_id, "selected-task.wav")
        media_two = _media(db, collection.collection_id, assigner_two.user_id, "other-task.wav")
        selected = _task(
            db,
            media_id=media_one.media_id,
            assigner_id=assigner_one.user_id,
            assignee_id=assignee_one.user_id,
        )
        _task(
            db,
            media_id=media_two.media_id,
            assigner_id=assigner_two.user_id,
            assignee_id=assignee_two.user_id,
        )
        db.commit()

        total, rows = task_repository.list_tasks(
            db,
            user_id=assigner_one.user_id,
            is_admin=True,
            accessible_collection_ids=None,
            assigner_id=assigner_one.user_id,
            assignee_id=assignee_one.user_id,
        )

        assert total == 1
        assert [row["task_id"] for row in rows] == [selected.task_id]


    def test_get_task_list_supports_fuzzy_type_alias_and_status(
        self, db: Session, task_setup
    ):
        role = task_setup["role"]
        collection = task_setup["collection"]

        assigner = _user(db, role.role_id, "type_alias_assigner", "Type Alias Assigner")
        assignee = _user(db, role.role_id, "type_alias_assignee", "Type Alias Assignee")
        media = _media(db, collection.collection_id, assigner.user_id, "type-alias.wav")
        selected = _task(
            db,
            media_id=media.media_id,
            assigner_id=assigner.user_id,
            assignee_id=assignee.user_id,
            status="reviewed",
        )
        db.commit()

        total, rows = task_repository.list_tasks(
            db,
            user_id=assigner.user_id,
            is_admin=True,
            accessible_collection_ids=None,
            type="media",
            status="review",
        )

        assert total == 1
        assert [row["task_id"] for row in rows] == [selected.task_id]
