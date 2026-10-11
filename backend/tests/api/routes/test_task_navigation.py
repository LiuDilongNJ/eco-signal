from datetime import timedelta

import pytest
from sqlmodel import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models import MediaCollection, Project, ProjectCollection, Task, User
from app.repositories.task_repository import task_repository


def query(client, setup, media, annotation=None, collection=None, headers=None, **overrides):
    params = {"project_id": setup.project.project_id, "media_id": media.media_id}
    if annotation is not None:
        params["annotation_id"] = annotation.annotation_id
    if collection is not None:
        params["collection_id"] = collection.collection_id
    params.update(overrides)
    return client.get(f"{settings.API_V1_STR}/tasks/navigation-items", params=params,
                      headers=setup.headers if headers is None else headers)


def allow(setup, collection=None):
    collection = collection or setup.first
    setup.grant("media:read", collection)
    setup.grant("annotation:read", collection)


def test_navigation_crosses_media_both_directions(client, navigation_setup):
    s = navigation_setup
    allow(s)
    audio, photo = s.media(), s.media(media_type="photo")
    a, b = s.annotation(audio), s.annotation(photo)
    s.task(a)
    target = s.task(b)
    result = query(client, s, audio, a).json()["data"]
    assert result["previous"] is None
    assert result["next"] == {"task_id": target.task_id, "project_id": s.project.project_id,
                              "collection_id": s.first.collection_id, "media_id": photo.media_id,
                              "media_type": "photo", "annotation_id": b.annotation_id}
    reverse = query(client, s, photo, b).json()["data"]
    assert reverse["previous"]["annotation_id"] == a.annotation_id
    assert reverse["next"] is None


def test_navigation_sorts_coordinates_before_annotation_id(client, navigation_setup):
    s = navigation_setup
    allow(s)
    media = s.media()
    later, earlier, higher = s.annotation(media, 10), s.annotation(media, 1), s.annotation(media, 1, 5)
    for a in (later, earlier, higher):
        s.task(a)
    result = query(client, s, media, higher).json()["data"]
    assert result["previous"]["annotation_id"] == earlier.annotation_id
    assert result["next"]["annotation_id"] == later.annotation_id


def test_navigation_excludes_reviewed_other_users_and_media_tasks(client, navigation_setup, db):
    s = navigation_setup
    allow(s)
    media = s.media()
    anchor = s.annotation(media)
    s.task(s.annotation(media, 1), status="reviewed")
    s.task(s.annotation(media, 2), assignee=s.other)
    db.add(Task(type="media", media_id=media.media_id, assigner_id=s.owner.user_id, assignee_id=s.owner.user_id, status="assigned"))
    target = s.annotation(media, 3)
    s.task(target)
    db.flush()
    response = query(client, s, media, anchor)
    assert response.status_code == 200
    assert response.json()["data"]["next"]["annotation_id"] == target.annotation_id


def test_navigation_reviewed_anchor_remains_usable(client, navigation_setup, db):
    s = navigation_setup
    allow(s)
    media = s.media()
    a, b = s.annotation(media), s.annotation(media, 1)
    s.task(a)
    s.task(b)
    task_repository.mark_annotation_task_reviewed(db, a.annotation_id, s.owner.user_id)
    assert query(client, s, media, a).json()["data"]["next"]["annotation_id"] == b.annotation_id
    assert query(client, s, media, b).json()["data"]["previous"] is None
    task_repository.mark_annotation_task_assigned(db, a.annotation_id, s.owner.user_id)
    assert query(client, s, media, b).json()["data"]["previous"]["annotation_id"] == a.annotation_id


def test_navigation_collection_scope_does_not_expand(client, navigation_setup):
    s = navigation_setup
    allow(s)
    allow(s, s.second)
    a, b = s.annotation(s.media()), s.annotation(s.media(s.second))
    s.task(b)
    media = type("Anchor", (), {"media_id": a.media_id})()
    assert query(client, s, media, a, s.first).json()["data"]["next"] is None
    assert query(client, s, media, a).json()["data"]["next"]["annotation_id"] == b.annotation_id


def test_navigation_filters_hidden_tasks_before_limit(client, navigation_setup):
    s = navigation_setup
    allow(s)
    media = s.media()
    anchor = s.annotation(media)
    hidden = s.annotation(s.media(s.second))
    target = s.annotation(s.media())
    s.task(hidden)
    s.task(target)
    assert query(client, s, media, anchor).json()["data"]["next"]["annotation_id"] == target.annotation_id


def test_navigation_cannot_combine_grants_across_paths(client, navigation_setup, db):
    s = navigation_setup
    allow(s)
    anchor_media = s.media()
    anchor = s.annotation(anchor_media)
    target_media = s.media(s.second)
    target = s.annotation(target_media)
    s.task(target)
    third = type(s.first)(name="Navigation third", creator_id=s.owner.user_id)
    db.add(third)
    db.flush()
    db.add(ProjectCollection(project_id=s.project.project_id, collection_id=third.collection_id))
    db.add(MediaCollection(media_id=target_media.media_id, collection_id=third.collection_id, added_by=s.owner.user_id))
    s.grant("media:read", s.second)
    s.grant("annotation:read", third)
    assert query(client, s, anchor_media, anchor).json()["data"]["next"] is None


@pytest.mark.parametrize("grant", ["project:write", "collection:write", "annotation:read_own", "public", "admin"])
def test_navigation_permission_modes(client, navigation_setup, db, grant):
    s = navigation_setup
    media = s.media()
    a, b = s.annotation(media), s.annotation(media, 1)
    headers = s.headers
    if grant == "public":
        s.project.public = True
        db.add(s.project)
        db.flush()
        s.first.public_access = s.first.public_tags = True
        db.add_all([s.project, s.first])
    elif grant == "admin":
        admin = db.exec(select(User).where(User.username == settings.FIRST_SUPERUSER)).one()
        headers = {"Authorization": f"Bearer {create_access_token(admin.user_id, timedelta(minutes=30))}"}
        s.task(b, assignee=admin)
        s.task(s.annotation(media, 0.5))
    elif grant == "project:write":
        s.grant(grant, collection=None)
    elif grant == "collection:write":
        s.grant(grant)
    else:
        s.grant("media:read")
        s.grant(grant)
        s.task(s.annotation(media, 0.5, creator=s.other))
    if grant != "admin":
        s.task(b)
    db.flush()
    response = query(client, s, media, a, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["next"]["annotation_id"] == b.annotation_id


def test_navigation_public_media_does_not_imply_public_annotations(client, navigation_setup, db):
    s = navigation_setup
    s.project.public = True
    db.add(s.project)
    db.flush()
    s.first.public_access = True
    db.add_all([s.project, s.first])
    media = s.media()
    a = s.annotation(media)
    s.task(a)
    response = query(client, s, media, a)
    assert response.status_code == 403


def test_navigation_scope_grants_do_not_cross_projects(client, navigation_setup, db):
    s = navigation_setup
    other = Project(name="Other navigation", url="https://other-navigation.example.com", creator_id=s.owner.user_id)
    db.add(other)
    db.flush()
    db.add(ProjectCollection(project_id=other.project_id, collection_id=s.first.collection_id))
    s.grant("collection:write", target_project=other)
    media = s.media()
    assert query(client, s, media).status_code == 403


def test_navigation_deduplicates_multiple_collection_paths(client, navigation_setup, db):
    s = navigation_setup
    allow(s)
    allow(s, s.second)
    media = s.media()
    db.add(MediaCollection(media_id=media.media_id, collection_id=s.second.collection_id, added_by=s.owner.user_id))
    a, b = s.annotation(media), s.annotation(media, 1)
    s.task(a)
    s.task(b)
    result = query(client, s, media, a).json()["data"]
    assert result["next"]["collection_id"] == min(s.first.collection_id, s.second.collection_id)
    assert query(client, s, media, b).json()["data"]["next"] is None


def test_navigation_without_selected_annotation_uses_media_start(client, navigation_setup):
    s = navigation_setup
    allow(s)
    earlier, current = s.media(), s.media()
    previous, next_ann = s.annotation(earlier), s.annotation(current)
    s.task(previous)
    s.task(next_ann)
    result = query(client, s, current).json()["data"]
    assert result["previous"]["annotation_id"] == previous.annotation_id
    assert result["next"]["annotation_id"] == next_ann.annotation_id


def test_navigation_empty_scope(client, navigation_setup):
    s = navigation_setup
    allow(s)
    assert query(client, s, s.media()).json()["data"] == {"previous": None, "next": None}


@pytest.mark.parametrize("field,value,status", [("media_id", 99999999, 404), ("annotation_id", 99999999, 404), ("project_id", 99999999, 400), ("media_id", 0, 422), ("annotation_id", -1, 422), ("project_id", "abc", 422)])
def test_navigation_invalid_anchor(client, navigation_setup, field, value, status):
    s = navigation_setup
    allow(s)
    media = s.media()
    assert query(client, s, media, **{field: value}).status_code == status


def test_navigation_annotation_media_mismatch(client, navigation_setup):
    s = navigation_setup
    allow(s)
    assert query(client, s, s.media(), s.annotation(s.media())).status_code == 400


def test_navigation_collection_project_mismatch(client, navigation_setup):
    s = navigation_setup
    media = s.media()
    assert query(client, s, media, s.annotation(media), s.first, project_id=99999999).status_code == 400


def test_navigation_requires_login(client):
    assert client.get(f"{settings.API_V1_STR}/tasks/navigation-items?project_id=1&media_id=1").status_code == 401
