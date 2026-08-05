"""
Test cases for permissions API routes and service layer.

Tests cover:
- List/get permission endpoints
- Project-level and collection-level permission sync
- has_resource_permission() 8-step hierarchy:
  1. Admin always passes
  2. Public resource (read only, self only)
  3. Direct collection-level permission
  4. Project-level inheritance (any permission type)
  5. collection:write implies all sub-resources read+write
  6. project:write implies collection:write on all collections
  7. write implies read for same resource
  8. Deny
"""
import jwt as pyjwt
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Collection, Permission, Role, User, UserPermission
from app.models.effective_permission import UserEffectivePermission
from app.models.project import Project, ProjectCollection
from app.repositories.permission_repository import permission_repository
from app.services.permission_service import _SUB_RESOURCE_TYPES
from app.services.permission_service import (
    has_resource_permission as _has_resource_permission,
)
from tests.utils.utils import random_lower_string

# ─── DB helpers ──────────────────────────────────────────────────────────────


def _create_user(db: Session) -> User:
    """Create a minimal non-admin test user."""
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


def _create_project(db: Session, user_id: int, public: bool = False) -> Project:
    """Create a minimal test project."""
    p = Project(
        name=f"proj_{random_lower_string()[:8]}",
        url="https://test.example.com",
        creator_id=user_id,
        public=public,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _create_collection(db: Session, user_id: int, public_access: bool = False) -> Collection:
    """Create a minimal test collection."""
    col = Collection(
        name=f"col_{random_lower_string()[:8]}",
        creator_id=user_id,
        public_access=public_access,
    )
    db.add(col)
    db.commit()
    db.refresh(col)
    project = _create_project(db, user_id=user_id, public=public_access)
    _link_project_collection(db, project.project_id, col.collection_id)
    return col


def _rename_project(db: Session, project: Project, name: str) -> Project:
    """Update project name for deterministic ordering tests."""
    project.name = name
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _rename_collection(db: Session, collection: Collection, name: str) -> Collection:
    """Update collection name for deterministic ordering tests."""
    collection.name = name
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


def _project_id_for_collection(db: Session, collection_id: int) -> int:
    project_id = db.exec(
        select(ProjectCollection.project_id).where(ProjectCollection.collection_id == collection_id)
    ).first()
    assert project_id is not None
    return project_id


def has_resource_permission(
    db: Session,
    user: User,
    resource_type: str,
    action: str,
    *,
    collection_id: int | None = None,
    project_id: int | None = None,
) -> bool:
    """Test helper: use explicit project context for collection-scoped checks."""
    if collection_id is not None and project_id is None:
        project_id = db.exec(
            select(ProjectCollection.project_id)
            .join(
                UserPermission,
                UserPermission.project_id == ProjectCollection.project_id,
            )
            .where(
                ProjectCollection.collection_id == collection_id,
                UserPermission.user_id == user.user_id,
            )
        ).first()
        if project_id is None:
            project_id = _project_id_for_collection(db, collection_id)
    return _has_resource_permission(
        db,
        user,
        resource_type,
        action,
        collection_id=collection_id,
        project_id=project_id,
    )


def _link_project_collection(db: Session, project_id: int, collection_id: int) -> None:
    """Associate a collection with a project."""
    existing = db.exec(
        select(ProjectCollection).where(
            ProjectCollection.project_id == project_id,
            ProjectCollection.collection_id == collection_id,
        )
    ).first()
    if existing is None:
        db.add(ProjectCollection(project_id=project_id, collection_id=collection_id))
        db.commit()


def _grant_collection_perm(
    db: Session,
    user_id: int,
    collection_id: int,
    perm_name: str,
    project_id: int | None = None,
) -> None:
    """Grant a named permission at project-local collection scope."""
    perm = db.exec(select(Permission).where(Permission.name == perm_name)).one()
    if project_id is None:
        project_ids = list(
            db.exec(
                select(ProjectCollection.project_id).where(ProjectCollection.collection_id == collection_id)
            ).all()
        )
        if not project_ids:
            collection = db.get(Collection, collection_id)
            assert collection is not None
            project = _create_project(db, user_id=collection.creator_id)
            _link_project_collection(db, project.project_id, collection_id)
            project_ids = [project.project_id]
        project_id = project_ids[-1]
    db.add(
        UserPermission(
            user_id=user_id,
            project_id=project_id,
            collection_id=collection_id,
            permission_id=perm.permission_id,
        )
    )
    db.commit()


def _grant_project_perm(db: Session, user_id: int, project_id: int, perm_name: str) -> None:
    """Grant a named permission at project scope."""
    perm = db.exec(select(Permission).where(Permission.name == perm_name)).one()
    db.add(UserPermission(user_id=user_id, project_id=project_id, permission_id=perm.permission_id))
    db.commit()


def _user_project_permission_names(db: Session, user_id: int, project_id: int) -> set[str]:
    stmt = (
        select(Permission.name)
        .join(UserPermission, UserPermission.permission_id == Permission.permission_id)
        .where(
            UserPermission.user_id == user_id,
            UserPermission.project_id == project_id,
        )
    )
    return set(db.exec(stmt).all())


def _user_collection_permission_names(db: Session, user_id: int, collection_id: int) -> set[str]:
    stmt = (
        select(Permission.name)
        .join(UserPermission, UserPermission.permission_id == Permission.permission_id)
        .where(
            UserPermission.user_id == user_id,
            UserPermission.collection_id == collection_id,
        )
    )
    return set(db.exec(stmt).all())


def _user_collection_permission_names_for_path(
    db: Session,
    user_id: int,
    project_id: int,
    collection_id: int,
) -> set[str]:
    stmt = (
        select(Permission.name)
        .join(UserPermission, UserPermission.permission_id == Permission.permission_id)
        .where(
            UserPermission.user_id == user_id,
            UserPermission.project_id == project_id,
            UserPermission.collection_id == collection_id,
        )
    )
    return set(db.exec(stmt).all())


def _project_assignment(project_id: int, stored_permissions: list[str], collections: list[dict] | None = None) -> dict:
    return {
        "project_id": project_id,
        "stored_permissions": stored_permissions,
        "collections": collections or [],
    }


def _collection_assignment(project_id: int, collection_id: int, stored_permissions: list[str]) -> dict:
    return {
        "project_id": project_id,
        "collection_id": collection_id,
        "stored_permissions": stored_permissions,
    }


# ─── API tests ───────────────────────────────────────────────────────────────








class TestSyncUserPermissionsGlobal:
    """PUT /users/{user_id}/permissions — unified permission sync."""

    def test_sync_project_scope_permissions(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can sync project-scoped permissions."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(proj.project_id, ["project:read", "audio:write"])
                ]
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["code"] == 0
        assert data["data"] is None
        names = _user_project_permission_names(db, user.user_id, proj.project_id)
        assert "audio:write" in names
        assert "project:read" in names

    def test_sync_collection_scope_permissions(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can sync collection-scoped permissions."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(
                        proj.project_id,
                        [],
                        [_collection_assignment(proj.project_id, col.collection_id, ["collection:write"])],
                    )
                ]
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["code"] == 0
        assert data["data"] is None
        assert _user_collection_permission_names(db, user.user_id, col.collection_id) == {"collection:write"}

    def test_sync_empty_permissions_clears_scope(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Sending empty permissions list clears all permissions for that scope."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        # First grant some permissions
        _grant_collection_perm(db, user.user_id, col.collection_id, "audio:read")
        # Then clear them
        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(
                        proj.project_id,
                        [],
                        [_collection_assignment(proj.project_id, col.collection_id, [])],
                    )
                ]
            },
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        assert _user_collection_permission_names(db, user.user_id, col.collection_id) == set()

    def test_sync_admin_set_admin_role(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can set is_admin=true to grant admin role."""
        user = _create_user(db)
        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={"is_admin": True, "projects": []},
        )
        assert r.status_code == 200
        # Verify user role changed
        db.refresh(user)
        assert user.role_id == 1  # Admin role

    def test_sync_admin_revoke_admin_role(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can set is_admin=false to revoke admin role."""
        user = _create_user(db)
        # First make admin
        user.role_id = 1
        db.add(user)
        db.commit()
        # Now revoke
        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={"is_admin": False, "projects": []},
        )
        assert r.status_code == 200
        db.refresh(user)
        assert user.role_id == 2  # Normal user role

    def test_sync_manager_cannot_set_admin(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Non-admin manager cannot set is_admin."""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        normal_user_id = int(payload["sub"])

        # Grant project:write to make normal user a manager
        proj = _create_project(db, user_id=1)
        _grant_project_perm(db, normal_user_id, proj.project_id, "project:write")

        user = _create_user(db)
        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=normal_user_token_headers,
            json={"is_admin": True, "projects": []},
        )
        assert r.status_code == 403

    def test_sync_invalid_permission_name_400(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Invalid permission name returns 400."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(proj.project_id, ["not:valid"])
                ]
            },
        )
        assert r.status_code == 400

    def test_sync_user_not_found_404(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        """Non-existent user_id returns 404."""
        r = client.put(
            f"{settings.API_V1_STR}/users/99999/permissions",
            headers=superuser_token_headers,
            json={"projects": []},
        )
        assert r.status_code == 404

    def test_sync_project_not_found_404(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Non-existent project_id returns 404."""
        user = _create_user(db)
        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(99999, [])
                ]
            },
        )
        assert r.status_code == 404

    def test_sync_both_scope_ids_422(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Mismatched collection.project_id payload is rejected."""
        user = _create_user(db)
        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    {
                        "project_id": 1,
                        "stored_permissions": [],
                        "collections": [
                            {
                                "project_id": 2,
                                "collection_id": 1,
                                "stored_permissions": [],
                            }
                        ],
                    }
                ]
            },
        )
        assert r.status_code == 400

    def test_sync_anonymous_401(self, client: TestClient) -> None:
        """Anonymous request returns 401."""
        r = client.put(
            f"{settings.API_V1_STR}/users/1/permissions",
            json={"projects": []},
        )
        assert r.status_code == 401

    def test_sync_manager_cannot_modify_out_of_scope(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Manager cannot modify permissions on a project they don't manage."""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        normal_user_id = int(payload["sub"])

        # Grant project:write on proj_a to make normal user a manager
        proj_a = _create_project(db, user_id=1)
        _grant_project_perm(db, normal_user_id, proj_a.project_id, "project:write")

        # Try to modify permissions on proj_b (not managed)
        proj_b = _create_project(db, user_id=1)
        user = _create_user(db)
        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=normal_user_token_headers,
            json={
                "projects": [
                    _project_assignment(proj_b.project_id, ["project:read"])
                ]
            },
        )
        assert r.status_code == 403

    def test_sync_multiple_scopes(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can sync multiple scopes in one request."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(
                        proj.project_id,
                        ["project:write"],
                        [_collection_assignment(proj.project_id, col.collection_id, ["audio:read", "site:write"])],
                    ),
                ]
            },
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        assert _user_project_permission_names(db, user.user_id, proj.project_id) == {"project:write"}
        assert _user_collection_permission_names(db, user.user_id, col.collection_id) == set()

    def test_sync_normalizes_redundant_with_scope_write(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """project:write + audio:write → only project:write is stored."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(proj.project_id, [
                        "project:write", "audio:write", "site:read"
                    ])
                ]
            },
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        assert _user_project_permission_names(db, user.user_id, proj.project_id) == {"project:write"}

    def test_sync_normalizes_write_implies_read(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """audio:write + audio:read → only audio:write is stored."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(
                        proj.project_id,
                        [],
                        [_collection_assignment(proj.project_id, col.collection_id, ["audio:write", "audio:read"])],
                    )
                ]
            },
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        assert _user_collection_permission_names(db, user.user_id, col.collection_id) == {
            "audio:write",
            "collection:read",
        }

    def test_sync_normalizes_cross_scope_project_covers_collection(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """project audio:write makes collection audio:write redundant."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(
                        proj.project_id,
                        ["audio:write"],
                        [_collection_assignment(proj.project_id, col.collection_id, ["audio:write"])],
                    ),
                ]
            },
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        assert _user_project_permission_names(db, user.user_id, proj.project_id) == {
            "audio:write",
            "project:read",
        }
        assert _user_collection_permission_names(db, user.user_id, col.collection_id) == set()

    def test_sync_normalizes_cross_scope_project_write_clears_all(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """project:write makes all collection-level permissions redundant."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(
                        proj.project_id,
                        ["project:write"],
                        [_collection_assignment(proj.project_id, col.collection_id, ["collection:write", "audio:read"])],
                    ),
                ]
            },
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        assert _user_collection_permission_names(db, user.user_id, col.collection_id) == set()

    def test_sync_cross_scope_project_write_covers_collection_read(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """project audio:write + collection audio:read → audio:read filtered (write implies read)."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(
                        proj.project_id,
                        ["audio:write"],
                        [_collection_assignment(proj.project_id, col.collection_id, ["audio:read"])],
                    ),
                ]
            },
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        assert _user_collection_permission_names(db, user.user_id, col.collection_id) == set()

    def test_sync_cross_scope_project_read_keeps_collection_write(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """project audio:read + collection audio:write → audio:write is NOT redundant, kept."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(
                        proj.project_id,
                        ["audio:read"],
                        [_collection_assignment(proj.project_id, col.collection_id, ["audio:write"])],
                    ),
                ]
            },
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        assert _user_collection_permission_names(db, user.user_id, col.collection_id) == {
            "audio:write",
            "collection:read",
        }

    # ── Deduplication tests ───────────────────────────────────────────────────

    def test_sync_duplicate_project_scopes_are_merged(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """同一项目节点提交完整 stored_permissions 时，应按最终树形状态同步。"""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)

        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(proj.project_id, ["audio:read", "site:read"]),
                ]
            },
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        assert _user_project_permission_names(db, user.user_id, proj.project_id) == {
            "audio:read",
            "site:read",
            "project:read",
        }

    def test_sync_duplicate_collection_scopes_are_merged(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """集合节点提交完整 stored_permissions 时，应按最终树形状态同步。"""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(
                        proj.project_id,
                        [],
                        [_collection_assignment(proj.project_id, col.collection_id, ["audio:read", "site:read"])],
                    ),
                ]
            },
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        assert _user_collection_permission_names(db, user.user_id, col.collection_id) == {
            "audio:read",
            "site:read",
            "collection:read",
        }

    def test_sync_large_duplicate_payload_like_frontend(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """提交空集合权限节点时，应清空该项目下该集合的存储权限。"""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(
                        proj.project_id,
                        [],
                        [_collection_assignment(proj.project_id, col.collection_id, [])],
                    )
                ]
            },
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        assert _user_collection_permission_names(db, user.user_id, col.collection_id) == set()

    def test_sync_omitted_project_clears_existing_permissions(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """管理员全量同步时，未提交的项目应清空已有权限。"""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        _grant_project_perm(db, user.user_id, proj.project_id, "project:write")

        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={"projects": []},
        )

        assert r.status_code == 200
        assert _user_project_permission_names(db, user.user_id, proj.project_id) == set()

    def test_sync_omitted_collection_clears_existing_permissions(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """项目仍提交但集合未提交时，应清空该项目内被省略集合的权限。"""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        _grant_collection_perm(db, user.user_id, col.collection_id, "audio:write")

        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(proj.project_id, ["project:read"], [])
                ]
            },
        )

        assert r.status_code == 200
        assert _user_project_permission_names(db, user.user_id, proj.project_id) == {"project:read"}
        assert _user_collection_permission_names(db, user.user_id, col.collection_id) == set()

    def test_non_admin_empty_payload_clears_only_managed_window(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """非管理员提交空树时，只清空自己管理范围内权限，范围外权限保留。"""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        manager_id = int(payload["sub"])

        target = _create_user(db)
        managed_a = _create_project(db, user_id=1)
        managed_b = _create_project(db, user_id=1)
        outside_d = _create_project(db, user_id=1)
        outside_e = _create_project(db, user_id=1)
        _grant_project_perm(db, manager_id, managed_a.project_id, "project:write")
        _grant_project_perm(db, manager_id, managed_b.project_id, "project:write")

        for project in (managed_a, managed_b, outside_d, outside_e):
            _grant_project_perm(db, target.user_id, project.project_id, "project:read")

        r = client.put(
            f"{settings.API_V1_STR}/users/{target.user_id}/permissions",
            headers=normal_user_token_headers,
            json={"projects": []},
        )
        assert r.status_code == 200
        assert _user_project_permission_names(db, target.user_id, managed_a.project_id) == set()
        assert _user_project_permission_names(db, target.user_id, managed_b.project_id) == set()
        assert _user_project_permission_names(db, target.user_id, outside_d.project_id) == {"project:read"}
        assert _user_project_permission_names(db, target.user_id, outside_e.project_id) == {"project:read"}

    def test_non_admin_omitted_collection_under_project_write_is_cleared(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """项目管理员提交项目节点但省略集合时，应清空该项目下被省略集合权限。"""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        manager_id = int(payload["sub"])

        target = _create_user(db)
        project = _create_project(db, user_id=1)
        col_kept = _create_collection(db, user_id=1)
        col_omitted = _create_collection(db, user_id=1)
        _link_project_collection(db, project.project_id, col_kept.collection_id)
        _link_project_collection(db, project.project_id, col_omitted.collection_id)
        _grant_project_perm(db, manager_id, project.project_id, "project:write")
        _grant_project_perm(db, target.user_id, project.project_id, "project:read")
        _grant_collection_perm(db, target.user_id, col_kept.collection_id, "audio:write", project_id=project.project_id)
        _grant_collection_perm(db, target.user_id, col_omitted.collection_id, "site:write", project_id=project.project_id)

        r = client.put(
            f"{settings.API_V1_STR}/users/{target.user_id}/permissions",
            headers=normal_user_token_headers,
            json={
                "projects": [
                    _project_assignment(
                        project.project_id,
                        ["project:read"],
                        [_collection_assignment(project.project_id, col_kept.collection_id, ["audio:write"])],
                    )
                ]
            },
        )
        assert r.status_code == 200
        assert "audio:write" in _user_collection_permission_names(db, target.user_id, col_kept.collection_id)
        assert _user_collection_permission_names(db, target.user_id, col_omitted.collection_id) == set()

    def test_non_admin_collection_window_clears_only_that_project_path(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """集合管理员省略集合时，只清空对应 project_id + collection_id 路径。"""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        manager_id = int(payload["sub"])

        target = _create_user(db)
        shared_col = _create_collection(db, user_id=1)
        project_a = _create_project(db, user_id=1)
        project_b = _create_project(db, user_id=1)
        _link_project_collection(db, project_a.project_id, shared_col.collection_id)
        _link_project_collection(db, project_b.project_id, shared_col.collection_id)
        _grant_collection_perm(
            db,
            manager_id,
            shared_col.collection_id,
            "collection:write",
            project_id=project_a.project_id,
        )
        _grant_collection_perm(
            db,
            target.user_id,
            shared_col.collection_id,
            "audio:write",
            project_id=project_a.project_id,
        )
        _grant_collection_perm(
            db,
            target.user_id,
            shared_col.collection_id,
            "site:write",
            project_id=project_b.project_id,
        )

        r = client.put(
            f"{settings.API_V1_STR}/users/{target.user_id}/permissions",
            headers=normal_user_token_headers,
            json={"projects": []},
        )
        assert r.status_code == 200
        path_a = {
            name for name in _user_collection_permission_names(db, target.user_id, shared_col.collection_id)
            if db.exec(
                select(UserPermission)
                .join(Permission)
                .where(
                    UserPermission.user_id == target.user_id,
                    UserPermission.project_id == project_a.project_id,
                    UserPermission.collection_id == shared_col.collection_id,
                    Permission.name == name,
                )
            ).first()
        }
        path_b = {
            name for name in _user_collection_permission_names(db, target.user_id, shared_col.collection_id)
            if db.exec(
                select(UserPermission)
                .join(Permission)
                .where(
                    UserPermission.user_id == target.user_id,
                    UserPermission.project_id == project_b.project_id,
                    UserPermission.collection_id == shared_col.collection_id,
                    Permission.name == name,
                )
            ).first()
        }
        assert path_a == set()
        assert "site:write" in path_b

    # ── is_admin edge cases ───────────────────────────────────────────────────

    def test_sync_is_admin_false_on_normal_user_by_non_admin_is_noop(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """非管理员操作者传 is_admin=false 给普通用户时，因为值未改变，应直接跳过而不触发 403。
        / Non-admin passing is_admin=false for a normal user (no change) should NOT raise 403."""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        normal_user_id = int(payload["sub"])

        # Give normal user a project:write so they're a valid manager
        proj = _create_project(db, user_id=1)
        _grant_project_perm(db, normal_user_id, proj.project_id, "project:write")

        # Create another normal user (role_id=2) to be the target
        target = _create_user(db)
        _grant_project_perm(db, target.user_id, proj.project_id, "project:read")
        r = client.put(
            f"{settings.API_V1_STR}/users/{target.user_id}/permissions",
            headers=normal_user_token_headers,
            json={"is_admin": False, "projects": []},
        )
        # is_admin=False and target is already not admin → no-op, should succeed
        assert r.status_code == 200

    def test_sync_is_admin_true_by_non_admin_is_forbidden(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """非管理员操作者传 is_admin=true 时，应拒绝 403。
        / Non-admin trying to set is_admin=true must be rejected with 403."""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        normal_user_id = int(payload["sub"])

        proj = _create_project(db, user_id=1)
        _grant_project_perm(db, normal_user_id, proj.project_id, "project:write")

        target = _create_user(db)
        r = client.put(
            f"{settings.API_V1_STR}/users/{target.user_id}/permissions",
            headers=normal_user_token_headers,
            json={"is_admin": True, "projects": []},
        )
        assert r.status_code == 403

    def test_collection_manager_cannot_submit_project_permissions(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """集合管理员不能在可见项目节点上提交 project:* 权限。"""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        manager_id = int(payload["sub"])

        target = _create_user(db)
        project = _create_project(db, user_id=1)
        collection = _create_collection(db, user_id=1)
        _link_project_collection(db, project.project_id, collection.collection_id)
        _grant_collection_perm(
            db,
            manager_id,
            collection.collection_id,
            "collection:write",
            project_id=project.project_id,
        )
        _grant_collection_perm(
            db,
            target.user_id,
            collection.collection_id,
            "collection:read",
            project_id=project.project_id,
        )

        r = client.put(
            f"{settings.API_V1_STR}/users/{target.user_id}/permissions",
            headers=normal_user_token_headers,
            json={
                "projects": [
                    _project_assignment(project.project_id, ["project:read"])
                ]
            },
        )

        assert r.status_code == 403
        assert "project:write" in r.json()["message"]

    def test_collection_manager_can_sync_own_collection_path_only(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """集合管理员只能修改自己管理的 project_id + collection_id 路径。"""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        manager_id = int(payload["sub"])

        target = _create_user(db)
        shared_col = _create_collection(db, user_id=1)
        project_a = _create_project(db, user_id=1)
        project_b = _create_project(db, user_id=1)
        _link_project_collection(db, project_a.project_id, shared_col.collection_id)
        _link_project_collection(db, project_b.project_id, shared_col.collection_id)
        _grant_collection_perm(
            db,
            manager_id,
            shared_col.collection_id,
            "collection:write",
            project_id=project_a.project_id,
        )
        _grant_collection_perm(
            db,
            target.user_id,
            shared_col.collection_id,
            "collection:read",
            project_id=project_a.project_id,
        )
        _grant_collection_perm(
            db,
            target.user_id,
            shared_col.collection_id,
            "site:write",
            project_id=project_b.project_id,
        )

        r = client.put(
            f"{settings.API_V1_STR}/users/{target.user_id}/permissions",
            headers=normal_user_token_headers,
            json={
                "projects": [
                    _project_assignment(
                        project_a.project_id,
                        [],
                        [
                            _collection_assignment(
                                project_a.project_id,
                                shared_col.collection_id,
                                ["annotation:write"],
                            )
                        ],
                    )
                ]
            },
        )

        assert r.status_code == 200
        assert _user_collection_permission_names_for_path(
            db,
            target.user_id,
            project_a.project_id,
            shared_col.collection_id,
        ) == {"annotation:write", "collection:read"}
        assert _user_collection_permission_names_for_path(
            db,
            target.user_id,
            project_b.project_id,
            shared_col.collection_id,
        ) == {"site:write"}


class TestGetUserPermissionConfig:
    """GET /users/{user_id}/permission-configuration"""

    def test_sorts_projects_and_collections_by_name_with_stable_id_tiebreaker(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Projects and nested collections are ordered by name, then ID."""
        user = _create_user(db)

        project_zulu = _rename_project(db, _create_project(db, user.user_id), "Zulu")
        project_alpha_1 = _rename_project(db, _create_project(db, user.user_id), "Alpha")
        project_alpha_2 = _rename_project(db, _create_project(db, user.user_id), "Alpha")

        collection_zulu = _rename_collection(db, _create_collection(db, user.user_id), "Zulu")
        collection_alpha_1 = _rename_collection(db, _create_collection(db, user.user_id), "Alpha")
        collection_alpha_2 = _rename_collection(db, _create_collection(db, user.user_id), "Alpha")

        _link_project_collection(db, project_zulu.project_id, collection_zulu.collection_id)
        _link_project_collection(db, project_zulu.project_id, collection_alpha_1.collection_id)
        _link_project_collection(db, project_zulu.project_id, collection_alpha_2.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/users/{user.user_id}/permission-configuration",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]

        created_projects = [
            p for p in data["projects"]
            if p["project_id"] in {project_zulu.project_id, project_alpha_1.project_id, project_alpha_2.project_id}
        ]
        assert [(p["project_name"], p["project_id"]) for p in created_projects] == [
            ("Alpha", min(project_alpha_1.project_id, project_alpha_2.project_id)),
            ("Alpha", max(project_alpha_1.project_id, project_alpha_2.project_id)),
            ("Zulu", project_zulu.project_id),
        ]

        zulu_project = next(p for p in data["projects"] if p["project_id"] == project_zulu.project_id)
        assert [
            (c["collection_name"], c["collection_id"]) for c in zulu_project["collections"]
            if c["collection_id"] in {
                collection_zulu.collection_id,
                collection_alpha_1.collection_id,
                collection_alpha_2.collection_id,
            }
        ] == [
            ("Alpha", min(collection_alpha_1.collection_id, collection_alpha_2.collection_id)),
            ("Alpha", max(collection_alpha_1.collection_id, collection_alpha_2.collection_id)),
            ("Zulu", collection_zulu.collection_id),
        ]

    def test_returns_tree_structure(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Response contains projects list with collections nested inside."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/users/{user.user_id}/permission-configuration",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert "is_admin" in data
        assert data["can_manage_admin_role"] is True
        assert "projects" in data
        # The created project should be present
        project_ids = [p["project_id"] for p in data["projects"]]
        assert proj.project_id in project_ids
        # The collection should be nested under the project
        proj_data = next(p for p in data["projects"] if p["project_id"] == proj.project_id)
        assert proj_data["can_manage_project"] is True
        assert "collections" in proj_data
        col_ids = [c["collection_id"] for c in proj_data["collections"]]
        assert col.collection_id in col_ids

    def test_includes_projects_without_permission(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Projects with no permissions are still included with empty stored_permissions."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)  # no permissions granted

        r = client.get(
            f"{settings.API_V1_STR}/users/{user.user_id}/permission-configuration",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        proj_data = next((p for p in data["projects"] if p["project_id"] == proj.project_id), None)
        assert proj_data is not None
        assert proj_data["stored_permissions"] == []
        assert proj_data["effective_permissions"] == []

    def test_returns_actual_stored_permissions(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Permissions are correctly returned per scope."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        _grant_project_perm(db, user.user_id, proj.project_id, "audio:write")
        _grant_collection_perm(db, user.user_id, col.collection_id, "site:read")

        r = client.get(
            f"{settings.API_V1_STR}/users/{user.user_id}/permission-configuration",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        proj_data = next(p for p in data["projects"] if p["project_id"] == proj.project_id)
        assert "audio:write" in proj_data["stored_permissions"]
        col_data = next(c for c in proj_data["collections"] if c["collection_id"] == col.collection_id)
        assert "site:read" in col_data["stored_permissions"]

    def test_collection_permissions_use_effective_inheritance(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """project:write should appear as effective collection permissions."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        _grant_project_perm(db, user.user_id, proj.project_id, "project:write")

        r = client.get(
            f"{settings.API_V1_STR}/users/{user.user_id}/permission-configuration",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        proj_data = next(p for p in data["projects"] if p["project_id"] == proj.project_id)
        col_data = next(c for c in proj_data["collections"] if c["collection_id"] == col.collection_id)

        assert col_data["stored_permissions"] == []
        assert "collection:write" in col_data["effective_permissions"]
        assert "site:write" in col_data["effective_permissions"]
        assert "site:read" not in col_data["effective_permissions"]

    def test_project_read_does_not_mark_collections_as_effective(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Project read grants the project itself, not collection-row permission badges."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        _grant_project_perm(db, user.user_id, proj.project_id, "project:read")

        r = client.get(
            f"{settings.API_V1_STR}/users/{user.user_id}/permission-configuration",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        proj_data = next(p for p in data["projects"] if p["project_id"] == proj.project_id)
        col_data = next(c for c in proj_data["collections"] if c["collection_id"] == col.collection_id)

        assert proj_data["stored_permissions"] == ["project:read"]
        assert col_data["stored_permissions"] == []
        assert col_data["effective_permissions"] == []

    def test_project_read_does_not_create_collection_scope_effective_rows(
        self, db: Session
    ) -> None:
        """project:read must not create collection-scope effective rows."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        _grant_project_perm(db, user.user_id, proj.project_id, "project:read")

        rows = db.exec(
            select(UserEffectivePermission).where(
                UserEffectivePermission.user_id == user.user_id,
                UserEffectivePermission.project_id == proj.project_id,
                UserEffectivePermission.collection_id == col.collection_id,
            )
        ).all()

        assert rows == []
        assert not permission_repository.has_any_accessible_collection(db, user.user_id)

    def test_collection_permissions_minimize_read_when_write_exists(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """If both read/write are effective for same resource, return write only."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        _grant_project_perm(db, user.user_id, proj.project_id, "project:write")
        _grant_project_perm(db, user.user_id, proj.project_id, "site:read")

        r = client.get(
            f"{settings.API_V1_STR}/users/{user.user_id}/permission-configuration",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        proj_data = next(p for p in data["projects"] if p["project_id"] == proj.project_id)
        col_data = next(c for c in proj_data["collections"] if c["collection_id"] == col.collection_id)

        assert "site:write" in col_data["effective_permissions"]
        assert "site:read" not in col_data["effective_permissions"]

    def test_project_module_permissions_are_effective_on_collections(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Project-level module grants are inherited by all child collection rows."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(
                        proj.project_id,
                        ["audio:read", "site:write", "annotation:read", "review:write"],
                    )
                ]
            },
        )
        assert r.status_code == 200

        r = client.get(
            f"{settings.API_V1_STR}/users/{user.user_id}/permission-configuration",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        proj_data = next(p for p in data["projects"] if p["project_id"] == proj.project_id)
        col_data = next(c for c in proj_data["collections"] if c["collection_id"] == col.collection_id)

        assert col_data["stored_permissions"] == []
        assert "audio:read" in col_data["effective_permissions"]
        assert "site:write" in col_data["effective_permissions"]
        assert "annotation:read" in col_data["effective_permissions"]
        assert "review:write" in col_data["effective_permissions"]

    def test_collection_stores_only_permissions_not_covered_by_project(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Mixed project+collection grants keep only explicit collection extras stored."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/users/{user.user_id}/permissions",
            headers=superuser_token_headers,
            json={
                "projects": [
                    _project_assignment(
                        proj.project_id,
                        ["review:write"],
                        [_collection_assignment(proj.project_id, col.collection_id, ["audio:read"])],
                    )
                ]
            },
        )
        assert r.status_code == 200

        assert _user_collection_permission_names(db, user.user_id, col.collection_id) == {
            "audio:read",
            "collection:read",
        }

        r = client.get(
            f"{settings.API_V1_STR}/users/{user.user_id}/permission-configuration",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        proj_data = next(p for p in data["projects"] if p["project_id"] == proj.project_id)
        col_data = next(c for c in proj_data["collections"] if c["collection_id"] == col.collection_id)

        assert "audio:read" in col_data["stored_permissions"]
        assert "review:write" not in col_data["stored_permissions"]
        assert "audio:read" in col_data["effective_permissions"]
        assert "review:write" in col_data["effective_permissions"]

    def test_project_manager_sees_only_managed_project_tree(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Project managers only receive projects where they have project:write."""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        manager_id = int(payload["sub"])

        target = _create_user(db)
        managed = _create_project(db, manager_id)
        unmanaged = _create_project(db, manager_id)
        managed_col = _create_collection(db, manager_id)
        unmanaged_col = _create_collection(db, manager_id)
        _link_project_collection(db, managed.project_id, managed_col.collection_id)
        _link_project_collection(db, unmanaged.project_id, unmanaged_col.collection_id)

        _grant_project_perm(db, manager_id, managed.project_id, "project:write")
        _grant_project_perm(db, target.user_id, managed.project_id, "project:read")
        _grant_project_perm(db, target.user_id, unmanaged.project_id, "project:read")

        r = client.get(
            f"{settings.API_V1_STR}/users/{target.user_id}/permission-configuration",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["can_manage_admin_role"] is False
        projects = data["projects"]
        assert [p["project_id"] for p in projects] == [managed.project_id]
        assert projects[0]["can_manage_project"] is True
        assert {c["collection_id"] for c in projects[0]["collections"]} == {managed_col.collection_id}

    def test_collection_manager_sees_only_project_collection_path(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Collection managers only receive their project-local collection path."""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        manager_id = int(payload["sub"])

        target = _create_user(db)
        shared_col = _create_collection(db, manager_id)
        project_a = _create_project(db, manager_id)
        project_b = _create_project(db, manager_id)
        _link_project_collection(db, project_a.project_id, shared_col.collection_id)
        _link_project_collection(db, project_b.project_id, shared_col.collection_id)

        _grant_collection_perm(
            db,
            manager_id,
            shared_col.collection_id,
            "collection:write",
            project_id=project_a.project_id,
        )
        _grant_collection_perm(
            db,
            target.user_id,
            shared_col.collection_id,
            "collection:read",
            project_id=project_a.project_id,
        )
        _grant_collection_perm(
            db,
            target.user_id,
            shared_col.collection_id,
            "collection:read",
            project_id=project_b.project_id,
        )

        r = client.get(
            f"{settings.API_V1_STR}/users/{target.user_id}/permission-configuration",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["can_manage_admin_role"] is False
        projects = data["projects"]
        assert [p["project_id"] for p in projects] == [project_a.project_id]
        assert projects[0]["can_manage_project"] is False
        assert [c["collection_id"] for c in projects[0]["collections"]] == [shared_col.collection_id]

    def test_manager_cannot_get_admin_permission_configuration(
        self, client: TestClient, normal_user_token_headers: dict[str, str]
    ) -> None:
        """Managers cannot view admin users' permission configuration."""
        r = client.get(
            f"{settings.API_V1_STR}/users/1/permission-configuration",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 403

    def test_manager_cannot_get_out_of_scope_permission_configuration(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Managers cannot view ordinary users outside their management scope."""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        manager_id = int(payload["sub"])

        target = _create_user(db)
        managed = _create_project(db, manager_id)
        other = _create_project(db, manager_id)
        _grant_project_perm(db, manager_id, managed.project_id, "project:write")
        _grant_project_perm(db, target.user_id, other.project_id, "project:read")

        r = client.get(
            f"{settings.API_V1_STR}/users/{target.user_id}/permission-configuration",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 403

    def test_is_admin_reflects_user_role(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """is_admin is True for admin user, False for normal user."""
        normal_user = _create_user(db)
        r = client.get(
            f"{settings.API_V1_STR}/users/{normal_user.user_id}/permission-configuration",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.json()["data"]["is_admin"] is False
        assert r.json()["data"]["can_manage_admin_role"] is True

    def test_user_not_found_404(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        """Non-existent user returns 404."""
        r = client.get(
            f"{settings.API_V1_STR}/users/99999/permission-configuration",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404

    def test_anonymous_401(self, client: TestClient) -> None:
        """Anonymous request returns 401."""
        r = client.get(f"{settings.API_V1_STR}/users/1/permission-configuration")
        assert r.status_code == 401


# ─── Unit/Integration tests for has_resource_permission() ────────────────────


class TestStep2PublicResource:
    """Step 2: Public resource gives read access to self only (not sub-resources)."""

    def test_public_collection_read_allowed(self, db: Session) -> None:
        """Public collection: any user can read the collection itself."""
        user = _create_user(db)
        col = _create_collection(db, user.user_id, public_access=True)
        assert has_resource_permission(db, user, "collection", "read", collection_id=col.collection_id)

    def test_public_collection_write_denied(self, db: Session) -> None:
        """Public collection does NOT grant write access."""
        user = _create_user(db)
        col = _create_collection(db, user.user_id, public_access=True)
        assert not has_resource_permission(db, user, "collection", "write", collection_id=col.collection_id)

    def test_public_collection_inherits_to_audio(self, db: Session) -> None:
        """Public collection (public_access=True) grants audio:read."""
        user = _create_user(db)
        col = _create_collection(db, user.user_id, public_access=True)
        assert has_resource_permission(db, user, "audio", "read", collection_id=col.collection_id)

    def test_public_collection_inherits_to_site(self, db: Session) -> None:
        """Public collection (public_access=True) grants site:read."""
        user = _create_user(db)
        col = _create_collection(db, user.user_id, public_access=True)
        assert has_resource_permission(db, user, "site", "read", collection_id=col.collection_id)

    def test_public_collection_does_not_inherit_audio_write(self, db: Session) -> None:
        """Public collection does NOT grant audio:write."""
        user = _create_user(db)
        col = _create_collection(db, user.user_id, public_access=True)
        assert not has_resource_permission(db, user, "audio", "write", collection_id=col.collection_id)

    def test_public_collection_does_not_inherit_to_annotation_without_public_tags(self, db: Session) -> None:
        """public_access alone does NOT grant annotation:read; need public_tags for that."""
        user = _create_user(db)
        col = _create_collection(db, user.user_id, public_access=True)
        assert not has_resource_permission(db, user, "annotation", "read", collection_id=col.collection_id)

    def test_public_project_read_allowed(self, db: Session) -> None:
        """Public project: any user can read the project itself."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id, public=True)
        assert has_resource_permission(db, user, "project", "read", project_id=proj.project_id)

    def test_public_project_does_not_inherit_to_collection(self, db: Session) -> None:
        """Public project does NOT grant collection:read."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id, public=True)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        assert not has_resource_permission(db, user, "collection", "read", collection_id=col.collection_id)


class TestStep3DirectCollectionPermission:
    """Step 3: Direct collection-level permission match."""

    def test_direct_audio_read(self, db: Session) -> None:
        user = _create_user(db)
        col = _create_collection(db, user.user_id)
        _grant_collection_perm(db, user.user_id, col.collection_id, "audio:read")
        assert has_resource_permission(db, user, "audio", "read", collection_id=col.collection_id)

    def test_direct_audio_write_implies_read(self, db: Session) -> None:
        """audio:write at collection scope implies audio:read via step 7."""
        user = _create_user(db)
        col = _create_collection(db, user.user_id)
        _grant_collection_perm(db, user.user_id, col.collection_id, "audio:write")
        assert has_resource_permission(db, user, "audio", "read", collection_id=col.collection_id)

    def test_no_permission_denied(self, db: Session) -> None:
        user = _create_user(db)
        col = _create_collection(db, user.user_id)
        assert not has_resource_permission(db, user, "audio", "read", collection_id=col.collection_id)

    def test_permission_does_not_bleed_to_other_collection(self, db: Session) -> None:
        user = _create_user(db)
        col_a = _create_collection(db, user.user_id)
        col_b = _create_collection(db, user.user_id)
        _grant_collection_perm(db, user.user_id, col_a.collection_id, "audio:write")
        # col_a has permission, col_b must not
        assert has_resource_permission(db, user, "audio", "write", collection_id=col_a.collection_id)
        assert not has_resource_permission(db, user, "audio", "write", collection_id=col_b.collection_id)


class TestStep4ProjectLevelInheritance:
    """Step 4: Project-level binding makes permission inherit to all collections under that project."""

    def test_audio_read_at_project_level_inherits_to_collection(self, db: Session) -> None:
        """audio:read bound at project scope is inherited by its collection."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        _grant_project_perm(db, user.user_id, proj.project_id, "audio:read")

        assert has_resource_permission(db, user, "audio", "read", collection_id=col.collection_id)

    def test_project_level_perm_not_applied_to_unrelated_collection(self, db: Session) -> None:
        """Project-level permission must NOT bleed to collections in other projects."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col_in_proj = _create_collection(db, user.user_id)
        col_out = _create_collection(db, user.user_id)  # not linked to proj
        _link_project_collection(db, proj.project_id, col_in_proj.collection_id)
        _grant_project_perm(db, user.user_id, proj.project_id, "audio:read")

        assert has_resource_permission(db, user, "audio", "read", collection_id=col_in_proj.collection_id)
        assert not has_resource_permission(db, user, "audio", "read", collection_id=col_out.collection_id)

    def test_project_read_does_not_cascade_to_sub_resources(self, db: Session) -> None:
        """project:read on project scope does NOT cascade to sub-resources (only direct match, step 4)."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        # project:read is granted at project scope — this only grants project resource itself
        # via step 4, because resource_type='project' is matched, not collection/audio
        _grant_project_perm(db, user.user_id, proj.project_id, "project:read")

        # project:read should NOT cascade to audio
        assert not has_resource_permission(db, user, "audio", "read", collection_id=col.collection_id)


class TestStep5CollectionWrite:
    """Step 5: collection:write implies all sub-resource read+write at collection scope."""

    def test_collection_write_implies_all_sub_resources(self, db: Session) -> None:
        user = _create_user(db)
        col = _create_collection(db, user.user_id)
        _grant_collection_perm(db, user.user_id, col.collection_id, "collection:write")

        for res in _SUB_RESOURCE_TYPES:
            assert has_resource_permission(db, user, res, "read", collection_id=col.collection_id), \
                f"collection:write should imply {res}:read"
            assert has_resource_permission(db, user, res, "write", collection_id=col.collection_id), \
                f"collection:write should imply {res}:write"

    def test_collection_write_does_not_grant_project_permissions(self, db: Session) -> None:
        """collection:write must NOT grant project:read or project:write."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        _grant_collection_perm(db, user.user_id, col.collection_id, "collection:write")

        assert not has_resource_permission(db, user, "project", "read", project_id=proj.project_id)
        assert not has_resource_permission(db, user, "project", "write", project_id=proj.project_id)


class TestStep6ProjectWrite:
    """Step 6: project:write implies collection:write on all collections under that project."""

    def test_project_write_implies_all_sub_resources_via_collection(self, db: Session) -> None:
        """project:write bound at project scope implies all sub-resources for all collections."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        _grant_project_perm(db, user.user_id, proj.project_id, "project:write")

        for res in _SUB_RESOURCE_TYPES:
            assert has_resource_permission(db, user, res, "read", collection_id=col.collection_id), \
                f"project:write should imply {res}:read via collection"
            assert has_resource_permission(db, user, res, "write", collection_id=col.collection_id), \
                f"project:write should imply {res}:write via collection"

    def test_project_write_implies_collection_write_itself(self, db: Session) -> None:
        """project:write also grants collection:write on collections under it."""
        user = _create_user(db)
        proj = _create_project(db, user.user_id)
        col = _create_collection(db, user.user_id)
        _link_project_collection(db, proj.project_id, col.collection_id)
        _grant_project_perm(db, user.user_id, proj.project_id, "project:write")

        assert has_resource_permission(db, user, "collection", "write", collection_id=col.collection_id)

    def test_project_write_does_not_apply_to_unrelated_collection(self, db: Session) -> None:
        """project:write on project A must NOT grant access on collections in project B."""
        user = _create_user(db)
        proj_a = _create_project(db, user.user_id)
        proj_b = _create_project(db, user.user_id)
        col_a = _create_collection(db, user.user_id)
        col_b = _create_collection(db, user.user_id)
        _link_project_collection(db, proj_a.project_id, col_a.collection_id)
        _link_project_collection(db, proj_b.project_id, col_b.collection_id)
        _grant_project_perm(db, user.user_id, proj_a.project_id, "project:write")

        # col_a: should pass
        assert has_resource_permission(db, user, "audio", "read", collection_id=col_a.collection_id)
        # col_b: must NOT pass
        assert not has_resource_permission(db, user, "audio", "read", collection_id=col_b.collection_id)


class TestStep7WriteImpliesRead:
    """Step 7: write implies read for same resource."""

    def test_audio_write_implies_audio_read(self, db: Session) -> None:
        user = _create_user(db)
        col = _create_collection(db, user.user_id)
        _grant_collection_perm(db, user.user_id, col.collection_id, "audio:write")
        assert has_resource_permission(db, user, "audio", "read", collection_id=col.collection_id)

    def test_audio_read_does_not_imply_audio_write(self, db: Session) -> None:
        user = _create_user(db)
        col = _create_collection(db, user.user_id)
        _grant_collection_perm(db, user.user_id, col.collection_id, "audio:read")
        assert not has_resource_permission(db, user, "audio", "write", collection_id=col.collection_id)


class TestSubResourceTypesConstant:
    """Verify _SUB_RESOURCE_TYPES contains expected members."""

    def test_sub_resource_types_include_audio(self) -> None:
        assert "audio" in _SUB_RESOURCE_TYPES

    def test_sub_resource_types_include_site(self) -> None:
        assert "site" in _SUB_RESOURCE_TYPES

    def test_sub_resource_types_include_annotation(self) -> None:
        assert "annotation" in _SUB_RESOURCE_TYPES

    def test_sub_resource_types_include_review(self) -> None:
        assert "review" in _SUB_RESOURCE_TYPES

    def test_sub_resource_types_do_not_include_project(self) -> None:
        assert "project" not in _SUB_RESOURCE_TYPES

    def test_sub_resource_types_do_not_include_collection(self) -> None:
        assert "collection" not in _SUB_RESOURCE_TYPES

    def test_sub_resource_types_do_not_include_queue(self) -> None:
        """queue is excluded from the permission system."""
        assert "queue" not in _SUB_RESOURCE_TYPES

    def test_sub_resource_types_do_not_include_task(self) -> None:
        """task is excluded from _SUB_RESOURCE_TYPES (access controlled via collection:write)."""
        assert "task" not in _SUB_RESOURCE_TYPES

    def test_sub_resource_types_do_not_include_index_log(self) -> None:
        """index_log is excluded from _SUB_RESOURCE_TYPES (access controlled via collection:write)."""
        assert "index_log" not in _SUB_RESOURCE_TYPES


class TestPublicTagsAnnotationAccess:
    """Step 2 extension: public_tags=True grants annotation:read."""

    def test_public_tags_grants_annotation_read(self, db: Session) -> None:
        """collection.public_tags=True → any user can read annotations in it."""
        user = _create_user(db)
        col = Collection(
            name=f"col_{random_lower_string()[:8]}",
            creator_id=user.user_id,
            public_access=False,
            public_tags=True,
        )
        db.add(col)
        db.commit()
        db.refresh(col)
        project = _create_project(db, user.user_id, public=True)
        _link_project_collection(db, project.project_id, col.collection_id)
        assert has_resource_permission(db, user, "annotation", "read", collection_id=col.collection_id)

    def test_public_tags_does_not_grant_annotation_write(self, db: Session) -> None:
        """public_tags does NOT grant annotation:write."""
        user = _create_user(db)
        col = Collection(
            name=f"col_{random_lower_string()[:8]}",
            creator_id=user.user_id,
            public_access=False,
            public_tags=True,
        )
        db.add(col)
        db.commit()
        db.refresh(col)
        project = _create_project(db, user.user_id, public=True)
        _link_project_collection(db, project.project_id, col.collection_id)
        assert not has_resource_permission(db, user, "annotation", "write", collection_id=col.collection_id)

    def test_public_tags_false_does_not_grant_annotation_read(self, db: Session) -> None:
        """public_tags=False → no annotation:read without explicit permission."""
        user = _create_user(db)
        col = _create_collection(db, user.user_id, public_access=False)
        assert not has_resource_permission(db, user, "annotation", "read", collection_id=col.collection_id)
