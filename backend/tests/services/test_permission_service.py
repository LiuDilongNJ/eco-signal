"""Unit tests for PermissionService (comprehensive)."""
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Collection, Project, Role, User
from app.models.project import ProjectCollection
from app.services import permission_service


def test_normalize_permissions_extended():
    """Test all branches of _normalize_permissions."""
    # Empty case
    assert permission_service._normalize_permissions([], "project") == []

    # Sub-resource present -> adds scope:read
    res = permission_service._normalize_permissions(["audio:read"], "project")
    assert "audio:read" in res
    assert "project:read" in res

    # project:write case
    res = permission_service._normalize_permissions(["project:write", "audio:read"], "project")
    assert "project:write" in res
    assert "audio:read" not in res
    assert "project:read" not in res

def test_remove_cross_scope_redundancies_extended():
    """Test _remove_cross_scope_redundancies edge cases."""
    # project:write covers all
    assert permission_service._remove_cross_scope_redundancies(["audio:read"], {"project:write"}) == []

    # parent has audio:write, collection has audio:read -> redundant
    assert permission_service._remove_cross_scope_redundancies(["audio:read"], {"audio:write"}) == []

    # parent has audio:read, collection has audio:read -> redundant
    assert permission_service._remove_cross_scope_redundancies(["audio:read"], {"audio:read"}) == []

    # parent has site:read, collection has audio:read -> NOT redundant
    assert permission_service._remove_cross_scope_redundancies(["audio:read"], {"site:read"}) == ["audio:read"]

class TestPermissionServiceComprehensive:
    """Integration tests for high coverage."""

    @pytest.fixture
    def setup_data(self, db: Session):
        admin_role = db.exec(select(Role).where(Role.name == settings.ADMIN_ROLE_NAME)).first()
        if not admin_role:
            admin_role = Role(name=settings.ADMIN_ROLE_NAME)
            db.add(admin_role)

        user_role_name = "User_" + str(datetime.now().timestamp())
        user_role = Role(name=user_role_name)
        db.add_all([user_role])
        db.flush()

        admin = User(username="admin_ps", role_id=admin_role.role_id, email="ap@e.com", password="p", name="A")
        user = User(username="user_ps", role_id=user_role.role_id, email="up@e.com", password="p", name="U")
        db.add_all([admin, user])
        db.flush()
        db.refresh(admin)
        db.refresh(user)
        return {"admin": admin, "user": user}

    def test_anonymous_access(self, db: Session, setup_data):
        p = Project(name="PubP", creator_id=setup_data["admin"].user_id, public=True, url="h")
        c = Collection(name="PubC", creator_id=setup_data["admin"].user_id, public_access=True)
        db.add_all([p, c])
        db.flush()
        db.add(ProjectCollection(project_id=p.project_id, collection_id=c.collection_id))
        db.flush()

        assert permission_service.can_access_project(db, None, p.project_id) is True
        assert permission_service.can_access_collection(db, None, p.project_id, c.collection_id) is True

        # Non-existent
        assert permission_service.can_access_project(db, None, 9999) is False
        assert permission_service.can_access_collection(db, None, p.project_id, 9999) is False


    def test_sync_user_permissions_global_full(self, db: Session, setup_data):
        admin = setup_data["admin"]
        user = setup_data["user"]
        p = Project(name="PG", creator_id=admin.user_id, url="h")
        db.add(p)
        db.flush()

        # Mocking for sync_user_permissions_global
        class MockRequest:
            def __init__(self, is_admin=None, projects=None):
                self.is_admin = is_admin
                self.projects = projects or []

        # Test admin toggle
        req = MockRequest(is_admin=True, projects=[])
        permission_service.sync_user_permissions_global(db, user.user_id, req, current_user=admin)
        db.refresh(user)
        assert user.role_id == 1  # Superuser

        req = MockRequest(is_admin=False, projects=[])
        permission_service.sync_user_permissions_global(db, user.user_id, req, current_user=admin)
        db.refresh(user)
        assert user.role_id != 1

"""
Tests for permission system fixes.

Covers:
- UniqueConstraint partial unique index behavior
- sync_user_permissions now calls _normalize_permissions
- index_log_service uses collection:write instead of collection:read
- analysis.py uses collection:write instead of index_log:write
"""
import datetime as datetime_module

import pytest
from sqlmodel import Session, select

from app.models import Permission, UserPermission, Role
from app.models.collection import Collection
from app.models.effective_permission import UserEffectivePermission
from app.models.index import IndexLog, IndexType
from app.models.media import Media, MediaCollection
from app.models.project import Project, ProjectCollection
from app.models.user import User
from app.repositories.permission_repository import permission_repository
from tests.utils.utils import random_lower_string


# ─── DB helpers ─────────────────────────────────────────────────────────────

def _create_user(db: Session) -> User:
    role = db.exec(select(Role).where(Role.name == "User")).first()
    user = User(
        role_id=role.role_id,
        username=f"u_{random_lower_string()[:8]}",
        password="hashed",
        name="Test User",
        email=f"{random_lower_string()[:8]}@test.com",
        active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_collection(db: Session, owner_id: int) -> Collection:
    col = Collection(
        name=f"col_{random_lower_string()[:8]}",
        creator_id=owner_id,
    )
    db.add(col)
    db.commit()
    db.refresh(col)
    return col


def _create_project(db: Session, owner_id: int) -> Project:
    project = Project(
        name=f"proj_{random_lower_string()[:8]}",
        creator_id=owner_id,
        url="http://test-project",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _ensure_project_for_collection(db: Session, collection_id: int, owner_id: int) -> int:
    project_ids = list(
        db.exec(
            select(ProjectCollection.project_id).where(ProjectCollection.collection_id == collection_id)
        ).all()
    )
    if project_ids:
        return project_ids[0]

    project = _create_project(db, owner_id=owner_id)
    db.add(ProjectCollection(project_id=project.project_id, collection_id=collection_id))
    db.commit()
    return project.project_id


def _grant_collection_perm(db: Session, user_id: int, collection_id: int, perm_name: str) -> None:
    perm = db.exec(select(Permission).where(Permission.name == perm_name)).one()
    collection = db.get(Collection, collection_id)
    assert collection is not None
    project_id = _ensure_project_for_collection(db, collection_id, collection.creator_id)
    db.add(
        UserPermission(
            user_id=user_id,
            project_id=project_id,
            collection_id=collection_id,
            permission_id=perm.permission_id,
        )
    )
    db.commit()


# ─── Tests: duplicate permission rows (UniqueConstraint fix) ─────────────────

class TestPartialUniqueIndex:
    """Ensure partial unique indexes prevent duplicate permission rows."""

    def test_no_duplicate_project_scope_permission(self, db: Session) -> None:
        """Adding the same project-scope permission twice should raise an integrity error."""
        user = _create_user(db)
        proj = Project(name=f"p_{random_lower_string()[:6]}", creator_id=1, url="http://test")
        db.add(proj)
        db.commit()
        db.refresh(proj)

        perm = db.exec(select(Permission).where(Permission.name == "project:read")).one()
        db.add(UserPermission(user_id=user.user_id, project_id=proj.project_id, permission_id=perm.permission_id))
        db.commit()

        # Second identical row should raise IntegrityError
        with pytest.raises(Exception):
            db.add(UserPermission(user_id=user.user_id, project_id=proj.project_id, permission_id=perm.permission_id))
            db.commit()

    def test_no_duplicate_collection_scope_permission(self, db: Session) -> None:
        """Adding the same collection-scope permission twice should raise an integrity error."""
        user = _create_user(db)
        col = _create_collection(db, owner_id=1)
        project_id = _ensure_project_for_collection(db, col.collection_id, owner_id=1)

        perm = db.exec(select(Permission).where(Permission.name == "audio:read")).one()
        db.add(
            UserPermission(
                user_id=user.user_id,
                project_id=project_id,
                collection_id=col.collection_id,
                permission_id=perm.permission_id,
            )
        )
        db.commit()

        with pytest.raises(Exception):
            db.add(
                UserPermission(
                    user_id=user.user_id,
                    project_id=project_id,
                    collection_id=col.collection_id,
                    permission_id=perm.permission_id,
                )
            )
            db.commit()

    def test_same_permission_on_different_collections_allowed(self, db: Session) -> None:
        """Same permission on two different collections is NOT a duplicate."""
        user = _create_user(db)
        col_a = _create_collection(db, owner_id=1)
        col_b = _create_collection(db, owner_id=1)
        project_a_id = _ensure_project_for_collection(db, col_a.collection_id, owner_id=1)
        project_b_id = _ensure_project_for_collection(db, col_b.collection_id, owner_id=1)

        perm = db.exec(select(Permission).where(Permission.name == "audio:read")).one()
        db.add(
            UserPermission(
                user_id=user.user_id,
                project_id=project_a_id,
                collection_id=col_a.collection_id,
                permission_id=perm.permission_id,
            )
        )
        db.add(
            UserPermission(
                user_id=user.user_id,
                project_id=project_b_id,
                collection_id=col_b.collection_id,
                permission_id=perm.permission_id,
            )
        )
        db.commit()

        rows = db.exec(select(UserPermission).where(
            UserPermission.user_id == user.user_id,
            UserPermission.permission_id == perm.permission_id,
        )).all()
        assert len(rows) == 2


class TestUserEffectivePermissionView:
    """Regression coverage for the canonical effective permission view."""

    def _permission_actions(
        self,
        db: Session,
        user_id: int,
        project_id: int,
        collection_id: int | None,
        resource_type: str,
    ) -> set[str]:
        rows = db.exec(
            select(UserEffectivePermission.action).where(
                UserEffectivePermission.user_id == user_id,
                UserEffectivePermission.project_id == project_id,
                UserEffectivePermission.collection_id == collection_id,
                UserEffectivePermission.resource_type == resource_type,
            )
        ).all()
        return set(rows)

    def test_project_read_stays_project_scope_only(self, db: Session) -> None:
        user = _create_user(db)
        project = _create_project(db, owner_id=1)
        collection = _create_collection(db, owner_id=1)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        project_read = db.exec(select(Permission).where(Permission.name == "project:read")).one()
        db.add(
            UserPermission(
                user_id=user.user_id,
                project_id=project.project_id,
                permission_id=project_read.permission_id,
            )
        )
        db.commit()

        project_row = db.exec(
            select(UserEffectivePermission).where(
                UserEffectivePermission.user_id == user.user_id,
                UserEffectivePermission.project_id == project.project_id,
                UserEffectivePermission.collection_id.is_(None),
                UserEffectivePermission.scope_type == "project",
                UserEffectivePermission.resource_type == "project",
                UserEffectivePermission.action == "read",
            )
        ).first()
        collection_rows = db.exec(
            select(UserEffectivePermission).where(
                UserEffectivePermission.user_id == user.user_id,
                UserEffectivePermission.collection_id == collection.collection_id,
            )
        ).all()

        assert project_row is not None
        assert collection_rows == []

    def test_project_write_covers_project_and_child_collection_paths(self, db: Session) -> None:
        user = _create_user(db)
        project = _create_project(db, owner_id=1)
        col_a = _create_collection(db, owner_id=1)
        col_b = _create_collection(db, owner_id=1)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=col_a.collection_id))
        db.add(ProjectCollection(project_id=project.project_id, collection_id=col_b.collection_id))
        project_write = db.exec(select(Permission).where(Permission.name == "project:write")).one()
        db.add(
            UserPermission(
                user_id=user.user_id,
                project_id=project.project_id,
                permission_id=project_write.permission_id,
            )
        )
        db.commit()

        assert self._permission_actions(
            db, user.user_id, project.project_id, None, "project"
        ) == {"read", "write"}
        for collection in (col_a, col_b):
            for resource_type in ("collection", "audio", "site", "annotation", "review"):
                assert self._permission_actions(
                    db,
                    user.user_id,
                    project.project_id,
                    collection.collection_id,
                    resource_type,
                ) == {"read", "write"}

        assert permission_repository.has_collection_resource_permission(
            db, user.user_id, project.project_id, col_a.collection_id, "audio", "read"
        )
        assert set(
            permission_repository.get_effective_collection_scopes(
                db, user.user_id, "collection", "read", project_id=project.project_id
            )
        ) == {
            (project.project_id, col_a.collection_id),
            (project.project_id, col_b.collection_id),
        }

    def test_project_sub_resource_expands_to_child_collections(self, db: Session) -> None:
        user = _create_user(db)
        project = _create_project(db, owner_id=1)
        col_a = _create_collection(db, owner_id=1)
        col_b = _create_collection(db, owner_id=1)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=col_a.collection_id))
        db.add(ProjectCollection(project_id=project.project_id, collection_id=col_b.collection_id))
        audio_read = db.exec(select(Permission).where(Permission.name == "audio:read")).one()
        db.add(
            UserPermission(
                user_id=user.user_id,
                project_id=project.project_id,
                permission_id=audio_read.permission_id,
            )
        )
        db.commit()

        assert set(
            permission_repository.get_effective_collection_scopes(
                db, user.user_id, "audio", "read", project_id=project.project_id
            )
        ) == {
            (project.project_id, col_a.collection_id),
            (project.project_id, col_b.collection_id),
        }
        assert not permission_repository.has_effective_permission(
            db, user.user_id, "audio", "read", project_id=project.project_id
        )

    def test_project_sub_resource_write_expands_read_and_write_only_for_resource(self, db: Session) -> None:
        user = _create_user(db)
        project = _create_project(db, owner_id=1)
        collection = _create_collection(db, owner_id=1)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        audio_write = db.exec(select(Permission).where(Permission.name == "audio:write")).one()
        db.add(
            UserPermission(
                user_id=user.user_id,
                project_id=project.project_id,
                permission_id=audio_write.permission_id,
            )
        )
        db.commit()

        assert self._permission_actions(
            db,
            user.user_id,
            project.project_id,
            collection.collection_id,
            "audio",
        ) == {"read", "write"}
        assert self._permission_actions(
            db,
            user.user_id,
            project.project_id,
            collection.collection_id,
            "site",
        ) == set()

    def test_collection_write_expands_collection_and_child_resources(self, db: Session) -> None:
        user = _create_user(db)
        project = _create_project(db, owner_id=1)
        collection = _create_collection(db, owner_id=1)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        collection_write = db.exec(select(Permission).where(Permission.name == "collection:write")).one()
        db.add(
            UserPermission(
                user_id=user.user_id,
                project_id=project.project_id,
                collection_id=collection.collection_id,
                permission_id=collection_write.permission_id,
            )
        )
        db.commit()

        for resource_type in ("collection", "audio", "site", "annotation", "review"):
            assert self._permission_actions(
                db,
                user.user_id,
                project.project_id,
                collection.collection_id,
                resource_type,
            ) == {"read", "write"}

    def test_collection_permission_stays_on_project_collection_path(self, db: Session) -> None:
        user = _create_user(db)
        shared_collection = _create_collection(db, owner_id=1)
        project_a = _create_project(db, owner_id=1)
        project_b = _create_project(db, owner_id=1)
        db.add(ProjectCollection(project_id=project_a.project_id, collection_id=shared_collection.collection_id))
        db.add(ProjectCollection(project_id=project_b.project_id, collection_id=shared_collection.collection_id))
        collection_write = db.exec(select(Permission).where(Permission.name == "collection:write")).one()
        db.add(
            UserPermission(
                user_id=user.user_id,
                project_id=project_a.project_id,
                collection_id=shared_collection.collection_id,
                permission_id=collection_write.permission_id,
            )
        )
        db.commit()

        assert permission_repository.has_collection_resource_permission(
            db,
            user.user_id,
            project_a.project_id,
            shared_collection.collection_id,
            "site",
            "read",
        )
        assert not permission_repository.has_collection_resource_permission(
            db,
            user.user_id,
            project_b.project_id,
            shared_collection.collection_id,
            "site",
            "read",
        )


# ─── Tests: index_log_service uses collection:write ──────────────────────────

class TestIndexLogPermissionLogic:
    """index_log_service: collection:write → all logs; otherwise → own logs only."""

    @pytest.fixture
    def setup_data(self, db: Session):
        """Set up test collection, media, index type, and two users."""
        user_a = _create_user(db)
        user_b = _create_user(db)
        col = _create_collection(db, owner_id=1)

        media = Media(
            name=f"m_{random_lower_string()[:6]}.wav",
            uploader_id=user_a.user_id,
            media_type="audio", is_metadata=True,
            date_time=datetime_module.datetime.now(datetime_module.UTC)
        )
        db.add(media)
        db.commit()
        db.refresh(media)

        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=1))

        idx_type = IndexType(name=f"idx_{random_lower_string()[:6]}")
        db.add(idx_type)
        db.commit()
        db.refresh(idx_type)

        # Log created by user_a
        log_a = IndexLog(
            media_id=media.media_id,
            user_id=user_a.user_id,
            index_id=idx_type.index_id,
            version="1.0",
            variable_order=1,
        )
        # Log created by user_b
        log_b = IndexLog(
            media_id=media.media_id,
            user_id=user_b.user_id,
            index_id=idx_type.index_id,
            version="1.0",
            variable_order=1,
        )
        db.add_all([log_a, log_b])
        db.commit()
        db.refresh(log_a)
        db.refresh(log_b)

        return {"user_a": user_a, "user_b": user_b, "col": col, "media": media, "log_a": log_a, "log_b": log_b}

    def test_user_sees_only_own_log_without_write(self, db: Session, setup_data) -> None:
        """Without collection:write, user only sees own index logs."""
        from app.services.index_log_service import list_index_logs
        user_a = setup_data["user_a"]

        results, total = list_index_logs(db, user_a)
        result_ids = [r["log_id"] for r in results]

        assert setup_data["log_a"].log_id in result_ids
        assert setup_data["log_b"].log_id not in result_ids

    def test_user_with_collection_write_sees_all_logs(self, db: Session, setup_data) -> None:
        """With collection:write, user sees all index logs in that collection."""
        from app.services.index_log_service import list_index_logs
        user_a = setup_data["user_a"]
        col = setup_data["col"]

        _grant_collection_perm(db, user_a.user_id, col.collection_id, "collection:write")

        results, total = list_index_logs(db, user_a)
        result_ids = [r["log_id"] for r in results]

        assert setup_data["log_a"].log_id in result_ids
        assert setup_data["log_b"].log_id in result_ids


class TestEffectivePermissionsViewClosure:
    """Ensure effective permission rows contain the full read/write closure."""

    def test_project_write_materializes_collection_read_rows(self, db: Session) -> None:
        """project:write materializes read/write rows for child collection paths."""
        user = _create_user(db)
        project = Project(
            name=f"p_{random_lower_string()[:8]}",
            creator_id=1,
            url="http://test-project",
        )
        db.add(project)
        db.flush()

        col_a = _create_collection(db, owner_id=1)
        col_b = _create_collection(db, owner_id=1)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=col_a.collection_id))
        db.add(ProjectCollection(project_id=project.project_id, collection_id=col_b.collection_id))
        db.flush()

        project_write = db.exec(
            select(Permission).where(Permission.name == "project:write")
        ).one()
        db.add(
            UserPermission(
                user_id=user.user_id,
                project_id=project.project_id,
                permission_id=project_write.permission_id,
            )
        )
        db.commit()

        readable_site_ids = permission_repository.get_accessible_collection_ids(
            db, user.user_id, resource_type="site", action="read"
        )
        writable_site_ids = permission_repository.get_accessible_collection_ids(
            db, user.user_id, resource_type="site", action="write"
        )
        readable_collection_ids = permission_repository.get_accessible_collection_ids(
            db, user.user_id, resource_type="collection", action="read"
        )

        assert set(readable_site_ids) == {col_a.collection_id, col_b.collection_id}
        assert set(writable_site_ids) == {col_a.collection_id, col_b.collection_id}
        assert set(readable_collection_ids) == {col_a.collection_id, col_b.collection_id}

        site_read_rows = db.exec(
            select(UserEffectivePermission).where(
                UserEffectivePermission.user_id == user.user_id,
                UserEffectivePermission.resource_type == "site",
                UserEffectivePermission.action == "read",
            )
        ).all()
        collection_read_rows = db.exec(
            select(UserEffectivePermission).where(
                UserEffectivePermission.user_id == user.user_id,
                UserEffectivePermission.resource_type == "collection",
                UserEffectivePermission.action == "read",
            )
        ).all()
        assert {row.collection_id for row in site_read_rows} == {
            col_a.collection_id,
            col_b.collection_id,
        }
        assert {row.collection_id for row in collection_read_rows} == {
            col_a.collection_id,
            col_b.collection_id,
        }

    def test_collection_write_materializes_child_resource_read_rows(self, db: Session) -> None:
        """collection:write materializes child-resource read rows in the view."""
        user = _create_user(db)
        col = _create_collection(db, owner_id=1)
        _grant_collection_perm(db, user.user_id, col.collection_id, "collection:write")

        readable_site_ids = permission_repository.get_accessible_collection_ids(
            db, user.user_id, resource_type="site", action="read"
        )
        writable_site_ids = permission_repository.get_accessible_collection_ids(
            db, user.user_id, resource_type="site", action="write"
        )
        assert col.collection_id in readable_site_ids
        assert col.collection_id in writable_site_ids

        site_read_rows = db.exec(
            select(UserEffectivePermission).where(
                UserEffectivePermission.user_id == user.user_id,
                UserEffectivePermission.collection_id == col.collection_id,
                UserEffectivePermission.resource_type == "site",
                UserEffectivePermission.action == "read",
            )
        ).all()
        assert len(site_read_rows) == 1

"""Unit tests for PermissionService (high coverage)."""
from datetime import datetime

import pytest
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    User, Role, Project, Collection, Permission, UserPermission
)
from app.models.project import ProjectCollection
from app.services import permission_service


class TestPermissionServiceScenarios:
    """Integration tests to push coverage above 80%."""

    @pytest.fixture
    def setup_data(self, db: Session):
        admin_role = db.exec(select(Role).where(Role.name == settings.ADMIN_ROLE_NAME)).first()
        if not admin_role:
            admin_role = Role(name=settings.ADMIN_ROLE_NAME)
            db.add(admin_role)

        user_role_name = "User_Final_" + str(datetime.now().timestamp())
        user_role = Role(name=user_role_name)
        db.add_all([user_role])
        db.flush()

        admin = User(username="admin_f", role_id=admin_role.role_id, email="af@e.com", password="p", name="A")
        user = User(username="user_f", role_id=user_role.role_id, email="uf@e.com", password="p", name="U")
        db.add_all([admin, user])
        db.flush()
        return {"admin": admin, "user": user}

    def test_get_accessible_collection_ids_complex(self, db: Session, setup_data):
        user = setup_data["user"]
        public_project = Project(name="P_Public", creator_id=user.user_id, public=True, url="h")
        private_project = Project(name="P_Private", creator_id=user.user_id, public=False, url="h")
        c1 = Collection(name="C1", creator_id=user.user_id, public_access=True)
        c2 = Collection(name="C2", creator_id=user.user_id, public_access=False)
        db.add_all([public_project, private_project, c1, c2])
        db.flush()
        db.add_all([
            ProjectCollection(project_id=public_project.project_id, collection_id=c1.collection_id),
            ProjectCollection(project_id=private_project.project_id, collection_id=c2.collection_id),
        ])
        db.flush()

        ids = permission_service.get_accessible_collection_ids(db, user)
        assert c1.collection_id in ids
        assert c2.collection_id not in ids

        perm = db.exec(select(Permission).where(Permission.name == "collection:read")).first()
        if not perm:
            perm = Permission(resource_type="collection", action="read", name="collection:read")
            db.add(perm)
            db.flush()

        db.add(
            UserPermission(
                user_id=user.user_id,
                project_id=private_project.project_id,
                collection_id=c2.collection_id,
                permission_id=perm.permission_id,
            )
        )
        db.flush()

        ids = permission_service.get_accessible_collection_ids(db, user)
        assert c1.collection_id in ids
        assert c2.collection_id in ids

    def test_can_access_no_permission(self, db: Session, setup_data):
        user = setup_data["user"]
        p = Project(name="PrivateP", creator_id=setup_data["admin"].user_id, public=False, url="h")
        c = Collection(name="PrivateC", creator_id=setup_data["admin"].user_id, public_access=False)
        db.add_all([p, c])
        db.flush()
        db.add(ProjectCollection(project_id=p.project_id, collection_id=c.collection_id))
        db.flush()

        assert permission_service.can_access_project(db, user, p.project_id, action="read") is False
        assert permission_service.can_access_collection(db, user, p.project_id, c.collection_id, action="read") is False
        assert permission_service.can_access_project(db, user, p.project_id, action="write") is False
        assert permission_service.can_access_collection(db, user, p.project_id, c.collection_id, action="write") is False

    def test_is_admin_none_role(self):
        user = User(username="x", role=None)
        assert permission_service.is_admin(user) is False


_GRANT_PERM_MAP = {
    "project:read": 1,
    "project:write": 2,
    "collection:read": 3,
    "collection:write": 4,
    "audio:read": 5,
    "audio:write": 6,
    "site:read": 7,
    "site:write": 8,
    "annotation:read": 9,
    "annotation:write": 10,
    "review:read": 11,
    "review:write": 12,
}


def _project_node(project_id, stored_permissions, collections=None):
    return SimpleNamespace(
        project_id=project_id,
        stored_permissions=stored_permissions,
        collections=collections or [],
    )


def _collection_node(project_id, collection_id, stored_permissions):
    return SimpleNamespace(
        project_id=project_id,
        collection_id=collection_id,
        stored_permissions=stored_permissions,
    )


def test_non_admin_manager_cannot_grant_project_write():
    context = permission_service._PermissionManagementContext(
        project_ids={1}, collection_scopes=set()
    )
    request_projects = [_project_node(1, ["project:write"])]
    with pytest.raises(HTTPException) as exc:
        permission_service._validate_permission_payload(
            request_projects, _GRANT_PERM_MAP, context
        )
    assert exc.value.status_code == 403
    assert "project:write" in exc.value.detail


def test_non_admin_manager_can_grant_collection_write():
    context = permission_service._PermissionManagementContext(
        project_ids={1}, collection_scopes=set()
    )
    request_projects = [
        _project_node(1, [], [_collection_node(1, 10, ["collection:write"])])
    ]
    # Should not raise: a project:write manager may delegate collection:write.
    permission_service._validate_permission_payload(
        request_projects, _GRANT_PERM_MAP, context
    )


def test_admin_can_grant_project_write():
    context = permission_service._PermissionManagementContext(
        project_ids=None, collection_scopes=None
    )
    request_projects = [_project_node(1, ["project:write"])]
    # Admin context is unrestricted.
    permission_service._validate_permission_payload(
        request_projects, _GRANT_PERM_MAP, context
    )
