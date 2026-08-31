"""
Test cases for user API routes.
"""
import csv
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import or_
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import verify_password
from app.models import Permission, User, UserPermission, UserPreference
from app.models.annotation import Annotation, AnnotationReview, AnnotationReviewStatus
from app.models.collection import Collection, CollectionContributor
from app.models.media import Media
from app.models.project import Project, ProjectCollection, ProjectContributor
from app.models.system import FileUpload
from app.models.task import Task
from app.models.taxon import SoundClassification
from app.repositories.user_repository import user_repository
from app.schemas import UserCreate
from tests.utils.csv import read_csv_dict_rows, read_csv_header
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _normal_test_user_id(db: Session) -> int:
    u = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).one()
    return u.user_id


def _superuser_id(db: Session) -> int:
    u = db.exec(select(User).where(User.username == settings.FIRST_SUPERUSER)).one()
    return u.user_id


def create_test_user(db: Session, **kwargs) -> User:
    defaults = {
        "username": random_lower_string()[:20],
        "name": "Test User",
        "email": random_email(),
        "password": random_lower_string(),
    }
    defaults.update(kwargs)
    user_in = UserCreate(**defaults)
    return user_repository.create(session=db, obj_in=user_in)


def _permission(db: Session, resource_type: str, action: str) -> Permission:
    return db.exec(select(Permission).where(
        Permission.resource_type == resource_type,
        Permission.action == action,
    )).one()


def _grant_permission(
    db: Session,
    user: User,
    resource_type: str,
    action: str,
    *,
    project_id: int,
    collection_id: int | None = None,
) -> None:
    permission = _permission(db, resource_type, action)
    db.add(UserPermission(
        user_id=user.user_id,
        project_id=project_id,
        collection_id=collection_id,
        permission_id=permission.permission_id,
    ))
    db.commit()


def _create_project_with_collection(
    db: Session,
    owner: User,
    *,
    project_name: str,
    collection_name: str,
) -> tuple[Project, Collection]:
    project = Project(
        name=project_name,
        url=f"http://{random_lower_string()}.test",
        creator_id=owner.user_id,
    )
    collection = Collection(name=collection_name, creator_id=owner.user_id)
    db.add(project)
    db.add(collection)
    db.commit()
    db.refresh(project)
    db.refresh(collection)
    db.add(ProjectCollection(
        project_id=project.project_id,
        collection_id=collection.collection_id,
    ))
    db.commit()
    return project, collection


def test_get_users_superuser_me(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(f"{settings.API_V1_STR}/current-user", headers=superuser_token_headers)
    json_resp = r.json()
    assert json_resp["code"] == 0
    current_user = json_resp["data"]
    assert current_user
    assert current_user["active"] is True
    assert current_user["username"] == settings.FIRST_SUPERUSER
    assert current_user["color"] == "#FFFFFF"
    assert current_user["is_admin"] is True
    assert current_user["is_project_admin"] is True


def test_get_users_normal_user_me(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.get(f"{settings.API_V1_STR}/current-user", headers=normal_user_token_headers)
    json_resp = r.json()
    assert json_resp["code"] == 0
    current_user = json_resp["data"]
    assert current_user
    assert current_user["active"] is True
    assert current_user["email"] == settings.EMAIL_TEST_USER
    assert current_user["is_admin"] is False
    assert current_user["is_project_admin"] is False


def test_creator_options_include_all_system_administrators_for_project_manager(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    manager = db.get(User, _normal_test_user_id(db))
    assert manager is not None
    owner = create_test_user(db)
    project, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Creator Options Project",
        collection_name="Creator Options Collection",
    )
    _grant_permission(db, manager, "project", "write", project_id=project.project_id)

    response = client.get(
        f"{settings.API_V1_STR}/users/creators?project_id={project.project_id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    options = response.json()["data"]
    assert all(set(option) == {"user_id", "name", "username", "is_admin"} for option in options)
    assert any(option["is_admin"] for option in options)


def test_creator_options_reject_unreachable_project(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    owner = create_test_user(db)
    project, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Creator Options Private Project",
        collection_name="Creator Options Private Collection",
    )

    response = client.get(
        f"{settings.API_V1_STR}/users/creators?project_id={project.project_id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 403


def test_creator_options_require_audio_write_in_requested_project(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.get(User, _normal_test_user_id(db))
    assert user is not None
    owner = create_test_user(db)
    readable_project, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Creator Read Only Project",
        collection_name="Creator Read Only Collection",
    )
    writable_project, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Creator Other Writable Project",
        collection_name="Creator Other Writable Collection",
    )
    _grant_permission(db, user, "audio", "read", project_id=readable_project.project_id)
    _grant_permission(db, user, "audio", "write", project_id=writable_project.project_id)

    response = client.get(
        f"{settings.API_V1_STR}/users/creators?project_id={readable_project.project_id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 403
    assert response.json()["message"] == "No audio:write permission on the requested project or collection"


def test_creator_options_allow_collection_audio_write_only_for_that_collection(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.get(User, _normal_test_user_id(db))
    assert user is not None
    owner = create_test_user(db)
    project, writable_collection = _create_project_with_collection(
        db,
        owner,
        project_name="Creator Collection Audio Write Project",
        collection_name="Creator Writable Collection",
    )
    other_collection = Collection(name="Creator Read Only Collection", creator_id=owner.user_id)
    db.add(other_collection)
    db.commit()
    db.refresh(other_collection)
    db.add(ProjectCollection(
        project_id=project.project_id,
        collection_id=other_collection.collection_id,
    ))
    db.commit()
    _grant_permission(
        db,
        user,
        "audio",
        "write",
        project_id=project.project_id,
        collection_id=writable_collection.collection_id,
    )

    allowed = client.get(
        f"{settings.API_V1_STR}/users/creators?project_id={project.project_id}&collection_id={writable_collection.collection_id}",
        headers=normal_user_token_headers,
    )
    denied = client.get(
        f"{settings.API_V1_STR}/users/creators?project_id={project.project_id}&collection_id={other_collection.collection_id}",
        headers=normal_user_token_headers,
    )

    assert allowed.status_code == 200
    assert denied.status_code == 403


def test_current_user_reports_scoped_audio_write_capability(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.get(User, _normal_test_user_id(db))
    assert user is not None
    owner = create_test_user(db)
    project, writable_collection = _create_project_with_collection(
        db,
        owner,
        project_name="Current User Audio Capability Project",
        collection_name="Current User Writable Collection",
    )
    other_collection = Collection(name="Current User Read Only Collection", creator_id=owner.user_id)
    db.add(other_collection)
    db.commit()
    db.refresh(other_collection)
    db.add(ProjectCollection(
        project_id=project.project_id,
        collection_id=other_collection.collection_id,
    ))
    db.commit()
    _grant_permission(db, user, "audio", "read", project_id=project.project_id)

    read_only = client.get(
        f"{settings.API_V1_STR}/current-user?project_id={project.project_id}",
        headers=normal_user_token_headers,
    )
    assert read_only.status_code == 200
    assert read_only.json()["data"]["can_write_audio"] is False

    _grant_permission(
        db,
        user,
        "audio",
        "write",
        project_id=project.project_id,
        collection_id=writable_collection.collection_id,
    )

    all_collections = client.get(
        f"{settings.API_V1_STR}/current-user?project_id={project.project_id}",
        headers=normal_user_token_headers,
    )
    writable_scope = client.get(
        f"{settings.API_V1_STR}/current-user?project_id={project.project_id}&collection_id={writable_collection.collection_id}",
        headers=normal_user_token_headers,
    )
    read_only_scope = client.get(
        f"{settings.API_V1_STR}/current-user?project_id={project.project_id}&collection_id={other_collection.collection_id}",
        headers=normal_user_token_headers,
    )

    assert all_collections.json()["data"]["can_write_audio"] is True
    assert writable_scope.json()["data"]["can_write_audio"] is True
    assert read_only_scope.json()["data"]["can_write_audio"] is False


def test_get_users_normal_user_me_with_project_write(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.get(User, _normal_test_user_id(db))
    assert user is not None
    owner = create_test_user(db)
    project, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Project Write Me",
        collection_name="Project Write Me Collection",
    )
    _grant_permission(db, user, "project", "write", project_id=project.project_id)

    r = client.get(f"{settings.API_V1_STR}/current-user", headers=normal_user_token_headers)

    assert r.status_code == 200
    current_user = r.json()["data"]
    assert current_user["is_admin"] is False
    assert current_user["is_project_admin"] is True


def test_get_users_normal_user_me_with_project_id_requires_write_on_that_project(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.get(User, _normal_test_user_id(db))
    assert user is not None
    owner = create_test_user(db)
    target_project, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Project Write Target",
        collection_name="Project Write Target Collection",
    )
    other_project, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Project Write Other",
        collection_name="Project Write Other Collection",
    )
    _grant_permission(db, user, "project", "write", project_id=other_project.project_id)

    r = client.get(
        f"{settings.API_V1_STR}/current-user?project_id={target_project.project_id}",
        headers=normal_user_token_headers,
    )

    assert r.status_code == 200
    current_user = r.json()["data"]
    assert current_user["is_admin"] is False
    assert current_user["is_project_admin"] is False


def test_get_users_normal_user_me_with_any_project_write(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.get(User, _normal_test_user_id(db))
    assert user is not None
    owner = create_test_user(db)
    project_a, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Project Write Any A",
        collection_name="Project Write Any Collection A",
    )
    project_b, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Project Write Any B",
        collection_name="Project Write Any Collection B",
    )
    _grant_permission(db, user, "project", "write", project_id=project_b.project_id)

    r = client.get(f"{settings.API_V1_STR}/current-user", headers=normal_user_token_headers)

    assert r.status_code == 200
    current_user = r.json()["data"]
    assert current_user["is_project_admin"] is True
    assert project_a.project_id != project_b.project_id


def test_get_users_normal_user_me_with_project_id_and_matching_project_write(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.get(User, _normal_test_user_id(db))
    assert user is not None
    owner = create_test_user(db)
    project, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Project Write Exact",
        collection_name="Project Write Exact Collection",
    )
    _grant_permission(db, user, "project", "write", project_id=project.project_id)

    r = client.get(
        f"{settings.API_V1_STR}/current-user?project_id={project.project_id}",
        headers=normal_user_token_headers,
    )

    assert r.status_code == 200
    current_user = r.json()["data"]
    assert current_user["is_project_admin"] is True


def test_get_users_normal_user_me_with_collection_write_only(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.get(User, _normal_test_user_id(db))
    assert user is not None
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db,
        owner,
        project_name="Collection Write Only Project",
        collection_name="Collection Write Only Collection",
    )
    _grant_permission(
        db,
        user,
        "collection",
        "write",
        project_id=project.project_id,
        collection_id=collection.collection_id,
    )

    r = client.get(f"{settings.API_V1_STR}/current-user", headers=normal_user_token_headers)

    assert r.status_code == 200
    current_user = r.json()["data"]
    assert current_user["is_admin"] is False
    assert current_user["is_project_admin"] is False


def test_get_users_normal_user_me_with_project_id_and_collection_write_only(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    user = db.get(User, _normal_test_user_id(db))
    assert user is not None
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db,
        owner,
        project_name="Collection Write Only Target Project",
        collection_name="Collection Write Only Target Collection",
    )
    _grant_permission(
        db,
        user,
        "collection",
        "write",
        project_id=project.project_id,
        collection_id=collection.collection_id,
    )

    r = client.get(
        f"{settings.API_V1_STR}/current-user?project_id={project.project_id}",
        headers=normal_user_token_headers,
    )

    assert r.status_code == 200
    current_user = r.json()["data"]
    assert current_user["is_admin"] is False
    assert current_user["is_project_admin"] is False


def test_get_users_superuser_me_with_project_id_is_project_admin(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    owner = create_test_user(db)
    project, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Superuser Project Context",
        collection_name="Superuser Project Context Collection",
    )

    r = client.get(
        f"{settings.API_V1_STR}/current-user?project_id={project.project_id}",
        headers=superuser_token_headers,
    )

    assert r.status_code == 200
    current_user = r.json()["data"]
    assert current_user["is_admin"] is True
    assert current_user["is_project_admin"] is True


def test_create_user_new_email(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Admin creates a user bound to a project
    owner = create_test_user(db)
    project = Project(name="Test Project Create", url="http://test.com", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    db.refresh(project)

    email = random_email()
    password = random_lower_string()
    username = random_lower_string()[:20]
    color = "#11aa33"
    data = {
        "username": username,
        "name": "New Test User",
        "email": email,
        "password": password,
        "color": color,
    }
    r = client.post(
        f"{settings.API_V1_STR}/users/?project_id={project.project_id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert 200 <= r.status_code < 300
    json_resp = r.json()
    assert json_resp["code"] == 0
    assert json_resp["data"] is None
    user = user_repository.get_by_email(session=db, email=email)
    assert user
    assert user.email == email
    assert user.color == "#11AA33"
    # New users are always assigned the normal role regardless of caller
    assert user.role.name == "User"


def test_create_user_invalid_color(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project = Project(name="Test Project Invalid Color", url="http://invalid-color.com", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    db.refresh(project)

    data = {
        "username": random_lower_string()[:20],
        "name": "Invalid Color User",
        "email": random_email(),
        "password": random_lower_string(),
        "color": "blue",
    }
    r = client.post(
        f"{settings.API_V1_STR}/users/?project_id={project.project_id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 422


def test_get_existing_user(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)
    user.color = "#00AAFF"
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.user_id
    r = client.get(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert 200 <= r.status_code < 300
    json_resp = r.json()
    assert json_resp["code"] == 0
    api_user = json_resp["data"]
    assert user.email == api_user["email"]
    assert api_user["color"] == "#00AAFF"
    assert "can_write_audio" not in api_user


def test_get_existing_user_current_user(client: TestClient, db: Session) -> None:
    password = random_lower_string()
    user = create_test_user(db, password=password)
    user_id = user.user_id

    login_data = {
        "username": user.username,
        "password": password,
    }
    r = client.post(f"{settings.API_V1_STR}/auth-tokens", data=login_data)
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}

    r = client.get(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=headers,
    )
    assert 200 <= r.status_code < 300
    json_resp = r.json()
    assert json_resp["code"] == 0
    api_user = json_resp["data"]
    assert user.email == api_user["email"]


def test_get_existing_user_permissions_error(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    # Create a user that the normal user doesn't have permission to view
    user = create_test_user(db)
    r = client.get(
        f"{settings.API_V1_STR}/users/{user.user_id}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403
    assert r.json()["message"] == "Target user is not within your management scope"


def test_create_user_existing_username(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Reuse any existing project (admin has all permissions)
    owner = create_test_user(db)
    project = Project(name="Dup Username Proj", url="http://dup.com", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    db.refresh(project)

    user = create_test_user(db)
    data = {
        "username": user.username,
        "name": "Another User",
        "email": random_email(),
        "password": random_lower_string(),
    }
    r = client.post(
        f"{settings.API_V1_STR}/users/?project_id={project.project_id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 400
    json_resp = r.json()
    assert json_resp["code"] != 0
    assert "user_id" not in json_resp


def test_create_user_with_project_write_permission(
    client: TestClient, db: Session
) -> None:
    """User with project:write can create a user bound to that project and gets project:read."""
    # 1. Create a manager user
    mgr_password = random_lower_string()
    mgr = user_repository.create(session=db, obj_in=UserCreate(
        username=random_lower_string()[:20], name="Manager",
        email=random_email(), password=mgr_password
    ))

    # 2. Create a project and grant project:write to manager
    owner = create_test_user(db)
    project = Project(name="PM Project", url="http://pm.com", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    db.refresh(project)

    write_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "write"
    )).one()
    db.add(UserPermission(user_id=mgr.user_id, project_id=project.project_id, permission_id=write_perm.permission_id))
    db.commit()

    # 3. Auth as manager
    headers = user_authentication_headers(client=client, username=mgr.username, password=mgr_password)

    # 4. Create user via API
    new_email = random_email()
    data = {
        "username": random_lower_string()[:20], "name": "New Member",
        "email": new_email, "password": random_lower_string(),
    }
    r = client.post(
        f"{settings.API_V1_STR}/users/?project_id={project.project_id}",
        headers=headers, json=data,
    )
    assert r.status_code == 200

    # 5. Verify new user has project:read
    new_user = user_repository.get_by_email(session=db, email=new_email)
    assert new_user
    read_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "read"
    )).one()
    up = db.exec(select(UserPermission).where(
        UserPermission.user_id == new_user.user_id,
        UserPermission.project_id == project.project_id,
        UserPermission.permission_id == read_perm.permission_id,
    )).first()
    assert up is not None


def test_create_user_with_collection_write_permission(
    client: TestClient, db: Session
) -> None:
    """User with collection:write can create a user bound to that collection and gets collection:read."""
    # 1. Create a manager user
    mgr_password = random_lower_string()
    mgr = user_repository.create(session=db, obj_in=UserCreate(
        username=random_lower_string()[:20], name="CollManager",
        email=random_email(), password=mgr_password
    ))

    # 2. Create a project and collection
    owner = create_test_user(db)
    project = Project(name="Coll Bind Proj", url="http://coll.com", creator_id=owner.user_id)
    db.add(project)
    collection = Collection(name="Bind Collection", creator_id=owner.user_id)
    db.add(collection)
    db.commit()
    db.refresh(project)
    db.refresh(collection)
    db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
    db.commit()

    # 3. Grant collection:write to manager
    write_perm = db.exec(select(Permission).where(
        Permission.resource_type == "collection", Permission.action == "write"
    )).one()
    db.add(UserPermission(
        user_id=mgr.user_id,
        project_id=project.project_id,
        collection_id=collection.collection_id,
        permission_id=write_perm.permission_id,
    ))
    db.commit()

    # 4. Auth as manager
    headers = user_authentication_headers(client=client, username=mgr.username, password=mgr_password)

    # 5. Create user via API
    new_email = random_email()
    data = {
        "username": random_lower_string()[:20], "name": "Coll Member",
        "email": new_email, "password": random_lower_string(),
    }
    r = client.post(
        f"{settings.API_V1_STR}/users/?project_id={project.project_id}&collection_id={collection.collection_id}",
        headers=headers, json=data,
    )
    assert r.status_code == 200

    # 6. Verify new user has collection:read
    new_user = user_repository.get_by_email(session=db, email=new_email)
    assert new_user
    read_perm = db.exec(select(Permission).where(
        Permission.resource_type == "collection", Permission.action == "read"
    )).one()
    up = db.exec(select(UserPermission).where(
        UserPermission.user_id == new_user.user_id,
        UserPermission.collection_id == collection.collection_id,
        UserPermission.permission_id == read_perm.permission_id,
    )).first()
    assert up is not None


def test_create_user_no_project_permission_fails(
    client: TestClient, db: Session
) -> None:
    """User without project:write cannot create a user in that project."""
    # 1. Create a manager with project:write on project A but request targets project B
    mgr_password = random_lower_string()
    mgr = user_repository.create(session=db, obj_in=UserCreate(
        username=random_lower_string()[:20], name="Manager2",
        email=random_email(), password=mgr_password
    ))
    owner = create_test_user(db)
    project_a = Project(name="PM Project A", url="http://a.com", creator_id=owner.user_id)
    project_b = Project(name="PM Project B", url="http://b.com", creator_id=owner.user_id)
    db.add(project_a)
    db.add(project_b)
    db.commit()
    db.refresh(project_a)
    db.refresh(project_b)

    write_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "write"
    )).one()
    db.add(UserPermission(user_id=mgr.user_id, project_id=project_a.project_id, permission_id=write_perm.permission_id))
    db.commit()

    headers = user_authentication_headers(client=client, username=mgr.username, password=mgr_password)

    data = {
        "username": random_lower_string()[:20], "name": "No Access",
        "email": random_email(), "password": random_lower_string(),
    }
    # Attempt to create in project B (no permission)
    r = client.post(
        f"{settings.API_V1_STR}/users/?project_id={project_b.project_id}",
        headers=headers, json=data,
    )
    assert r.status_code == 403


def test_create_user_by_normal_user(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    data = {
        "username": random_lower_string()[:20],
        "name": "Test User",
        "email": random_email(),
        "password": random_lower_string(),
    }
    r = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 403


def test_retrieve_users(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    create_test_user(db)
    create_test_user(db)

    r = client.get(f"{settings.API_V1_STR}/users/", headers=superuser_token_headers)
    json_resp = r.json()
    assert json_resp["code"] == 0
    all_users = json_resp["data"]

    assert len(all_users) > 1
    # assert "count" in all_users # count is usually top level or part of page_info, checking data length is enough or check page_info
    # Since all_users is now the list (from data), we check length
    assert "data" not in all_users # all_users IS the data list
    for item in all_users:
        assert "email" in item


def test_list_users_project_manager_sees_only_ordinary_users_in_managed_project(
    client: TestClient, db: Session
) -> None:
    owner = create_test_user(db)
    project_a, _ = _create_project_with_collection(
        db,
        owner,
        project_name="User List Manager Project A",
        collection_name="User List Manager Collection A",
    )
    project_b, _ = _create_project_with_collection(
        db,
        owner,
        project_name="User List Manager Project B",
        collection_name="User List Manager Collection B",
    )
    manager_password = random_lower_string()
    manager = create_test_user(db, password=manager_password, name="List Project Manager")
    ordinary_a = create_test_user(db, name="List Ordinary A")
    peer_manager_a = create_test_user(db, name="List Peer Project Manager A")
    ordinary_b = create_test_user(db, name="List Ordinary B")

    _grant_permission(db, manager, "project", "write", project_id=project_a.project_id)
    _grant_permission(db, ordinary_a, "project", "read", project_id=project_a.project_id)
    _grant_permission(db, peer_manager_a, "project", "write", project_id=project_a.project_id)
    _grant_permission(db, ordinary_b, "project", "read", project_id=project_b.project_id)

    headers = user_authentication_headers(
        client=client,
        username=manager.username,
        password=manager_password,
    )
    r = client.get(
        f"{settings.API_V1_STR}/users?scope=all&page_size=100",
        headers=headers,
    )

    assert r.status_code == 200
    ids = {user["user_id"] for user in r.json()["data"]}
    assert ordinary_a.user_id in ids
    assert ordinary_b.user_id not in ids
    assert peer_manager_a.user_id not in ids
    assert manager.user_id not in ids
    assert _superuser_id(db) not in ids


def test_list_users_current_project_cannot_bypass_manager_scope(
    client: TestClient, db: Session
) -> None:
    owner = create_test_user(db)
    project_a, _ = _create_project_with_collection(
        db,
        owner,
        project_name="No Bypass Project A",
        collection_name="No Bypass Collection A",
    )
    project_b, _ = _create_project_with_collection(
        db,
        owner,
        project_name="No Bypass Project B",
        collection_name="No Bypass Collection B",
    )
    manager_password = random_lower_string()
    manager = create_test_user(db, password=manager_password, name="No Bypass Manager")
    ordinary_b = create_test_user(db, name="No Bypass Ordinary B")

    _grant_permission(db, manager, "project", "write", project_id=project_a.project_id)
    _grant_permission(db, ordinary_b, "project", "read", project_id=project_b.project_id)

    headers = user_authentication_headers(
        client=client,
        username=manager.username,
        password=manager_password,
    )
    r = client.get(
        f"{settings.API_V1_STR}/users?scope=current&project_id={project_b.project_id}",
        headers=headers,
    )

    assert r.status_code == 200
    assert r.json()["data"] == []


def test_list_users_collection_manager_uses_project_local_collection_scope(
    client: TestClient, db: Session
) -> None:
    owner = create_test_user(db)
    project_a, collection_x = _create_project_with_collection(
        db,
        owner,
        project_name="Collection Scope Project A",
        collection_name="Collection Scope X",
    )
    project_b, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Collection Scope Project B",
        collection_name="Collection Scope Other",
    )
    manager_password = random_lower_string()
    manager = create_test_user(db, password=manager_password, name="Collection Scope Manager")
    ordinary_x = create_test_user(db, name="Collection Scope Ordinary")
    peer_collection_manager = create_test_user(db, name="Collection Scope Peer")
    parent_project_manager = create_test_user(db, name="Collection Scope Parent Manager")
    other_project_same_collection = create_test_user(db, name="Collection Scope Other Project")

    db.add(ProjectCollection(
        project_id=project_b.project_id,
        collection_id=collection_x.collection_id,
    ))
    db.commit()

    _grant_permission(
        db,
        manager,
        "collection",
        "write",
        project_id=project_a.project_id,
        collection_id=collection_x.collection_id,
    )
    _grant_permission(
        db,
        ordinary_x,
        "collection",
        "read",
        project_id=project_a.project_id,
        collection_id=collection_x.collection_id,
    )
    _grant_permission(
        db,
        peer_collection_manager,
        "collection",
        "write",
        project_id=project_a.project_id,
        collection_id=collection_x.collection_id,
    )
    _grant_permission(db, parent_project_manager, "project", "write", project_id=project_a.project_id)
    _grant_permission(
        db,
        other_project_same_collection,
        "collection",
        "read",
        project_id=project_b.project_id,
        collection_id=collection_x.collection_id,
    )

    headers = user_authentication_headers(
        client=client,
        username=manager.username,
        password=manager_password,
    )
    r = client.get(
        f"{settings.API_V1_STR}/users?scope=current&project_id={project_a.project_id}"
        f"&collection_id={collection_x.collection_id}&page_size=100",
        headers=headers,
    )

    assert r.status_code == 200
    ids = {user["user_id"] for user in r.json()["data"]}
    assert ordinary_x.user_id in ids
    assert peer_collection_manager.user_id not in ids
    assert parent_project_manager.user_id not in ids
    assert other_project_same_collection.user_id not in ids
    assert manager.user_id not in ids


def test_list_users_scope_all_merges_project_and_collection_write_scopes(
    client: TestClient, db: Session
) -> None:
    owner = create_test_user(db)
    project_a, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Scope All Merge Project A",
        collection_name="Scope All Merge Collection A",
    )
    project_b, collection_b = _create_project_with_collection(
        db,
        owner,
        project_name="Scope All Merge Project B",
        collection_name="Scope All Merge Collection B",
    )
    manager_password = random_lower_string()
    manager = create_test_user(db, password=manager_password, name="Scope All Merge Manager")
    project_user = create_test_user(db, name="Scope All Merge Project User")
    collection_user = create_test_user(db, name="Scope All Merge Collection User")
    outside_user = create_test_user(db, name="Scope All Merge Outside User")

    _grant_permission(db, manager, "project", "write", project_id=project_a.project_id)
    _grant_permission(
        db,
        manager,
        "collection",
        "write",
        project_id=project_b.project_id,
        collection_id=collection_b.collection_id,
    )
    _grant_permission(db, project_user, "project", "read", project_id=project_a.project_id)
    _grant_permission(
        db,
        collection_user,
        "collection",
        "read",
        project_id=project_b.project_id,
        collection_id=collection_b.collection_id,
    )
    _grant_permission(db, outside_user, "project", "read", project_id=project_b.project_id)

    headers = user_authentication_headers(
        client=client,
        username=manager.username,
        password=manager_password,
    )
    r = client.get(
        f"{settings.API_V1_STR}/users?scope=all&page_size=100",
        headers=headers,
    )

    assert r.status_code == 200
    ids = {user["user_id"] for user in r.json()["data"]}
    assert project_user.user_id in ids
    assert collection_user.user_id in ids
    assert outside_user.user_id not in ids
    assert len(ids) == len(r.json()["data"])




def test_export_users_manager_scope_matches_user_list(
    client: TestClient, db: Session
) -> None:
    owner = create_test_user(db)
    project, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Export Scope Project",
        collection_name="Export Scope Collection",
    )
    manager_password = random_lower_string()
    manager = create_test_user(db, password=manager_password, name="Export Manager")
    ordinary = create_test_user(db, name="Export Ordinary")
    peer_manager = create_test_user(db, name="Export Peer Manager")
    outside = create_test_user(db, name="Export Outside")

    _grant_permission(db, manager, "project", "write", project_id=project.project_id)
    _grant_permission(db, ordinary, "project", "read", project_id=project.project_id)
    _grant_permission(db, peer_manager, "project", "write", project_id=project.project_id)

    headers = user_authentication_headers(
        client=client,
        username=manager.username,
        password=manager_password,
    )
    r = client.get(f"{settings.API_V1_STR}/users/exports", headers=headers)

    assert r.status_code == 200
    assert r.headers["content-disposition"] == (
        'attachment; filename="users.csv"; '
        "filename*=UTF-8''users.csv"
    )
    csv_body = r.text
    header = read_csv_header(csv_body)
    assert header == ["user_id", "username", "name", "email", "orcid", "color", "contrib", "active"]
    assert ordinary.email in csv_body
    assert peer_manager.email not in csv_body
    assert outside.email not in csv_body
    assert manager.email not in csv_body
    rows = list(csv.DictReader(csv_body.splitlines()))
    assert settings.FIRST_SUPERUSER not in {row["username"] for row in rows}


def test_export_users_current_collection_scope_filters_to_selected_collection(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project, selected_collection = _create_project_with_collection(
        db,
        owner,
        project_name="Current Export Scope Project",
        collection_name="Current Export Selected Collection",
    )
    other_collection = Collection(
        name="Current Export Other Collection",
        creator_id=owner.user_id,
    )
    db.add(other_collection)
    db.commit()
    db.refresh(other_collection)
    db.add(ProjectCollection(
        project_id=project.project_id,
        collection_id=other_collection.collection_id,
    ))
    db.commit()

    selected_user = create_test_user(db, name="Current Export Selected User")
    other_user = create_test_user(db, name="Current Export Other User")
    _grant_permission(
        db,
        selected_user,
        "collection",
        "read",
        project_id=project.project_id,
        collection_id=selected_collection.collection_id,
    )
    _grant_permission(
        db,
        other_user,
        "collection",
        "read",
        project_id=project.project_id,
        collection_id=other_collection.collection_id,
    )

    response = client.get(
        f"{settings.API_V1_STR}/users/exports?project_id={project.project_id}"
        f"&collection_id={selected_collection.collection_id}&scope=current",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    rows_by_id = {int(row["user_id"]): row for row in read_csv_dict_rows(response.text)}
    assert selected_user.user_id in rows_by_id
    assert other_user.user_id not in rows_by_id


def test_export_users_all_collection_scope_keeps_all_users_and_collection_contrib(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db,
        owner,
        project_name="All Export Scope Project",
        collection_name="All Export Scope Collection",
    )
    contributor = create_test_user(db, name="All Export Contributor")
    other_user = create_test_user(db, name="All Export Other User")
    db.add(CollectionContributor(
        user_id=contributor.user_id,
        collection_id=collection.collection_id,
        contribution_role="Reviewer",
    ))
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/users/exports?project_id={project.project_id}"
        f"&collection_id={collection.collection_id}&scope=all",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    rows_by_id = {int(row["user_id"]): row for row in read_csv_dict_rows(response.text)}
    assert contributor.user_id in rows_by_id
    assert other_user.user_id in rows_by_id
    assert rows_by_id[contributor.user_id]["contrib"] == "Reviewer"
    assert rows_by_id[other_user.user_id]["contrib"] == ""


def test_export_users_current_collection_scope_respects_manager_access(
    client: TestClient, db: Session
) -> None:
    owner = create_test_user(db)
    project, managed_collection = _create_project_with_collection(
        db,
        owner,
        project_name="Manager Export Scope Project",
        collection_name="Manager Export Managed Collection",
    )
    other_collection = Collection(
        name="Manager Export Other Collection",
        creator_id=owner.user_id,
    )
    db.add(other_collection)
    db.commit()
    db.refresh(other_collection)
    db.add(ProjectCollection(
        project_id=project.project_id,
        collection_id=other_collection.collection_id,
    ))
    db.commit()

    manager_password = random_lower_string()
    manager = create_test_user(db, password=manager_password, name="Manager Export Manager")
    managed_user = create_test_user(db, name="Manager Export Managed User")
    out_of_scope_user = create_test_user(db, name="Manager Export Other User")
    _grant_permission(
        db,
        manager,
        "collection",
        "write",
        project_id=project.project_id,
        collection_id=managed_collection.collection_id,
    )
    _grant_permission(
        db,
        managed_user,
        "collection",
        "read",
        project_id=project.project_id,
        collection_id=managed_collection.collection_id,
    )
    _grant_permission(
        db,
        out_of_scope_user,
        "collection",
        "read",
        project_id=project.project_id,
        collection_id=other_collection.collection_id,
    )
    headers = user_authentication_headers(
        client=client,
        username=manager.username,
        password=manager_password,
    )

    response = client.get(
        f"{settings.API_V1_STR}/users/exports?project_id={project.project_id}"
        f"&collection_id={managed_collection.collection_id}&scope=current",
        headers=headers,
    )

    assert response.status_code == 200
    rows_by_id = {int(row["user_id"]): row for row in read_csv_dict_rows(response.text)}
    assert managed_user.user_id in rows_by_id
    assert out_of_scope_user.user_id not in rows_by_id
    assert manager.user_id not in rows_by_id


def test_read_user_by_id_manager_cannot_view_peer_manager(
    client: TestClient, db: Session
) -> None:
    owner = create_test_user(db)
    project, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Detail Scope Project",
        collection_name="Detail Scope Collection",
    )
    manager_password = random_lower_string()
    manager = create_test_user(db, password=manager_password, name="Detail Manager")
    ordinary = create_test_user(db, name="Detail Ordinary")
    peer_manager = create_test_user(db, name="Detail Peer Manager")

    _grant_permission(db, manager, "project", "write", project_id=project.project_id)
    _grant_permission(db, ordinary, "project", "read", project_id=project.project_id)
    _grant_permission(db, peer_manager, "project", "write", project_id=project.project_id)

    headers = user_authentication_headers(
        client=client,
        username=manager.username,
        password=manager_password,
    )

    ordinary_response = client.get(
        f"{settings.API_V1_STR}/users/{ordinary.user_id}",
        headers=headers,
    )
    peer_response = client.get(
        f"{settings.API_V1_STR}/users/{peer_manager.user_id}",
        headers=headers,
    )

    assert ordinary_response.status_code == 200
    assert ordinary_response.json()["data"]["user_id"] == ordinary.user_id
    assert peer_response.status_code == 403
    assert peer_response.json()["message"] == "Target user is not within your management scope"


def test_retrieve_users_with_search(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """Test user search across multiple fields."""
    # Create users with unique searchable fields
    user1 = create_test_user(db, name="Unique Search Name", username="uniqueusr", email="unique@lab.edu", orcid="0000-0000-0000-1234", active=True)
    user2 = create_test_user(db, name="Another User", username="another", email="another@lab.edu", orcid="1111-1111", active=False)
    
    # Create project and collection for testing filters
    proj = Project(name="Search Project", url="http://search.com", creator_id=user1.user_id)
    db.add(proj)
    db.commit()
    db.refresh(proj)
    
    col = Collection(name="Search Collection", creator_id=user1.user_id)
    db.add(col)
    db.commit()
    db.refresh(col)
    db.add(ProjectCollection(project_id=proj.project_id, collection_id=col.collection_id))
    db.commit()
    
    # Bind user1 to project, user2 to collection
    read_proj_perm = db.exec(select(Permission).where(Permission.resource_type == "project", Permission.action == "read")).one()
    read_col_perm = db.exec(select(Permission).where(Permission.resource_type == "collection", Permission.action == "read")).one()
    
    db.add(UserPermission(user_id=user1.user_id, project_id=proj.project_id, permission_id=read_proj_perm.permission_id))
    db.add(UserPermission(
        user_id=user2.user_id,
        project_id=proj.project_id,
        collection_id=col.collection_id,
        permission_id=read_col_perm.permission_id,
    ))
    db.commit()

    # Search by name
    r = client.get(
        f"{settings.API_V1_STR}/users/?name=Unique",
        headers=superuser_token_headers
    )
    assert r.status_code == 200
    json_resp = r.json()
    assert json_resp["code"] == 0
    data = json_resp["data"]  # data is the list
    assert len(data) >= 1
    assert all("preference" not in u for u in data)
    assert any(u["name"] == "Unique Search Name" for u in data)

    # Search by user_id
    r = client.get(
        f"{settings.API_V1_STR}/users/?user_id={user1.user_id}",
        headers=superuser_token_headers
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["user_id"] == user1.user_id

    # Search by username
    r = client.get(
        f"{settings.API_V1_STR}/users/?username=uniqueu",
        headers=superuser_token_headers
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    assert any(u["username"] == "uniqueusr" for u in data)

    # Search by email
    r = client.get(
        f"{settings.API_V1_STR}/users/?email=unique@lab",
        headers=superuser_token_headers
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    assert any(u["email"] == "unique@lab.edu" for u in data)

    # Search by orcid
    r = client.get(
        f"{settings.API_V1_STR}/users/?orcid=0000-0000",
        headers=superuser_token_headers
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    assert any(u["orcid"] == "0000-0000-0000-1234" for u in data)

    # Search by active=False
    r = client.get(
        f"{settings.API_V1_STR}/users/?active=false",
        headers=superuser_token_headers
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    assert any(u["user_id"] == user2.user_id for u in data)

    # Search by project_id
    r = client.get(
        f"{settings.API_V1_STR}/users/?project_id={proj.project_id}",
        headers=superuser_token_headers
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    assert any(u["user_id"] == user1.user_id for u in data)

    # Search by collection_id
    r = client.get(
        f"{settings.API_V1_STR}/users/?collection_id={col.collection_id}",
        headers=superuser_token_headers
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    assert any(u["user_id"] == user2.user_id for u in data)


def test_read_users_scope_default_equals_current(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project = Project(name="Scope Default Project", url="http://scope-default.com", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    db.refresh(project)

    in_project_user = create_test_user(db)
    read_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "read"
    )).one()
    db.add(UserPermission(
        user_id=in_project_user.user_id,
        project_id=project.project_id,
        permission_id=read_perm.permission_id
    ))
    db.commit()

    r_default = client.get(
        f"{settings.API_V1_STR}/users?project_id={project.project_id}",
        headers=superuser_token_headers,
    )
    r_current = client.get(
        f"{settings.API_V1_STR}/users?project_id={project.project_id}&scope=current",
        headers=superuser_token_headers,
    )

    assert r_default.status_code == 200
    assert r_current.status_code == 200
    ids_default = sorted(u["user_id"] for u in r_default.json()["data"])
    ids_current = sorted(u["user_id"] for u in r_current.json()["data"])
    assert ids_default == ids_current


def test_read_users_scope_all_project_only_links_contrib(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project = Project(name="Scope All Project", url="http://scope-all-project.com", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    db.refresh(project)

    in_project_user = create_test_user(db)
    out_project_user = create_test_user(db)

    db.add(ProjectContributor(
        user_id=in_project_user.user_id,
        project_id=project.project_id,
        contribution_role="Data Analyst"
    ))
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/users?scope=all&project_id={project.project_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    by_id = {u["user_id"]: u for u in data}

    assert in_project_user.user_id in by_id
    assert out_project_user.user_id in by_id
    assert by_id[in_project_user.user_id]["contrib"] == "Data Analyst"
    assert by_id[out_project_user.user_id]["contrib"] is None


def test_read_users_scope_all_collection_only_links_contrib(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    collection = Collection(name="Scope All Collection", creator_id=owner.user_id)
    db.add(collection)
    db.commit()
    db.refresh(collection)

    in_collection_user = create_test_user(db)
    out_collection_user = create_test_user(db)

    db.add(CollectionContributor(
        user_id=in_collection_user.user_id,
        collection_id=collection.collection_id,
        contribution_role="Reviewer"
    ))
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/users?scope=all&collection_id={collection.collection_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    by_id = {u["user_id"]: u for u in data}

    assert in_collection_user.user_id in by_id
    assert out_collection_user.user_id in by_id
    assert by_id[in_collection_user.user_id]["contrib"] == "Reviewer"
    assert by_id[out_collection_user.user_id]["contrib"] is None


def test_read_users_scope_all_contrib_filter_uses_context_only(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project = Project(name="Scope All Contrib Filter Project", url="http://scope-all-contrib.com", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    db.refresh(project)

    analyst_user = create_test_user(db)
    other_role_user = create_test_user(db)

    db.add(ProjectContributor(
        user_id=analyst_user.user_id,
        project_id=project.project_id,
        contribution_role="Data Analyst"
    ))
    db.add(ProjectContributor(
        user_id=other_role_user.user_id,
        project_id=project.project_id,
        contribution_role="Lead Researcher"
    ))
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/users?scope=all&project_id={project.project_id}&contrib=Data%20Analyst",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    user_ids = [u["user_id"] for u in data]

    assert analyst_user.user_id in user_ids
    assert other_role_user.user_id not in user_ids


def test_read_users_scope_all_contrib_filter_supports_fuzzy_match(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project = Project(name="Scope All Contrib Fuzzy Project", url="http://scope-all-contrib-fuzzy.com", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    db.refresh(project)

    analyst_user = create_test_user(db)
    reviewer_user = create_test_user(db)

    db.add(ProjectContributor(
        user_id=analyst_user.user_id,
        project_id=project.project_id,
        contribution_role="Data Analyst"
    ))
    db.add(ProjectContributor(
        user_id=reviewer_user.user_id,
        project_id=project.project_id,
        contribution_role="Lead Researcher"
    ))
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/users?scope=all&project_id={project.project_id}&contrib=anal",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    user_ids = [u["user_id"] for u in data]

    assert analyst_user.user_id in user_ids
    assert reviewer_user.user_id not in user_ids


def test_read_users_scope_all_both_ids_prioritize_collection_for_contrib(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project = Project(name="Scope All Both IDs Project", url="http://scope-all-both.com", creator_id=owner.user_id)
    collection = Collection(name="Scope All Both IDs Collection", creator_id=owner.user_id)
    db.add(project)
    db.add(collection)
    db.commit()
    db.refresh(project)
    db.refresh(collection)

    both_contrib_user = create_test_user(db)
    project_only_user = create_test_user(db)

    db.add(ProjectContributor(
        user_id=both_contrib_user.user_id,
        project_id=project.project_id,
        contribution_role="Data Analyst"
    ))
    db.add(CollectionContributor(
        user_id=both_contrib_user.user_id,
        collection_id=collection.collection_id,
        contribution_role="Reviewer"
    ))
    db.add(ProjectContributor(
        user_id=project_only_user.user_id,
        project_id=project.project_id,
        contribution_role="Project Manager"
    ))
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/users?scope=all&project_id={project.project_id}&collection_id={collection.collection_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    by_id = {u["user_id"]: u for u in data}

    assert both_contrib_user.user_id in by_id
    assert project_only_user.user_id in by_id
    assert by_id[both_contrib_user.user_id]["contrib"] == "Reviewer"
    assert by_id[project_only_user.user_id]["contrib"] is None


def test_read_users_scope_invalid_returns_422(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/users?scope=invalid",
        headers=superuser_token_headers,
    )
    assert r.status_code == 422


def test_retrieve_users_with_order(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """Test user ordering by different fields."""
    user_aaa = create_test_user(db, name="AAA Test Order User", username="aaa_user", email="aaa_email@lab.edu")
    user_zzz = create_test_user(db, name="ZZZ Test Order User", username="zzz_user", email="zzz_email@lab.edu")
    
    # Order by name ascending 
    r = client.get(
        f"{settings.API_V1_STR}/users/?order_by=name&order_dir=asc&name=Test Order User",
        headers=superuser_token_headers
    )
    assert r.status_code == 200
    json_resp = r.json()
    assert json_resp["code"] == 0
    data = json_resp["data"]
    names = [u["name"] for u in data]
    assert "AAA Test Order User" in names
    assert "ZZZ Test Order User" in names
    assert names.index("AAA Test Order User") < names.index("ZZZ Test Order User")
    
    # Order by name descending 
    r = client.get(
        f"{settings.API_V1_STR}/users/?order_by=name&order_dir=desc&name=Test Order User",
        headers=superuser_token_headers
    )
    assert r.status_code == 200
    json_resp = r.json()
    assert json_resp["code"] == 0
    data = json_resp["data"]
    names = [u["name"] for u in data]
    assert names.index("ZZZ Test Order User") < names.index("AAA Test Order User")

    # Order by username descending 
    r = client.get(
        f"{settings.API_V1_STR}/users/?order_by=username&order_dir=desc&name=Test Order User",
        headers=superuser_token_headers
    )
    assert r.status_code == 200
    data = r.json()["data"]
    usernames = [u["username"] for u in data]
    assert usernames.index("zzz_user") < usernames.index("aaa_user")

    # Order by email descending 
    r = client.get(
        f"{settings.API_V1_STR}/users/?order_by=email&order_dir=desc&name=Test Order User",
        headers=superuser_token_headers
    )
    assert r.status_code == 200
    data = r.json()["data"]
    emails = [u["email"] for u in data]
    assert emails.index("zzz_email@lab.edu") < emails.index("aaa_email@lab.edu")

    # Order by id descending 
    r = client.get(
        f"{settings.API_V1_STR}/users/?order_by=user_id&order_dir=desc&name=Test Order User",
        headers=superuser_token_headers
    )
    assert r.status_code == 200
    data = r.json()["data"]
    ids = [u["user_id"] for u in data]
    assert ids.index(user_zzz.user_id) < ids.index(user_aaa.user_id)


def test_retrieve_users_order_by_project_contrib_asc_nulls_last(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Project Contrib Sort Asc",
        collection_name="Project Contrib Sort Asc Collection",
    )
    analyst = create_test_user(db, name="Project Contrib Sort User")
    manager = create_test_user(db, name="Project Contrib Sort User")
    no_contrib = create_test_user(db, name="Project Contrib Sort User")
    analyst_tie = create_test_user(db, name="Project Contrib Sort User")

    for user in (analyst, manager, no_contrib, analyst_tie):
        _grant_permission(db, user, "project", "read", project_id=project.project_id)

    db.add(ProjectContributor(
        user_id=analyst.user_id,
        project_id=project.project_id,
        contribution_role="Data Analyst",
    ))
    db.add(ProjectContributor(
        user_id=manager.user_id,
        project_id=project.project_id,
        contribution_role="Project Manager",
    ))
    db.add(ProjectContributor(
        user_id=analyst_tie.user_id,
        project_id=project.project_id,
        contribution_role="Data Analyst",
    ))
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/users?project_id={project.project_id}&order_by=contrib&order_dir=asc&name=Project%20Contrib%20Sort%20User",
        headers=superuser_token_headers,
    )

    assert r.status_code == 200
    data = r.json()["data"]
    ordered_ids = [user["user_id"] for user in data]
    ordered_contribs = [user["contrib"] for user in data]

    expected_tie_order = sorted([analyst.user_id, analyst_tie.user_id])
    assert ordered_ids[:2] == expected_tie_order
    assert ordered_ids[2] == manager.user_id
    assert ordered_ids[3] == no_contrib.user_id
    assert ordered_contribs == ["Data Analyst", "Data Analyst", "Project Manager", None]


def test_retrieve_users_order_by_project_contrib_desc_uses_database_default_null_order(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Project Contrib Sort Desc",
        collection_name="Project Contrib Sort Desc Collection",
    )
    analyst = create_test_user(db, name="Project Contrib Desc User")
    manager = create_test_user(db, name="Project Contrib Desc User")
    no_contrib = create_test_user(db, name="Project Contrib Desc User")

    for user in (analyst, manager, no_contrib):
        _grant_permission(db, user, "project", "read", project_id=project.project_id)

    db.add(ProjectContributor(
        user_id=analyst.user_id,
        project_id=project.project_id,
        contribution_role="Data Analyst",
    ))
    db.add(ProjectContributor(
        user_id=manager.user_id,
        project_id=project.project_id,
        contribution_role="Project Manager",
    ))
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/users?project_id={project.project_id}&order_by=contrib&order_dir=desc&name=Project%20Contrib%20Desc%20User",
        headers=superuser_token_headers,
    )

    assert r.status_code == 200
    data = r.json()["data"]
    assert [user["user_id"] for user in data] == [no_contrib.user_id, manager.user_id, analyst.user_id]
    assert [user["contrib"] for user in data] == [None, "Project Manager", "Data Analyst"]


def test_retrieve_users_order_by_collection_contrib_prioritizes_collection_context(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db,
        owner,
        project_name="Collection Contrib Sort",
        collection_name="Collection Contrib Sort Collection",
    )
    reviewer = create_test_user(db, name="Collection Contrib Sort User")
    annotator = create_test_user(db, name="Collection Contrib Sort User")

    for user in (reviewer, annotator):
        _grant_permission(db, user, "project", "read", project_id=project.project_id)
        _grant_permission(
            db,
            user,
            "collection",
            "read",
            project_id=project.project_id,
            collection_id=collection.collection_id,
        )

    db.add(ProjectContributor(
        user_id=reviewer.user_id,
        project_id=project.project_id,
        contribution_role="Data Analyst",
    ))
    db.add(ProjectContributor(
        user_id=annotator.user_id,
        project_id=project.project_id,
        contribution_role="Project Manager",
    ))
    db.add(CollectionContributor(
        user_id=reviewer.user_id,
        collection_id=collection.collection_id,
        contribution_role="Reviewer",
    ))
    db.add(CollectionContributor(
        user_id=annotator.user_id,
        collection_id=collection.collection_id,
        contribution_role="Annotator",
    ))
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/users?project_id={project.project_id}&collection_id={collection.collection_id}&order_by=contrib&order_dir=asc&name=Collection%20Contrib%20Sort%20User",
        headers=superuser_token_headers,
    )

    assert r.status_code == 200
    data = r.json()["data"]
    assert [user["user_id"] for user in data] == [annotator.user_id, reviewer.user_id]
    assert [user["contrib"] for user in data] == ["Annotator", "Reviewer"]


def test_retrieve_users_order_by_contrib_without_context_falls_back_to_user_id(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    first = create_test_user(db, name="No Context Contrib Sort User")
    second = create_test_user(db, name="No Context Contrib Sort User")

    r = client.get(
        f"{settings.API_V1_STR}/users?order_by=contrib&order_dir=asc&name=No%20Context%20Contrib%20Sort%20User",
        headers=superuser_token_headers,
    )

    assert r.status_code == 200
    data = r.json()["data"]
    assert [user["user_id"] for user in data] == sorted([first.user_id, second.user_id])


def test_export_users_order_by_contrib_matches_project_context_order(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project, _ = _create_project_with_collection(
        db,
        owner,
        project_name="Export Contrib Sort",
        collection_name="Export Contrib Sort Collection",
    )
    analyst = create_test_user(db, name="Export Contrib Sort User")
    manager = create_test_user(db, name="Export Contrib Sort User")
    no_contrib = create_test_user(db, name="Export Contrib Sort User")

    for user in (analyst, manager, no_contrib):
        _grant_permission(db, user, "project", "read", project_id=project.project_id)

    db.add(ProjectContributor(
        user_id=analyst.user_id,
        project_id=project.project_id,
        contribution_role="Data Analyst",
    ))
    db.add(ProjectContributor(
        user_id=manager.user_id,
        project_id=project.project_id,
        contribution_role="Project Manager",
    ))
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/users/exports?project_id={project.project_id}&order_by=contrib&order_dir=asc",
        headers=superuser_token_headers,
    )

    assert r.status_code == 200
    rows = [
        row for row in read_csv_dict_rows(r.text)
        if row["name"] == "Export Contrib Sort User"
    ]
    assert [int(row["user_id"]) for row in rows] == [analyst.user_id, manager.user_id, no_contrib.user_id]
    assert [row["contrib"] for row in rows] == ["Data Analyst", "Project Manager", ""]



def test_update_user_me(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    name = "Updated Name"
    email = random_email()
    color = "#11AA33"
    data = {"name": name, "email": email, "color": color}
    r = client.patch(
        f"{settings.API_V1_STR}/current-user",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 200
    json_resp = r.json()
    assert json_resp["code"] == 0
    assert json_resp["data"] is None

    user_query = select(User).where(User.email == email)
    user_db = db.exec(user_query).first()
    assert user_db
    assert user_db.email == email
    assert user_db.name == name
    assert user_db.color == color


def test_update_user_me_invalid_color(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.patch(
        f"{settings.API_V1_STR}/current-user",
        headers=normal_user_token_headers,
        json={"color": "blue"},
    )
    assert r.status_code == 422


def test_update_user_me_null_clears_orcid(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).one()
    user.orcid = "0000-0000-0000-0001"
    db.add(user)
    db.commit()

    r = client.patch(
        f"{settings.API_V1_STR}/current-user",
        headers=normal_user_token_headers,
        json={"orcid": None},
    )

    assert r.status_code == 200
    db.refresh(user)
    assert user.orcid is None


def test_update_user_me_rejects_empty_required_fields(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    for payload in ({"name": "   "}, {"email": None}, {"color": None}):
        r = client.patch(
            f"{settings.API_V1_STR}/current-user",
            headers=normal_user_token_headers,
            json=payload,
        )
        assert r.status_code == 422


def test_update_password_me(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    new_password = random_lower_string()
    data = {
        "current_password": settings.FIRST_SUPERUSER_PASSWORD,
        "new_password": new_password,
    }
    r = client.put(
        f"{settings.API_V1_STR}/current-user/password-credential",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200
    json_resp = r.json()
    assert json_resp["code"] == 0
    json_resp = r.json()
    assert json_resp["code"] == 0
    # updated_user = json_resp["data"] # ApiResponse has no data
    assert json_resp["message"] == "Password updated successfully"

    user_query = select(User).where(User.username == settings.FIRST_SUPERUSER)
    user_db = db.exec(user_query).first()
    assert user_db
    assert user_db.username == settings.FIRST_SUPERUSER
    assert verify_password(new_password, user_db.password)

    # Revert to the old password to keep consistency in test
    old_data = {
        "current_password": new_password,
        "new_password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.put(
        f"{settings.API_V1_STR}/current-user/password-credential",
        headers=superuser_token_headers,
        json=old_data,
    )
    db.refresh(user_db)

    assert r.status_code == 200
    assert verify_password(settings.FIRST_SUPERUSER_PASSWORD, user_db.password)


def test_update_password_me_incorrect_password(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    new_password = random_lower_string()
    data = {"current_password": new_password, "new_password": new_password}
    r = client.put(
        f"{settings.API_V1_STR}/current-user/password-credential",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 400
    updated_user = r.json()
    assert updated_user["message"] == "Incorrect password"


def test_update_user_me_email_exists(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)

    data = {"email": user.email}
    r = client.patch(
        f"{settings.API_V1_STR}/current-user",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 409
    assert r.json()["message"] == "User with this email already exists"


def test_update_password_me_same_password_error(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {
        "current_password": settings.FIRST_SUPERUSER_PASSWORD,
        "new_password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.put(
        f"{settings.API_V1_STR}/current-user/password-credential",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 400
    updated_user = r.json()
    assert (
        updated_user["message"] == "New password cannot be the same as the current one"
    )

def test_update_user(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)

    data = {"name": "Updated_name"}
    r = client.patch(
        f"{settings.API_V1_STR}/users/{user.user_id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200
    json_resp = r.json()
    assert json_resp["code"] == 0
    assert json_resp["data"] is None

    user_query = select(User).where(User.email == user.email)
    user_db = db.exec(user_query).first()
    db.refresh(user_db)
    assert user_db
    assert user_db.name == "Updated_name"


def test_update_user_color(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db, name="Original Name", color="#FFFFFF")

    r = client.patch(
        f"{settings.API_V1_STR}/users/{user.user_id}",
        headers=superuser_token_headers,
        json={"color": "#11aa33"},
    )
    assert r.status_code == 200
    assert r.json()["code"] == 0

    user_db = db.get(User, user.user_id)
    assert user_db
    assert user_db.color == "#11AA33"
    assert user_db.name == "Original Name"


def test_update_user_invalid_color(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)

    r = client.patch(
        f"{settings.API_V1_STR}/users/{user.user_id}",
        headers=superuser_token_headers,
        json={"color": "blue"},
    )
    assert r.status_code == 422


def test_update_user_not_exists(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"name": "Updated_name"}
    r = client.patch(
        f"{settings.API_V1_STR}/users/99999",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 404
    assert r.json()["message"] == "The user with this id does not exist in the system"


def test_update_user_email_exists(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)
    user2 = create_test_user(db)

    data = {"email": user2.email}
    r = client.patch(
        f"{settings.API_V1_STR}/users/{user.user_id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 409
    assert r.json()["message"] == "User with this email already exists"


def test_admin_update_user_password(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """Test admin can update another user's password."""
    old_password = random_lower_string()
    user = create_test_user(db, password=old_password)
    new_password = random_lower_string()

    data = {"new_password": new_password}
    r = client.put(
        f"{settings.API_V1_STR}/users/{user.user_id}/password-credential",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200
    assert r.json()["message"] == "Password updated successfully"

    # Verify password was updated
    user_query = select(User).where(User.user_id == user.user_id)
    user_db = db.exec(user_query).first()
    db.refresh(user_db)
    assert user_db
    assert verify_password(new_password, user_db.password)
    assert not verify_password(old_password, user_db.password)


def test_admin_update_user_password_not_found(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """Test admin updating password for non-existent user returns 404."""
    data = {"new_password": random_lower_string()}
    r = client.put(
        f"{settings.API_V1_STR}/users/99999/password-credential",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 404
    assert r.json()["message"] == "User not found"


def test_admin_update_user_password_without_privileges(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    """Test normal user cannot update another user's password."""
    user = create_test_user(db)
    data = {"new_password": random_lower_string()}
    r = client.put(
        f"{settings.API_V1_STR}/users/{user.user_id}/password-credential",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 403
    assert r.json()["message"] == "Permission required: write access on at least one project or collection"


def test_delete_user_super_user(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)
    user_id = user.user_id
    r = client.delete(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    json_resp = r.json()
    assert json_resp["code"] == 0
    # deleted_user = json_resp["data"] # ApiResponse has no data
    assert json_resp["message"] == "User deleted successfully"
    result = db.exec(select(User).where(User.user_id == user_id)).first()
    assert result is None


def test_delete_user_with_annotation_review_cascades(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)
    user_id = user.user_id

    sound = db.exec(select(SoundClassification)).first()
    if sound is None:
        sound = SoundClassification(
            sound_type=f"sound_{random_lower_string()[:8]}"
        )
        db.add(sound)
        db.commit()
        db.refresh(sound)

    media = Media(
        name=f"delete_user_review_{random_lower_string()[:8]}.wav",
        uploader_id=_superuser_id(db),
        media_type="audio", is_metadata=True,
        date_time=datetime.datetime.now(datetime.UTC),
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    annotation = Annotation(
        media_id=media.media_id,
        sound_id=sound.sound_id,
        creator_id=_superuser_id(db),
        min_x=0.0,
        max_x=1.0,
        min_y=0.0,
        max_y=1000.0,
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)

    status = AnnotationReviewStatus(
        name=f"delete_user_{random_lower_string()[:8]}"
    )
    db.add(status)
    db.commit()
    db.refresh(status)

    db.add(
        AnnotationReview(
            annotation_id=annotation.annotation_id,
            reviewer_id=user_id,
            annotation_review_status_id=status.annotation_review_status_id,
            note="delete user cascade regression",
        )
    )
    db.commit()

    r = client.delete(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert r.json()["message"] == "User deleted successfully"
    assert db.get(User, user_id) is None
    assert db.exec(
        select(AnnotationReview).where(AnnotationReview.reviewer_id == user_id)
    ).first() is None


def test_delete_user_detaches_media_and_cleans_auxiliary_records(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)
    user_id = user.user_id
    admin_id = _superuser_id(db)

    media = Media(
        name=f"delete_user_media_{random_lower_string()[:8]}.wav",
        uploader_id=admin_id,
        creator_id=user_id,
        media_type="audio", is_metadata=True,
        date_time=datetime.datetime.now(datetime.UTC),
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    db.add(
        FileUpload(
            path="/tmp/delete-user-test",
            filename="delete-user-test.wav",
            name="delete-user-test.wav",
            media_id=media.media_id,
            directory=0,
            uploader_id=user_id,
        )
    )
    db.add(
        Task(
            type="review",
            media_id=media.media_id,
            assigner_id=admin_id,
            assignee_id=user_id,
            status="assigned",
        )
    )
    db.add(
        Task(
            type="review",
            media_id=media.media_id,
            assigner_id=user_id,
            assignee_id=admin_id,
            status="assigned",
        )
    )
    db.commit()

    r = client.delete(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert db.get(User, user_id) is None

    db.refresh(media)
    assert media.creator_id is None
    assert db.exec(
        select(FileUpload).where(FileUpload.uploader_id == user_id)
    ).first() is None
    assert db.exec(
        select(Task).where(
            or_(Task.assigner_id == user_id, Task.assignee_id == user_id)
        )
    ).first() is None


def test_delete_user_not_found(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.delete(
        f"{settings.API_V1_STR}/users/99999",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
    assert r.json()["message"] == "User not found"


def test_delete_user_current_super_user_error(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    super_user = user_repository.get_by_username(session=db, username=settings.FIRST_SUPERUSER)
    assert super_user
    user_id = super_user.user_id

    r = client.delete(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 403
    assert r.json()["message"] == "Super users are not allowed to delete themselves"


def test_delete_user_without_privileges(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)

    r = client.delete(
        f"{settings.API_V1_STR}/users/{user.user_id}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403
    assert r.json()["message"] == "Permission required: write access on at least one project or collection"

def test_user_repository_authenticate_by_username(db: Session) -> None:
    password = random_lower_string()
    user = create_test_user(db, password=password)
    
    # Test valid username/password
    auth_user = user_repository.authenticate_by_username(session=db, username=user.username, password=password)
    assert auth_user
    assert auth_user.username == user.username

    # Test invalid username
    auth_user = user_repository.authenticate_by_username(session=db, username="invalid_usr", password=password)
    assert auth_user is None

    # Test invalid password
    auth_user = user_repository.authenticate_by_username(session=db, username=user.username, password="wrong_password")
    assert auth_user is None


def test_user_repository_update_with_password(db: Session) -> None:
    password = random_lower_string()
    user = create_test_user(db, password=password)
    
    # Create an object with a password attribute to run the password hash block in update
    new_password = random_lower_string()
    update_data = UserCreate(
        username=user.username,
        name=user.name,
        email=user.email,
        password=new_password,
        active=user.active
    )
    
    updated_user = user_repository.update(session=db, db_obj=user, obj_in=update_data)
    assert updated_user.user_id == user.user_id
    assert verify_password(new_password, updated_user.password)


def test_set_project_contributor_success(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Create test resources
    user = create_test_user(db)
    owner = create_test_user(db)
    project = Project(name="Test Proj", url="url", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    db.refresh(project)

    data = {"project_id": project.project_id, "contribution_role": "Data Analyst"}
    r = client.put(
        f"{settings.API_V1_STR}/users/{user.user_id}/contributors",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200
    assert r.json()["message"] == "Contributor set successfully"

    # Verify db
    contrib = db.get(ProjectContributor, (project.project_id, user.user_id))
    assert contrib is not None
    assert contrib.contribution_role == "Data Analyst"


def test_set_project_contributor_with_frontend_researcher_role(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)
    owner = create_test_user(db)
    project = Project(name="Research Project", url="url", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    db.refresh(project)

    r = client.put(
        f"{settings.API_V1_STR}/users/{user.user_id}/contributors",
        headers=superuser_token_headers,
        json={"project_id": project.project_id, "contribution_role": "Researcher"},
    )

    assert r.status_code == 200
    contrib = db.get(ProjectContributor, (project.project_id, user.user_id))
    assert contrib is not None
    assert contrib.contribution_role == "Researcher"


def test_set_collection_contributor_success(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Create test resources
    user = create_test_user(db)
    owner = create_test_user(db)
    project = Project(name="Dummy Proj", url="url", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    db.refresh(project)
    
    collection = Collection(name="Test Coll", creator_id=owner.user_id)
    db.add(collection)
    db.commit()
    db.refresh(collection)
    db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
    db.commit()

    # Collection contributor requests are scoped by the project+collection link.
    data = {"project_id": project.project_id, "collection_id": collection.collection_id, "contribution_role": "Field Recorder"}
    r = client.put(
        f"{settings.API_V1_STR}/users/{user.user_id}/contributors",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200

    contrib = db.get(CollectionContributor, (collection.collection_id, user.user_id))
    assert contrib is not None
    assert contrib.contribution_role == "Field Recorder"


def test_set_contributor_not_found(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)
    # Give a non-existent project id
    data = {"project_id": 99999}
    r = client.put(
        f"{settings.API_V1_STR}/users/{user.user_id}/contributors",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 404
    assert r.json()["message"] == "Project not found"


def test_set_contributor_forbidden(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)
    data = {"project_id": 1}
    r = client.put(
        f"{settings.API_V1_STR}/users/{user.user_id}/contributors",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 403


def test_set_contributor_invalid_role(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)
    project = Project(name="Bad Proj", url="url", creator_id=user.user_id)
    db.add(project)
    db.commit()
    
    data = {"project_id": project.project_id, "contribution_role": "Hacker"}
    r = client.put(
        f"{settings.API_V1_STR}/users/{user.user_id}/contributors",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 400
    assert "Invalid contribution role" in r.json()["message"]




def test_remove_project_contributor(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)
    owner = create_test_user(db)
    project = Project(name="Project For Deletion", url="url", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    db.refresh(project)
    
    # Pre-add contributor
    contrib = ProjectContributor(user_id=user.user_id, project_id=project.project_id, contribution_role="Data Analyst")
    db.add(contrib)
    db.commit()

    # Now remove by setting role to None or empty
    data = {"project_id": project.project_id, "contribution_role": ""}
    r = client.put(
        f"{settings.API_V1_STR}/users/{user.user_id}/contributors",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200
    
    deleted_contrib = db.get(ProjectContributor, (project.project_id, user.user_id))
    assert deleted_contrib is None


def test_remove_collection_contributor(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_test_user(db)
    owner = create_test_user(db)
    project = Project(name="Dummy Proj", url="url", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    
    collection = Collection(name="Coll For Deletion", creator_id=owner.user_id)
    db.add(collection)
    db.commit()
    db.refresh(collection)
    db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
    db.commit()

    # Pre-add
    contrib = CollectionContributor(user_id=user.user_id, collection_id=collection.collection_id, contribution_role="Reviewer")
    db.add(contrib)
    db.commit()

    # Remove
    data = {"project_id": project.project_id, "collection_id": collection.collection_id, "contribution_role": None}
    r = client.put(
        f"{settings.API_V1_STR}/users/{user.user_id}/contributors",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200
    
    deleted_contrib = db.get(CollectionContributor, (collection.collection_id, user.user_id))
    assert deleted_contrib is None


def test_manager_update_user_out_of_scope_fails(client: TestClient, db: Session) -> None:
    """A project manager cannot update a user who is not in their project."""
    # 1. Create a manager for Project A
    mgr_pw = random_lower_string()
    mgr = user_repository.create(session=db, obj_in=UserCreate(
        username=random_lower_string()[:20], name="Manager A",
        email=random_email(), password=mgr_pw
    ))
    owner = create_test_user(db)
    proj_a = Project(name="Project A", url="http://a.com", creator_id=owner.user_id)
    db.add(proj_a)
    db.commit()
    db.refresh(proj_a)

    write_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "write"
    )).one()
    db.add(UserPermission(user_id=mgr.user_id, project_id=proj_a.project_id, permission_id=write_perm.permission_id))
    db.commit()

    # 2. Create a user in Project B
    proj_b = Project(name="Project B", url="http://b.com", creator_id=owner.user_id)
    db.add(proj_b)
    db.commit()
    db.refresh(proj_b)

    target_user = create_test_user(db)
    read_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "read"
    )).one()
    db.add(UserPermission(user_id=target_user.user_id, project_id=proj_b.project_id, permission_id=read_perm.permission_id))
    db.commit()

    # 3. Manager A tries to update User in Project B
    headers = user_authentication_headers(client=client, username=mgr.username, password=mgr_pw)
    data = {"name": "Hacked Name"}
    r = client.patch(f"{settings.API_V1_STR}/users/{target_user.user_id}", headers=headers, json=data)

    assert r.status_code == 403
    assert r.json()["message"] == "Target user is not within your management scope"


def test_manager_update_user_color_in_scope_success(client: TestClient, db: Session) -> None:
    """A project manager can update the color of a user who is in their project."""
    mgr_pw = random_lower_string()
    mgr = user_repository.create(session=db, obj_in=UserCreate(
        username=random_lower_string()[:20], name="Manager Color",
        email=random_email(), password=mgr_pw
    ))
    owner = create_test_user(db)
    project = Project(name="Project Color", url="http://color.com", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    db.refresh(project)

    write_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "write"
    )).one()
    read_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "read"
    )).one()
    db.add(UserPermission(user_id=mgr.user_id, project_id=project.project_id, permission_id=write_perm.permission_id))

    target_user = create_test_user(db, color="#FFFFFF")
    db.add(UserPermission(user_id=target_user.user_id, project_id=project.project_id, permission_id=read_perm.permission_id))
    db.commit()

    headers = user_authentication_headers(client=client, username=mgr.username, password=mgr_pw)
    r = client.patch(
        f"{settings.API_V1_STR}/users/{target_user.user_id}",
        headers=headers,
        json={"color": "#abcdef"},
    )

    assert r.status_code == 200
    assert r.json()["code"] == 0
    db.refresh(target_user)
    assert target_user.color == "#ABCDEF"


def test_manager_update_user_color_out_of_scope_fails(client: TestClient, db: Session) -> None:
    """A project manager cannot update the color of a user outside their project."""
    mgr_pw = random_lower_string()
    mgr = user_repository.create(session=db, obj_in=UserCreate(
        username=random_lower_string()[:20], name="Manager Color Out",
        email=random_email(), password=mgr_pw
    ))
    owner = create_test_user(db)
    proj_a = Project(name="Project Color A", url="http://color-a.com", creator_id=owner.user_id)
    proj_b = Project(name="Project Color B", url="http://color-b.com", creator_id=owner.user_id)
    db.add(proj_a)
    db.add(proj_b)
    db.commit()
    db.refresh(proj_a)
    db.refresh(proj_b)

    write_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "write"
    )).one()
    read_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "read"
    )).one()
    db.add(UserPermission(user_id=mgr.user_id, project_id=proj_a.project_id, permission_id=write_perm.permission_id))

    target_user = create_test_user(db, color="#FFFFFF")
    db.add(UserPermission(user_id=target_user.user_id, project_id=proj_b.project_id, permission_id=read_perm.permission_id))
    db.commit()

    headers = user_authentication_headers(client=client, username=mgr.username, password=mgr_pw)
    r = client.patch(
        f"{settings.API_V1_STR}/users/{target_user.user_id}",
        headers=headers,
        json={"color": "#123456"},
    )

    assert r.status_code == 403
    assert r.json()["message"] == "Target user is not within your management scope"
    db.refresh(target_user)
    assert target_user.color == "#FFFFFF"


def test_manager_reset_admin_password_fails(client: TestClient, db: Session) -> None:
    """A manager cannot reset an admin's password."""
    # 1. Create a manager
    mgr_pw = random_lower_string()
    mgr = user_repository.create(session=db, obj_in=UserCreate(
        username=random_lower_string()[:20], name="Manager X",
        email=random_email(), password=mgr_pw
    ))
    owner = create_test_user(db)
    proj = Project(name="Shared Project", url="http://shared.com", creator_id=owner.user_id)
    db.add(proj)
    db.commit()
    db.refresh(proj)

    write_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "write"
    )).one()
    db.add(UserPermission(user_id=mgr.user_id, project_id=proj.project_id, permission_id=write_perm.permission_id))
    db.commit()

    # 2. Identify an Admin user (superuser role_id=1)
    admin_user = db.exec(select(User).where(User.username == settings.FIRST_SUPERUSER)).one()

    # 3. Manager tries to reset Admin password
    headers = user_authentication_headers(client=client, username=mgr.username, password=mgr_pw)
    data = {"new_password": "newpassword123"}
    r = client.put(f"{settings.API_V1_STR}/users/{admin_user.user_id}/password-credential", headers=headers, json=data)

    assert r.status_code == 403
    assert r.json()["message"] == "Managers are not allowed to manage Administrator accounts"


def test_read_users_filter_project_includes_admin(
    client: TestClient, superuser_token_headers: dict, db: Session
) -> None:
    """GET /users?project_id={id} should include system administrators."""
    # 1. Create a project
    owner = create_test_user(db)
    project = Project(name="Filter Test Proj", url="http://test.com", creator_id=owner.user_id)
    db.add(project)
    db.commit()
    db.refresh(project)

    # 2. Assign a normal user to the project
    user = create_test_user(db)
    read_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "read"
    )).one()
    db.add(UserPermission(user_id=user.user_id, project_id=project.project_id, permission_id=read_perm.permission_id))
    db.commit()

    # 3. Call API with project_id filter
    r = client.get(
        f"{settings.API_V1_STR}/users?project_id={project.project_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    
    # Check that both the assigned user and the admin (current user) are in the list
    user_ids = [u["user_id"] for u in data]
    assert user.user_id in user_ids
    
    # Find at least one admin (role_id=1)
    admin = db.exec(select(User).where(User.role_id == 1)).first()
    assert admin is not None
    assert admin.user_id in user_ids

def test_manager_delete_user_in_scope_success(client: TestClient, db: Session) -> None:
    """A project manager can delete a user who is in their project."""
    # 1. Create a manager
    mgr_pw = "mgrpass123"
    mgr = user_repository.create(session=db, obj_in=UserCreate(
        username="mgr_del_scope", name="Manager Del",
        email="mgrdel@e.com", password=mgr_pw
    ))
    owner = create_test_user(db)
    proj = Project(name="Delete Scope Proj", url="http://ds.com", creator_id=owner.user_id)
    db.add(proj)
    db.commit()
    db.refresh(proj)

    write_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "write"
    )).one()
    db.add(UserPermission(user_id=mgr.user_id, project_id=proj.project_id, permission_id=write_perm.permission_id))
    db.commit()

    # 2. Create a target user in that project
    target_user = create_test_user(db)
    read_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "read"
    )).one()
    db.add(UserPermission(user_id=target_user.user_id, project_id=proj.project_id, permission_id=read_perm.permission_id))
    db.commit()

    # 3. Manager deletes Target User
    headers = user_authentication_headers(client=client, username=mgr.username, password=mgr_pw)
    r = client.delete(f"{settings.API_V1_STR}/users/{target_user.user_id}", headers=headers)

    assert r.status_code == 200
    assert r.json()["message"] == "User deleted successfully"
    assert db.get(User, target_user.user_id) is None


def test_manager_delete_user_out_of_scope_fails(client: TestClient, db: Session) -> None:
    """A manager cannot delete a user who is not in their management scope."""
    mgr_pw = "mgrpass456"
    mgr = user_repository.create(session=db, obj_in=UserCreate(
        username="mgr_del_out", name="Mgr Out",
        email="mgr_out@e.com", password=mgr_pw
    ))
    owner = create_test_user(db)
    proj = Project(name="Mgr Scope", url="h", creator_id=owner.user_id)
    db.add(proj)
    db.commit()
    db.refresh(proj)
    
    write_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "write"
    )).one()
    db.add(UserPermission(user_id=mgr.user_id, project_id=proj.project_id, permission_id=write_perm.permission_id))
    db.commit()

    # Target user in NO project (or a different one)
    target_user = create_test_user(db)

    headers = user_authentication_headers(client=client, username=mgr.username, password=mgr_pw)
    r = client.delete(f"{settings.API_V1_STR}/users/{target_user.user_id}", headers=headers)

    assert r.status_code == 403
    assert r.json()["message"] == "Target user is not within your management scope"


def test_manager_delete_admin_fails(client: TestClient, db: Session) -> None:
    """A manager cannot delete an administrator."""
    mgr_pw = "mgrpass789"
    mgr = user_repository.create(session=db, obj_in=UserCreate(
        username="mgr_del_admin", name="Mgr Admin",
        email="mgr_admin@e.com", password=mgr_pw
    ))
    owner = create_test_user(db)
    proj = Project(name="Shared", url="h", creator_id=owner.user_id)
    db.add(proj)
    db.commit()
    db.refresh(proj)
    
    write_perm = db.exec(select(Permission).where(
        Permission.resource_type == "project", Permission.action == "write"
    )).one()
    db.add(UserPermission(user_id=mgr.user_id, project_id=proj.project_id, permission_id=write_perm.permission_id))
    db.commit()

    admin = db.exec(select(User).where(User.username == settings.FIRST_SUPERUSER)).one()

    headers = user_authentication_headers(client=client, username=mgr.username, password=mgr_pw)
    r = client.delete(f"{settings.API_V1_STR}/users/{admin.user_id}", headers=headers)

    assert r.status_code == 403
    assert r.json()["message"] == "Managers are not allowed to manage Administrator accounts"


# ---------------------------------------------------------------------------
# Tests for PATCH /current-user/preferences
# ---------------------------------------------------------------------------

def test_update_preference_fft(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    """User can update their FFT preference."""
    r = client.patch(
        f"{settings.API_V1_STR}/current-user/preferences",
        headers=normal_user_token_headers,
        json={"fft": 2048},
    )
    assert r.status_code == 200
    assert r.json()["data"] is None
    pref = db.get(UserPreference, _normal_test_user_id(db))
    assert pref is not None
    assert pref.fft == 2048


def test_update_preference_invalid_fft(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """FFT value must be one of the allowed sizes."""
    r = client.patch(
        f"{settings.API_V1_STR}/current-user/preferences",
        headers=normal_user_token_headers,
        json={"fft": 300},
    )
    assert r.status_code == 422


@pytest.mark.parametrize("theme", ["light", "dark", "auto"])
def test_update_preference_theme(
    theme: str,
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    """User can update every supported theme preference."""
    r = client.patch(
        f"{settings.API_V1_STR}/current-user/preferences",
        headers=normal_user_token_headers,
        json={"theme": theme},
    )
    assert r.status_code == 200
    assert r.json()["data"] is None
    pref = db.get(UserPreference, _normal_test_user_id(db))
    assert pref is not None
    assert pref.theme == theme


@pytest.mark.parametrize("theme", ["system", "unknown", "a" * 21])
def test_update_preference_rejects_invalid_theme(
    theme: str,
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    """Theme preference only accepts the documented values."""
    r = client.patch(
        f"{settings.API_V1_STR}/current-user/preferences",
        headers=normal_user_token_headers,
        json={"theme": theme},
    )
    assert r.status_code == 422


def test_update_preference_defaults_theme_to_auto(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    """Creating a preference without a theme uses auto."""
    user_id = _normal_test_user_id(db)
    pref = db.get(UserPreference, user_id)
    if pref is not None:
        db.delete(pref)
        db.commit()

    r = client.patch(
        f"{settings.API_V1_STR}/current-user/preferences",
        headers=normal_user_token_headers,
        json={"fft": 2048},
    )
    assert r.status_code == 200
    created_pref = db.get(UserPreference, user_id)
    assert created_pref is not None
    assert created_pref.theme == "auto"


def test_update_preference_multiple_fields(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    """User can update multiple preference fields in one request."""
    r = client.patch(
        f"{settings.API_V1_STR}/current-user/preferences",
        headers=normal_user_token_headers,
        json={"fft": 512, "language": "zh", "notifications_enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["data"] is None
    pref = db.get(UserPreference, _normal_test_user_id(db))
    assert pref is not None
    assert pref.fft == 512
    assert pref.language == "zh"
    assert pref.notifications_enabled is False


def test_update_preference_upsert(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    """Calling preference update twice keeps the latest value (upsert)."""
    client.patch(
        f"{settings.API_V1_STR}/current-user/preferences",
        headers=normal_user_token_headers,
        json={"fft": 1024},
    )
    r = client.patch(
        f"{settings.API_V1_STR}/current-user/preferences",
        headers=normal_user_token_headers,
        json={"fft": 4096},
    )
    assert r.status_code == 200
    assert r.json()["data"] is None
    pref = db.get(UserPreference, _normal_test_user_id(db))
    assert pref is not None
    assert pref.fft == 4096


def test_update_preference_requires_login(client: TestClient) -> None:
    """Unauthenticated request is rejected."""
    r = client.patch(
        f"{settings.API_V1_STR}/current-user/preferences",
        json={"fft": 512},
    )
    assert r.status_code == 401


def test_preference_reflected_in_me(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """After updating, GET /current-user returns the updated preference."""
    client.patch(
        f"{settings.API_V1_STR}/current-user/preferences",
        headers=normal_user_token_headers,
        json={"fft": 256},
    )
    r = client.get(
        f"{settings.API_V1_STR}/current-user",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    pref = r.json()["data"]["preference"]
    assert pref is not None
    assert pref["fft"] == 256


CURRENT_USER_PERMISSIONS_URL = f"{settings.API_V1_STR}/current-user/permissions"

ALL_PERMISSION_NAMES = {
    "project:read", "project:write",
    "collection:read", "collection:write",
    "audio:read", "audio:write",
    "site:read", "site:write",
    "annotation:read", "annotation:write",
    "review:read", "review:write",
}


def _permissions_url(project_id: int | None = None, collection_id: int | None = None) -> str:
    params = []
    if project_id is not None:
        params.append(f"project_id={project_id}")
    if collection_id is not None:
        params.append(f"collection_id={collection_id}")
    return f"{CURRENT_USER_PERMISSIONS_URL}{'?' + '&'.join(params) if params else ''}"


def _get_permissions(client: TestClient, url: str, headers: dict[str, str] | None = None) -> set[str]:
    response = client.get(url, headers=headers or {})
    assert response.status_code == 200
    return set(response.json()["data"]["permissions"])


def test_current_user_permissions_admin_gets_every_permission(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db, owner, project_name="Perm Admin Project", collection_name="Perm Admin Collection"
    )

    response = client.get(
        _permissions_url(project.project_id, collection.collection_id),
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_admin"] is True
    assert set(data["permissions"]) == ALL_PERMISSION_NAMES


def test_current_user_permissions_project_write_expands_to_collection_scope(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    manager = db.get(User, _normal_test_user_id(db))
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db, owner, project_name="Perm Write Project", collection_name="Perm Write Collection"
    )
    _grant_permission(db, manager, "project", "write", project_id=project.project_id)

    permissions = _get_permissions(
        client,
        _permissions_url(project.project_id, collection.collection_id),
        normal_user_token_headers,
    )

    assert {"project:write", "collection:write", "review:write", "audio:write"} <= permissions


def test_current_user_permissions_review_read_does_not_grant_write(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    """Issue #71: a review:read user must not be told they can edit reviews."""
    reader = db.get(User, _normal_test_user_id(db))
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db, owner, project_name="Perm Read Project", collection_name="Perm Read Collection"
    )
    _grant_permission(
        db,
        reader,
        "review",
        "read",
        project_id=project.project_id,
        collection_id=collection.collection_id,
    )

    permissions = _get_permissions(
        client,
        _permissions_url(project.project_id, collection.collection_id),
        normal_user_token_headers,
    )

    assert "review:read" in permissions
    assert "review:write" not in permissions


def test_current_user_permissions_are_scoped_to_the_requested_collection(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    user = db.get(User, _normal_test_user_id(db))
    owner = create_test_user(db)
    project, writable_collection = _create_project_with_collection(
        db, owner, project_name="Perm Scope Project", collection_name="Perm Scope Writable"
    )
    other_collection = Collection(name="Perm Scope Other", creator_id=owner.user_id)
    db.add(other_collection)
    db.commit()
    db.refresh(other_collection)
    db.add(ProjectCollection(
        project_id=project.project_id,
        collection_id=other_collection.collection_id,
    ))
    db.commit()
    _grant_permission(
        db,
        user,
        "review",
        "write",
        project_id=project.project_id,
        collection_id=writable_collection.collection_id,
    )

    writable = _get_permissions(
        client,
        _permissions_url(project.project_id, writable_collection.collection_id),
        normal_user_token_headers,
    )
    other = _get_permissions(
        client,
        _permissions_url(project.project_id, other_collection.collection_id),
        normal_user_token_headers,
    )
    project_wide = _get_permissions(
        client,
        _permissions_url(project.project_id),
        normal_user_token_headers,
    )

    assert "review:write" in writable
    assert "review:write" not in other
    # Project-only scope contains only grants that apply across the whole project.
    assert "review:write" not in project_wide


def test_current_user_permissions_ignores_collection_without_project(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    user = db.get(User, _normal_test_user_id(db))
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db, owner, project_name="Perm Loose Project", collection_name="Perm Loose Collection"
    )
    _grant_permission(
        db,
        user,
        "review",
        "write",
        project_id=project.project_id,
        collection_id=collection.collection_id,
    )

    response = client.get(
        f"{CURRENT_USER_PERMISSIONS_URL}?collection_id={collection.collection_id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["project_id"] is None
    assert data["collection_id"] is None
    assert set(data["permissions"]) == set()


def test_current_user_permissions_without_grants_is_empty(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db, owner, project_name="Perm Empty Project", collection_name="Perm Empty Collection"
    )
    project.public = False
    db.add(project)
    db.commit()

    permissions = _get_permissions(
        client,
        _permissions_url(project.project_id, collection.collection_id),
        normal_user_token_headers,
    )

    assert permissions == set()


def test_current_user_permissions_public_project_alone_grants_only_project_read(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    """A public project exposes itself, never the collections beneath it."""
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db, owner, project_name="Perm Shallow Project", collection_name="Perm Shallow Collection"
    )
    assert project.public is True
    assert collection.public_access is False

    permissions = _get_permissions(
        client,
        _permissions_url(project.project_id, collection.collection_id),
        normal_user_token_headers,
    )

    assert permissions == {"project:read"}


def test_current_user_permissions_anonymous_gets_public_reads_only(
    client: TestClient, db: Session
) -> None:
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db, owner, project_name="Perm Public Project", collection_name="Perm Public Collection"
    )
    project.public = True
    collection.public_access = True
    collection.public_tags = True
    db.add(project)
    db.add(collection)
    db.commit()

    permissions = _get_permissions(
        client,
        _permissions_url(project.project_id, collection.collection_id),
    )

    assert permissions == {
        "project:read",
        "collection:read",
        "audio:read",
        "site:read",
        "annotation:read",
    }


def test_current_user_permissions_anonymous_on_private_project_is_empty(
    client: TestClient, db: Session
) -> None:
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db, owner, project_name="Perm Private Project", collection_name="Perm Private Collection"
    )
    project.public = False
    db.add(project)
    db.commit()

    response = client.get(_permissions_url(project.project_id, collection.collection_id))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_admin"] is False
    assert data["permissions"] == []


def test_current_user_permissions_public_tags_off_hides_annotation_read(
    client: TestClient, db: Session
) -> None:
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db, owner, project_name="Perm Tagless Project", collection_name="Perm Tagless Collection"
    )
    project.public = True
    collection.public_access = True
    collection.public_tags = False
    db.add(project)
    db.add(collection)
    db.commit()

    permissions = _get_permissions(
        client,
        _permissions_url(project.project_id, collection.collection_id),
    )

    assert "annotation:read" not in permissions
    assert {"collection:read", "audio:read", "site:read"} <= permissions


def test_current_user_permissions_public_read_never_implies_write(
    client: TestClient, db: Session
) -> None:
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db, owner, project_name="Perm NoWrite Project", collection_name="Perm NoWrite Collection"
    )
    project.public = True
    collection.public_access = True
    collection.public_tags = True
    db.add(project)
    db.add(collection)
    db.commit()

    permissions = _get_permissions(
        client,
        _permissions_url(project.project_id, collection.collection_id),
    )

    assert not any(name.endswith(":write") for name in permissions)


def test_current_user_permissions_echoes_requested_scope(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    owner = create_test_user(db)
    project, collection = _create_project_with_collection(
        db, owner, project_name="Perm Echo Project", collection_name="Perm Echo Collection"
    )

    response = client.get(
        _permissions_url(project.project_id, collection.collection_id),
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["project_id"] == project.project_id
    assert data["collection_id"] == collection.collection_id
