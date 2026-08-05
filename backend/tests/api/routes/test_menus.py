"""
Menus API routes tests.

This module contains tests for the menus API endpoints.
"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import create_access_token
from app.models import Collection, Permission, Role, User, UserPermission
from app.models.project import Project, ProjectCollection
from tests.utils.utils import random_lower_string

CURRENT_USER_MENU_URL = f"{settings.API_V1_STR}/current-user/menu-items"
EXPECTED_MENU_ORDER = [
    "Projects",
    "Collections",
    "Users",
    "Audios",
    "Photos",
    "Sites",
    "Annotations",
    "Reviews",
    "Tasks",
    "Queue",
    "Index Logs",
]


def _headers_for_user(user: User) -> dict[str, str]:
    token = create_access_token(user.user_id, expires_delta=timedelta(minutes=30))
    return {"Authorization": f"Bearer {token}"}


def _create_user(db: Session) -> User:
    role = db.exec(select(Role).where(Role.name == "User")).one()
    user = User(
        role_id=role.role_id,
        username=f"menu_{random_lower_string()[:8]}",
        password="hashed",
        name="Menu User",
        email=f"{random_lower_string()[:8]}@menu.test",
        active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_project(db: Session, user_id: int) -> Project:
    project = Project(
        name=f"proj_{random_lower_string()[:8]}",
        url="https://test.example.com",
        creator_id=user_id,
        public=False,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _create_collection(db: Session, user_id: int) -> Collection:
    collection = Collection(
        name=f"col_{random_lower_string()[:8]}",
        creator_id=user_id,
        public_access=False,
    )
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


def _link_project_collection(db: Session, project: Project, collection: Collection) -> None:
    db.add(
        ProjectCollection(
            project_id=project.project_id,
            collection_id=collection.collection_id,
        )
    )
    db.commit()


def _grant_project_permission(
    db: Session,
    user: User,
    project: Project,
    permission_name: str,
) -> None:
    permission = db.exec(select(Permission).where(Permission.name == permission_name)).one()
    db.add(
        UserPermission(
            user_id=user.user_id,
            project_id=project.project_id,
            permission_id=permission.permission_id,
        )
    )
    db.commit()


def _grant_collection_permission(
    db: Session,
    user: User,
    collection: Collection,
    permission_name: str,
) -> Project:
    project = _create_project(db, collection.creator_id)
    _link_project_collection(db, project, collection)
    permission = db.exec(select(Permission).where(Permission.name == permission_name)).one()
    db.add(
        UserPermission(
            user_id=user.user_id,
            project_id=project.project_id,
            collection_id=collection.collection_id,
            permission_id=permission.permission_id,
        )
    )
    db.commit()
    return project


def _visible_map(response_json: dict) -> dict[str, bool]:
    return {item["name"]: item["visible"] for item in response_json["data"]}


def _visible_names(response_json: dict) -> set[str]:
    return {name for name, visible in _visible_map(response_json).items() if visible}


def _menu_url(project_id: int) -> str:
    return f"{CURRENT_USER_MENU_URL}?project_id={project_id}"


def _menu_url_with_collection(project_id: int, collection_id: int) -> str:
    return f"{CURRENT_USER_MENU_URL}?project_id={project_id}&collection_id={collection_id}"




class TestCurrentUserMenuItems:
    """Tests for GET /current-user/menu-items endpoint."""

    def test_anonymous_returns_401(self, client: TestClient) -> None:
        r = client.get(_menu_url(1))

        assert r.status_code == 401

    def test_admin_with_collection_sees_all_menus(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        user = _create_user(db)
        project = _create_project(db, user.user_id)
        collection = _create_collection(db, user.user_id)
        _link_project_collection(db, project, collection)

        r = client.get(_menu_url(project.project_id), headers=superuser_token_headers)

        assert r.status_code == 200
        body = r.json()
        assert [item["name"] for item in body["data"]] == EXPECTED_MENU_ORDER
        assert _visible_names(body) == set(EXPECTED_MENU_ORDER)

    def test_admin_without_collection_only_sees_base_and_system_menus(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        user = _create_user(db)
        project = _create_project(db, user.user_id)

        r = client.get(_menu_url(project.project_id), headers=superuser_token_headers)

        assert r.status_code == 200
        assert _visible_names(r.json()) == {
            "Projects",
            "Collections",
            "Queue",
            "Index Logs",
        }

    @pytest.mark.parametrize(
        ("permission_name", "visible_menus"),
        [
            ("audio:read", {"Audios", "Photos"}),
            ("site:read", {"Sites"}),
            ("annotation:read", {"Annotations"}),
            ("review:read", {"Reviews"}),
        ],
    )
    def test_single_read_permission_only_shows_matching_data_menu(
        self,
        client: TestClient,
        db: Session,
        permission_name: str,
        visible_menus: set[str],
    ) -> None:
        user = _create_user(db)
        collection = _create_collection(db, user.user_id)
        project = _grant_collection_permission(db, user, collection, permission_name)

        r = client.get(_menu_url(project.project_id), headers=_headers_for_user(user))

        assert r.status_code == 200
        assert _visible_names(r.json()) == visible_menus | {"Queue", "Index Logs"}

    @pytest.mark.parametrize("permission_name", ["audio:write", "review:write"])
    def test_task_menu_requires_audio_or_review_write(
        self,
        client: TestClient,
        db: Session,
        permission_name: str,
    ) -> None:
        user = _create_user(db)
        collection = _create_collection(db, user.user_id)
        project = _grant_collection_permission(db, user, collection, permission_name)

        r = client.get(_menu_url(project.project_id), headers=_headers_for_user(user))

        assert r.status_code == 200
        visible = _visible_names(r.json())
        assert "Tasks" in visible
        assert "Queue" in visible
        assert "Index Logs" in visible

    def test_admin_with_project_id_hides_collection_scoped_menus_when_project_has_no_collections(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        user = _create_user(db)
        project = _create_project(db, user.user_id)
        other_collection = _create_collection(db, user.user_id)
        other_project = _create_project(db, user.user_id)
        _link_project_collection(db, other_project, other_collection)

        r = client.get(
            _menu_url(project.project_id),
            headers=superuser_token_headers,
        )

        assert r.status_code == 200
        assert _visible_names(r.json()) == {
            "Projects",
            "Collections",
            "Queue",
            "Index Logs",
        }

    def test_project_write_with_project_id_hides_collection_scoped_menus_when_project_has_no_collections(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        user = _create_user(db)
        project = _create_project(db, user.user_id)
        _grant_project_permission(db, user, project, "project:write")

        r = client.get(_menu_url(project.project_id), headers=_headers_for_user(user))

        assert r.status_code == 200
        assert _visible_names(r.json()) == {
            "Projects",
            "Collections",
            "Queue",
            "Index Logs",
        }

    def test_project_write_with_project_id_and_collection_shows_all_menus(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        user = _create_user(db)
        project = _create_project(db, user.user_id)
        collection = _create_collection(db, user.user_id)
        _link_project_collection(db, project, collection)
        _grant_project_permission(db, user, project, "project:write")

        r = client.get(_menu_url(project.project_id), headers=_headers_for_user(user))

        assert r.status_code == 200
        assert _visible_names(r.json()) == set(EXPECTED_MENU_ORDER)

    def test_project_id_hides_collection_scoped_menus_when_access_is_only_in_other_project(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        user = _create_user(db)
        target_project = _create_project(db, user.user_id)
        other_collection = _create_collection(db, user.user_id)
        _grant_collection_permission(db, user, other_collection, "audio:read")

        r = client.get(_menu_url(target_project.project_id), headers=_headers_for_user(user))

        assert r.status_code == 200
        assert _visible_names(r.json()) == {"Queue", "Index Logs"}

    def test_project_write_on_other_project_hides_manage_menus_for_target_project(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        user = _create_user(db)
        project_a = _create_project(db, user.user_id)
        project_b = _create_project(db, user.user_id)
        _grant_project_permission(db, user, project_a, "project:write")

        r = client.get(_menu_url(project_b.project_id), headers=_headers_for_user(user))

        assert r.status_code == 200
        visible = _visible_names(r.json())
        assert "Projects" not in visible
        assert "Collections" not in visible
        assert "Users" not in visible

    def test_collection_write_with_project_id_only_hides_collection_and_user_menus(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        user = _create_user(db)
        project = _create_project(db, user.user_id)
        collection = _create_collection(db, user.user_id)
        _link_project_collection(db, project, collection)
        permission = db.exec(select(Permission).where(Permission.name == "collection:write")).one()
        db.add(UserPermission(
            user_id=user.user_id,
            project_id=project.project_id,
            collection_id=collection.collection_id,
            permission_id=permission.permission_id,
        ))
        db.commit()

        r = client.get(_menu_url(project.project_id), headers=_headers_for_user(user))

        assert r.status_code == 200
        visible = _visible_names(r.json())
        assert "Projects" not in visible
        assert "Collections" not in visible
        assert "Users" not in visible
        assert {
            "Audios",
            "Photos",
            "Sites",
            "Annotations",
            "Reviews",
            "Tasks",
            "Queue",
            "Index Logs",
        }.issubset(visible)

    def test_collection_write_on_selected_collection_shows_collection_and_user_menus(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        user = _create_user(db)
        project = _create_project(db, user.user_id)
        collection = _create_collection(db, user.user_id)
        _link_project_collection(db, project, collection)
        permission = db.exec(select(Permission).where(Permission.name == "collection:write")).one()
        db.add(UserPermission(
            user_id=user.user_id,
            project_id=project.project_id,
            collection_id=collection.collection_id,
            permission_id=permission.permission_id,
        ))
        db.commit()

        r = client.get(
            _menu_url_with_collection(project.project_id, collection.collection_id),
            headers=_headers_for_user(user),
        )

        assert r.status_code == 200
        visible = _visible_names(r.json())
        assert "Projects" not in visible
        assert "Collections" in visible
        assert "Users" in visible

    def test_collection_write_on_other_collection_hides_collection_and_user_menus_for_selected_collection(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        user = _create_user(db)
        project = _create_project(db, user.user_id)
        writable_collection = _create_collection(db, user.user_id)
        selected_collection = _create_collection(db, user.user_id)
        _link_project_collection(db, project, writable_collection)
        _link_project_collection(db, project, selected_collection)
        permission = db.exec(select(Permission).where(Permission.name == "collection:write")).one()
        db.add(UserPermission(
            user_id=user.user_id,
            project_id=project.project_id,
            collection_id=writable_collection.collection_id,
            permission_id=permission.permission_id,
        ))
        db.commit()

        r = client.get(
            _menu_url_with_collection(project.project_id, selected_collection.collection_id),
            headers=_headers_for_user(user),
        )

        assert r.status_code == 200
        visible = _visible_names(r.json())
        assert "Projects" not in visible
        assert "Collections" not in visible
        assert "Users" not in visible

    def test_project_write_on_selected_collection_shows_collection_and_user_menus(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        user = _create_user(db)
        project = _create_project(db, user.user_id)
        collection = _create_collection(db, user.user_id)
        _link_project_collection(db, project, collection)
        _grant_project_permission(db, user, project, "project:write")

        r = client.get(
            _menu_url_with_collection(project.project_id, collection.collection_id),
            headers=_headers_for_user(user),
        )

        assert r.status_code == 200
        visible = _visible_names(r.json())
        assert "Projects" in visible
        assert "Collections" in visible
        assert "Users" in visible

    def test_regular_user_without_permission_only_sees_system_menus(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        user = _create_user(db)
        project = _create_project(db, user.user_id)

        r = client.get(_menu_url(project.project_id), headers=_headers_for_user(user))

        assert r.status_code == 200
        assert _visible_names(r.json()) == {"Queue", "Index Logs"}

    def test_response_has_fixed_order_and_no_numeric_fields(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        user = _create_user(db)
        project = _create_project(db, user.user_id)

        r = client.get(_menu_url(project.project_id), headers=_headers_for_user(user))

        assert r.status_code == 200
        items = r.json()["data"]
        assert [item["name"] for item in items] == EXPECTED_MENU_ORDER
        assert all("visible" in item for item in items)
        assert all("id" not in item and "order" not in item for item in items)
