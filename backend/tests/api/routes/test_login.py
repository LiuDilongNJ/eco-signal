import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.core.security import verify_password
from app.repositories import user_repository
from app.schemas import UserCreate
from app.services import auth_service
from app.utils import generate_password_reset_token
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def test_get_access_token(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/auth-tokens", data=login_data)
    payload = r.json()
    assert r.status_code == 200
    assert "access_token" in payload
    assert payload["access_token"]
    assert payload["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert payload["token_type"] == "bearer"
    assert settings.AUTH_REFRESH_COOKIE_NAME in r.cookies


def test_get_access_token_incorrect_password(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": "incorrect",
    }
    r = client.post(f"{settings.API_V1_STR}/auth-tokens", data=login_data)
    assert r.status_code == 400


def test_refresh_access_token_rotates_cookie(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    login_resp = client.post(f"{settings.API_V1_STR}/auth-tokens", data=login_data)
    old_refresh = login_resp.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    assert old_refresh

    refresh_resp = client.post(f"{settings.API_V1_STR}/auth-token-refreshes")
    payload = refresh_resp.json()
    new_refresh = refresh_resp.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)

    assert refresh_resp.status_code == 200
    assert payload["code"] == 0
    assert payload["data"]["access_token"]
    assert payload["data"]["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert new_refresh
    assert new_refresh != old_refresh


def test_refresh_reuse_detected_revokes_family(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Disable grace period so any replay is immediately treated as an attack.
    monkeypatch.setattr(auth_service.settings, "REFRESH_GRACE_PERIOD_SECONDS", 0)

    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    login_resp = client.post(f"{settings.API_V1_STR}/auth-tokens", data=login_data)
    stolen_refresh = login_resp.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    assert stolen_refresh

    first_refresh = client.post(f"{settings.API_V1_STR}/auth-token-refreshes")
    assert first_refresh.status_code == 200

    # Replay the original token — with grace period off, this triggers family revocation.
    client.cookies.set(settings.AUTH_REFRESH_COOKIE_NAME, stolen_refresh)
    replay_resp = client.post(f"{settings.API_V1_STR}/auth-token-refreshes")
    assert replay_resp.status_code == 401
    assert replay_resp.json()["message"] == "Refresh token reuse detected"

    # The rotated token must also be blocked because the whole family was revoked.
    rotated_refresh = first_refresh.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    assert rotated_refresh
    client.cookies.set(settings.AUTH_REFRESH_COOKIE_NAME, rotated_refresh)
    blocked_resp = client.post(f"{settings.API_V1_STR}/auth-token-refreshes")
    assert blocked_resp.status_code == 401


def test_concurrent_refresh_within_grace_period(client: TestClient) -> None:
    """Refresh requests replaying the same old cookie converge on the same rotated token."""
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    login_resp = client.post(f"{settings.API_V1_STR}/auth-tokens", data=login_data)
    original_refresh = login_resp.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    assert original_refresh

    # First refresh rotates the token.
    first_resp = client.post(f"{settings.API_V1_STR}/auth-token-refreshes")
    assert first_resp.status_code == 200
    rotated_cookie = first_resp.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    assert rotated_cookie

    # Second request with the original (now rotated) token — simulates a concurrent call
    # or a retry after a lost response. Within the grace window the server returns the
    # SAME cached replacement instead of rotating again (idempotent refresh).
    client.cookies.set(settings.AUTH_REFRESH_COOKIE_NAME, original_refresh)
    second_resp = client.post(f"{settings.API_V1_STR}/auth-token-refreshes")
    assert second_resp.status_code == 200
    assert second_resp.json()["data"]["access_token"]

    new_cookie = second_resp.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    assert new_cookie and new_cookie != original_refresh
    assert new_cookie == rotated_cookie


def test_logout_clears_cookie_and_blocks_refresh(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    login_resp = client.post(f"{settings.API_V1_STR}/auth-tokens", data=login_data)
    assert login_resp.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)

    logout_resp = client.delete(f"{settings.API_V1_STR}/auth-tokens/current")
    assert logout_resp.status_code == 200
    assert logout_resp.json()["message"] == "logged out"

    refresh_resp = client.post(f"{settings.API_V1_STR}/auth-token-refreshes")
    assert refresh_resp.status_code == 401


def test_reset_password(client: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    new_password = random_lower_string()

    user_create = UserCreate(
        username=random_lower_string()[:20],
        name="Test User",
        email=email,
        password=password,
    )
    user = user_repository.create(session=db, obj_in=user_create)
    login_resp = client.post(
        f"{settings.API_V1_STR}/auth-tokens",
        data={"username": user.username, "password": password},
    )
    refresh_token = login_resp.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    assert refresh_token

    token = generate_password_reset_token(email=email)
    headers = user_authentication_headers(client=client, username=user.username, password=password)
    data = {"new_password": new_password, "token": token}

    r = client.post(
        f"{settings.API_V1_STR}/password-resets",
        headers=headers,
        json=data,
    )

    assert r.status_code == 200
    json_resp = r.json()
    assert json_resp["code"] == 0
    assert json_resp["message"] == "Password updated successfully"
    assert "meta" in json_resp

    db.refresh(user)
    assert verify_password(new_password, user.password)

    client.cookies.set(settings.AUTH_REFRESH_COOKIE_NAME, refresh_token)
    refresh_resp = client.post(f"{settings.API_V1_STR}/auth-token-refreshes")
    assert refresh_resp.status_code == 401


def test_reset_password_invalid_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"new_password": "changethis", "token": "invalid"}
    r = client.post(
        f"{settings.API_V1_STR}/password-resets",
        headers=superuser_token_headers,
        json=data,
    )
    response = r.json()

    assert "message" in response
    assert r.status_code == 400
    assert response["message"] == "Invalid token"
