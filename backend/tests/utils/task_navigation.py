from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import select

from app.core.security import create_access_token
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
from app.models.annotation import Annotation
from app.models.media import PhotoSetting
from app.models.permission import Permission, UserPermission


@pytest.fixture
def navigation_setup(db):
    role = Role(name="Navigation member")
    db.add(role)
    db.flush()
    owner = User(username="nav-owner", name="Navigation owner", email="nav-owner@example.com", role_id=role.role_id, password="unused")
    other = User(username="nav-other", name="Navigation colleague", email="nav-other@example.com", role_id=role.role_id, password="unused")
    db.add_all([owner, other])
    db.flush()
    project = Project(name="Navigation project", url="https://navigation.example.com", creator_id=owner.user_id, public=False)
    first = Collection(name="Navigation first", creator_id=owner.user_id, public_access=False, public_tags=False)
    second = Collection(name="Navigation second", creator_id=owner.user_id, public_access=False, public_tags=False)
    db.add_all([project, first, second])
    db.flush()
    for collection in (first, second):
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
    db.flush()

    def media(collection=first, media_type="audio"):
        item = Media(filename=f"navigation.{media_type}", media_type=media_type, is_metadata=True, creator_id=owner.user_id, uploader_id=owner.user_id)
        if media_type == "photo":
            setting = PhotoSetting()
            db.add(setting)
            db.flush()
            item.photo_setting_id = setting.photo_setting_id
        db.add(item)
        db.flush()
        db.add(MediaCollection(media_id=item.media_id, collection_id=collection.collection_id, added_by=owner.user_id))
        db.flush()
        return item

    def annotation(item, x=0, y=0, creator=owner):
        result = Annotation(media_id=item.media_id, creator_id=creator.user_id, min_x=x, max_x=x+1, min_y=y, max_y=y+1)
        db.add(result)
        db.flush()
        return result

    def task(ann, assignee=owner, status="assigned"):
        result = Task(type="annotation", media_id=ann.media_id, annotation_id=ann.annotation_id, assigner_id=owner.user_id, assignee_id=assignee.user_id, status=status)
        db.add(result)
        db.flush()
        return result

    def grant(name, collection=first, target_project=project):
        permission = db.exec(select(Permission).where(Permission.name == name)).one()
        db.add(UserPermission(user_id=owner.user_id, permission_id=permission.permission_id,
                              project_id=target_project.project_id,
                              collection_id=collection.collection_id if collection is not None else None))
        db.flush()

    return SimpleNamespace(owner=owner, other=other, project=project, first=first, second=second,
                           media=media, annotation=annotation, task=task, grant=grant,
                           headers={"Authorization": f"Bearer {create_access_token(owner.user_id, timedelta(minutes=30))}"})
