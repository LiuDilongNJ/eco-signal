"""
Roles API routes tests.

This module contains tests for the roles API endpoints.
"""
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from tests.utils.user import create_random_user


def test_update_user_role_admin_success(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """Test that an admin can successfully change a user's role to admin and back."""
    # Create a normal test user
    user = create_random_user(db)
    user.role_id = 2
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Assert initial role is normal user (2)
    assert user.role_id == 2
    
    # 1. Promote to Admin
    r = client.put(
        f"{settings.API_V1_STR}/users/{user.user_id}/role-assignment",
        headers=superuser_token_headers,
        json={"is_admin": True}
    )
    assert r.status_code == 200
    json_resp = r.json()
    assert json_resp["code"] == 0
    
    db.refresh(user)
    assert user.role_id == 1  # Verify role updated to admin
    
    # 2. Demote back to normal user
    r2 = client.put(
        f"{settings.API_V1_STR}/users/{user.user_id}/role-assignment",
        headers=superuser_token_headers,
        json={"is_admin": False}
    )
    assert r2.status_code == 200
    
    db.refresh(user)
    assert user.role_id == 2  # Verify role updated to normal user


def test_update_user_role_forbidden(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    """Test that a normal user cannot change roles."""
    user = create_random_user(db)
    user.role_id = 2
    db.add(user)
    db.commit()
    db.refresh(user)
    
    r = client.put(
        f"{settings.API_V1_STR}/users/{user.user_id}/role-assignment",
        headers=normal_user_token_headers,
        json={"is_admin": True}
    )
    assert r.status_code == 403


def test_update_user_role_not_found(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """Test changing role of a non-existent user."""
    r = client.put(
        f"{settings.API_V1_STR}/users/99999/role-assignment",
        headers=superuser_token_headers,
        json={"is_admin": True}
    )
    assert r.status_code == 404
