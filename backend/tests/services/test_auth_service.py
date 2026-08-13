from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import HTTPException
from redis.exceptions import RedisError
from sqlmodel import Session

from app.repositories import user_repository
from app.schemas import UserCreate
from app.services import auth_service
from tests.utils.utils import random_email, random_lower_string


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FakeAsyncRedis:
    """Minimal async redis stand-in for the login rate-limit counters."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    async def get(self, key: str):
        value = self.store.get(key)
        return None if value is None else str(value).encode()

    async def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key: str, seconds: int) -> None:
        return None

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


class FakeRefreshSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.family_revoked: set[str] = set()
        self.replacement_tokens: dict[str, str] = {}
        self.activity_states: dict[str, str] = {}
        self.activity_error: RedisError | None = None
        self.initialization_error: RedisError | None = None

    async def initialize_family_activity(
        self, redis, family_id: str, *, timeout_seconds: int
    ) -> None:
        if self.initialization_error:
            raise self.initialization_error
        self.activity_states[family_id] = "active"

    async def touch_family_activity(
        self, redis, family_id: str, *, timeout_seconds: int
    ) -> str:
        if self.activity_error:
            raise self.activity_error
        return self.activity_states.get(family_id, "expired")

    async def cache_replacement_token(
        self, redis, parent_jti: str, refresh_token: str, *, grace_seconds: int
    ) -> None:
        if grace_seconds <= 0:
            return
        self.replacement_tokens[parent_jti] = refresh_token

    async def get_replacement_token(self, redis, parent_jti: str) -> str | None:
        return self.replacement_tokens.get(parent_jti)

    async def create_session(self, redis, **kwargs) -> None:
        self.sessions[kwargs["jti"]] = {
            **kwargs,
            "revoked_at": None,
            "replaced_by_jti": None,
        }

    async def get_session_by_jti(self, redis, jti: str) -> dict[str, Any] | None:
        return self.sessions.get(jti)

    async def revoke_session(self, redis, jti: str, *, replaced_by_jti: str | None = None) -> None:
        session_data = self.sessions.get(jti)
        if not session_data:
            return
        if session_data["revoked_at"] is None:
            session_data["revoked_at"] = _now()
        if replaced_by_jti:
            session_data["replaced_by_jti"] = replaced_by_jti

    async def is_family_revoked(self, redis, family_id: str) -> bool:
        return family_id in self.family_revoked

    async def revoke_family(self, redis, family_id: str, *, family_expires_at=None) -> None:
        self.family_revoked.add(family_id)
        self.activity_states.pop(family_id, None)
        for session_data in self.sessions.values():
            if session_data["family_id"] == family_id and session_data["revoked_at"] is None:
                session_data["revoked_at"] = _now()

    async def revoke_user_sessions(self, redis, user_id: int) -> None:
        for session_data in self.sessions.values():
            if session_data["user_id"] == user_id:
                await self.revoke_family(redis, session_data["family_id"])

    async def resolve_replacement_session(
        self, redis, session: dict, *, grace_seconds: int = 60
    ) -> dict | None:
        if grace_seconds <= 0:
            return None
        now = _now()
        current = session
        for _ in range(5):
            revoked_at = current["revoked_at"]
            if revoked_at is None or (now - revoked_at).total_seconds() > grace_seconds:
                return None
            replacement_jti = current.get("replaced_by_jti")
            if not replacement_jti:
                return None
            current = self.sessions.get(replacement_jti)
            if not current:
                return None
            if current["revoked_at"] is None:
                return current
        return None


def _make_user(db: Session) -> tuple[Any, str]:
    password = random_lower_string()
    user = user_repository.create(
        session=db,
        obj_in=UserCreate(
            username=random_lower_string()[:20],
            name="Auth Service User",
            email=random_email(),
            password=password,
        ),
    )
    return user, password


@pytest.mark.anyio
async def test_login_issues_refresh_token_row(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    user, password = _make_user(db)
    fake_repo = FakeRefreshSessionRepository()
    monkeypatch.setattr(auth_service, "auth_refresh_session_repository", fake_repo)
    monkeypatch.setattr(auth_service.settings, "AUTH_SESSION_ABSOLUTE_EXPIRE_MINUTES", 60 * 24 * 90)

    access_token, refresh_token, refresh_max_age = await auth_service.login(
        db, FakeAsyncRedis(), user.username, password, client_ip="127.0.0.1", user_agent="pytest"
    )

    assert access_token.access_token
    assert access_token.expires_in > 0
    assert refresh_token
    assert refresh_max_age > 0

    assert len(fake_repo.sessions) == 1
    row = list(fake_repo.sessions.values())[-1]
    assert row["user_id"] == user.user_id
    assert row["family_expires_at"] > row["expires_at"]


@pytest.mark.anyio
async def test_idle_timeout_rejects_and_revokes_session_family(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, password = _make_user(db)
    fake_repo = FakeRefreshSessionRepository()
    monkeypatch.setattr(auth_service, "auth_refresh_session_repository", fake_repo)
    monkeypatch.setattr(auth_service.settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(auth_service.settings, "AUTH_SESSION_IDLE_EXPIRE_MINUTES", 30)

    token, refresh_token, _ = await auth_service.login(
        db, FakeAsyncRedis(), user.username, password
    )
    family_id = next(iter(fake_repo.sessions.values()))["family_id"]
    assert token.session_idle_timeout_seconds == 1800
    fake_repo.activity_states.pop(family_id)

    with pytest.raises(HTTPException) as exc:
        await auth_service.refresh_access_token(db, object(), refresh_token)

    assert exc.value.status_code == 401
    assert exc.value.headers == {
        "WWW-Authenticate": "Bearer",
        "X-Auth-Reason": "idle_timeout",
    }
    assert family_id in fake_repo.family_revoked


@pytest.mark.anyio
async def test_session_activity_validation_handles_active_revoked_and_missing_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = FakeRefreshSessionRepository()
    monkeypatch.setattr(auth_service, "auth_refresh_session_repository", fake_repo)
    monkeypatch.setattr(auth_service.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(auth_service.settings, "AUTH_SESSION_IDLE_EXPIRE_MINUTES", 30)
    fake_repo.activity_states["active-family"] = "active"
    fake_repo.activity_states["revoked-family"] = "revoked"

    await auth_service.validate_session_activity(object(), "active-family", user_id="7")

    with pytest.raises(HTTPException) as missing:
        await auth_service.validate_session_activity(object(), None, user_id="7")
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as revoked:
        await auth_service.validate_session_activity(object(), "revoked-family", user_id="7")
    assert revoked.value.status_code == 401
    assert revoked.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.anyio
async def test_session_activity_redis_failures_return_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = FakeRefreshSessionRepository()
    monkeypatch.setattr(auth_service, "auth_refresh_session_repository", fake_repo)
    monkeypatch.setattr(auth_service.settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(auth_service.settings, "AUTH_SESSION_IDLE_EXPIRE_MINUTES", 30)
    fake_repo.activity_error = RedisError("unavailable")

    with pytest.raises(HTTPException) as validation:
        await auth_service.validate_session_activity(object(), "family-id")
    assert validation.value.status_code == 503

    fake_repo.activity_error = None
    fake_repo.initialization_error = RedisError("unavailable")
    with pytest.raises(HTTPException) as initialization:
        await auth_service.initialize_session_activity(object(), "family-id")
    assert initialization.value.status_code == 503


@pytest.mark.anyio
async def test_refresh_rejects_expired_invalid_and_unknown_tokens(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_repo = FakeRefreshSessionRepository()
    monkeypatch.setattr(auth_service, "auth_refresh_session_repository", fake_repo)

    expired_jti = "expired-jti"
    expired_token = auth_service.security.create_refresh_token(
        subject="1",
        expires_delta=timedelta(seconds=-1),
        jti=expired_jti,
        family_id="expired-family",
    )
    fake_repo.sessions[expired_jti] = {
        "revoked_at": None,
        "replaced_by_jti": None,
    }
    with pytest.raises(HTTPException) as expired:
        await auth_service.refresh_access_token(db, object(), expired_token)
    assert expired.value.status_code == 401
    assert fake_repo.sessions[expired_jti]["revoked_at"] is not None

    with pytest.raises(HTTPException) as invalid:
        await auth_service.refresh_access_token(db, object(), "invalid-token")
    assert invalid.value.status_code == 401

    unknown_token = auth_service.security.create_refresh_token(
        subject="1",
        expires_delta=timedelta(minutes=5),
        jti="unknown-jti",
        family_id="unknown-family",
    )
    with pytest.raises(HTTPException) as unknown:
        await auth_service.refresh_access_token(db, object(), unknown_token)
    assert unknown.value.status_code == 401


@pytest.mark.anyio
async def test_refresh_rolls_without_absolute_session_expiry(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, password = _make_user(db)
    fake_repo = FakeRefreshSessionRepository()
    monkeypatch.setattr(auth_service, "auth_refresh_session_repository", fake_repo)
    monkeypatch.setattr(auth_service.settings, "AUTH_SESSION_ABSOLUTE_EXPIRE_MINUTES", 0)

    _, refresh_token, _ = await auth_service.login(db, FakeAsyncRedis(), user.username, password)
    row = next(iter(fake_repo.sessions.values()))
    assert row["family_expires_at"] is None

    _, new_refresh_token, refresh_max_age = await auth_service.refresh_access_token(
        db, object(), refresh_token
    )

    assert new_refresh_token != refresh_token
    assert refresh_max_age > 0
    assert len(fake_repo.sessions) == 2
    assert all(session["family_expires_at"] is None for session in fake_repo.sessions.values())


@pytest.mark.anyio
async def test_refresh_ignores_legacy_family_expiry_when_absolute_expiry_disabled(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, password = _make_user(db)
    fake_repo = FakeRefreshSessionRepository()
    monkeypatch.setattr(auth_service, "auth_refresh_session_repository", fake_repo)
    monkeypatch.setattr(auth_service.settings, "AUTH_SESSION_ABSOLUTE_EXPIRE_MINUTES", 60 * 24 * 90)

    _, refresh_token, _ = await auth_service.login(db, FakeAsyncRedis(), user.username, password)
    legacy_row = next(iter(fake_repo.sessions.values()))
    legacy_row["family_expires_at"] = _now() - timedelta(seconds=1)

    monkeypatch.setattr(auth_service.settings, "AUTH_SESSION_ABSOLUTE_EXPIRE_MINUTES", 0)
    _, new_refresh_token, _ = await auth_service.refresh_access_token(db, object(), refresh_token)

    assert new_refresh_token != refresh_token
    assert any(session["family_expires_at"] is None for session in fake_repo.sessions.values())


@pytest.mark.anyio
async def test_refresh_fails_when_session_absolute_expired(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, password = _make_user(db)
    fake_repo = FakeRefreshSessionRepository()
    monkeypatch.setattr(auth_service, "auth_refresh_session_repository", fake_repo)
    monkeypatch.setattr(auth_service.settings, "AUTH_SESSION_ABSOLUTE_EXPIRE_MINUTES", 60 * 24 * 90)

    _, refresh_token, _ = await auth_service.login(db, FakeAsyncRedis(), user.username, password)
    row = next(iter(fake_repo.sessions.values()))
    row["family_expires_at"] = _now() - timedelta(seconds=1)

    with pytest.raises(HTTPException) as exc:
        await auth_service.refresh_access_token(db, object(), refresh_token)
    assert exc.value.status_code == 401
    assert "Session expired" in str(exc.value.detail)


@pytest.mark.anyio
async def test_concurrent_refresh_within_grace_returns_same_replacement(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requests replaying an already-rotated token converge on the SAME replacement token."""
    user, password = _make_user(db)
    fake_repo = FakeRefreshSessionRepository()
    monkeypatch.setattr(auth_service, "auth_refresh_session_repository", fake_repo)

    _, refresh_token_a, _ = await auth_service.login(db, FakeAsyncRedis(), user.username, password)

    # First refresh — rotates A → B and caches B as A's replacement
    access1, refresh_token_b, max_age_b = await auth_service.refresh_access_token(
        db, object(), refresh_token_a
    )
    assert access1.access_token

    # Replays with the old token A (concurrent tabs / retried request) must return
    # the cached replacement B unchanged, without rotating again.
    access2, refresh_token_c, max_age_c = await auth_service.refresh_access_token(
        db, object(), refresh_token_a
    )
    access3, refresh_token_d, _ = await auth_service.refresh_access_token(
        db, object(), refresh_token_a
    )
    assert access2.access_token
    assert access3.access_token
    assert refresh_token_c == refresh_token_b
    assert refresh_token_d == refresh_token_b
    assert max_age_c > 0
    assert max_age_c <= max_age_b

    # Only login + one rotation happened: exactly two sessions, family intact
    assert len(fake_repo.sessions) == 2
    family_id = next(iter(fake_repo.sessions.values()))["family_id"]
    assert family_id not in fake_repo.family_revoked


@pytest.mark.anyio
async def test_replay_falls_back_to_chain_rotation_when_cache_missing(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a cached replacement, a grace-window replay follows the chain and rotates."""
    user, password = _make_user(db)
    fake_repo = FakeRefreshSessionRepository()
    monkeypatch.setattr(auth_service, "auth_refresh_session_repository", fake_repo)

    _, refresh_token_a, _ = await auth_service.login(db, FakeAsyncRedis(), user.username, password)
    _, refresh_token_b, _ = await auth_service.refresh_access_token(db, object(), refresh_token_a)

    fake_repo.replacement_tokens.clear()

    access, refresh_token_c, _ = await auth_service.refresh_access_token(
        db, object(), refresh_token_a
    )
    assert access.access_token
    assert refresh_token_c != refresh_token_b

    family_id = next(iter(fake_repo.sessions.values()))["family_id"]
    assert family_id not in fake_repo.family_revoked


@pytest.mark.anyio
async def test_reuse_outside_grace_period_revokes_family(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replaying a rotated token with grace period disabled triggers family revocation."""
    user, password = _make_user(db)
    fake_repo = FakeRefreshSessionRepository()
    monkeypatch.setattr(auth_service, "auth_refresh_session_repository", fake_repo)
    monkeypatch.setattr(auth_service.settings, "REFRESH_GRACE_PERIOD_SECONDS", 0)

    _, refresh_token_a, _ = await auth_service.login(db, FakeAsyncRedis(), user.username, password)
    await auth_service.refresh_access_token(db, object(), refresh_token_a)

    with pytest.raises(HTTPException) as exc:
        await auth_service.refresh_access_token(db, object(), refresh_token_a)
    assert exc.value.status_code == 401
    assert "reuse" in exc.value.detail.lower()

    sessions = list(fake_repo.sessions.values())
    family_id = sessions[0]["family_id"]
    assert family_id in fake_repo.family_revoked


@pytest.mark.anyio
async def test_login_blocks_after_too_many_failed_attempts(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, password = _make_user(db)
    fake_repo = FakeRefreshSessionRepository()
    monkeypatch.setattr(auth_service, "auth_refresh_session_repository", fake_repo)
    monkeypatch.setattr(auth_service.settings, "LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 3)
    redis = FakeAsyncRedis()

    for _ in range(3):
        with pytest.raises(HTTPException) as exc:
            await auth_service.login(db, redis, user.username, "wrong-password", client_ip="10.0.0.1")
        assert exc.value.status_code == 400

    # Threshold reached: even the correct password is now rejected with 429.
    with pytest.raises(HTTPException) as exc:
        await auth_service.login(db, redis, user.username, password, client_ip="10.0.0.1")
    assert exc.value.status_code == 429


@pytest.mark.anyio
async def test_login_success_clears_failed_attempt_counter(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, password = _make_user(db)
    fake_repo = FakeRefreshSessionRepository()
    monkeypatch.setattr(auth_service, "auth_refresh_session_repository", fake_repo)
    monkeypatch.setattr(auth_service.settings, "LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 3)
    redis = FakeAsyncRedis()

    with pytest.raises(HTTPException):
        await auth_service.login(db, redis, user.username, "wrong-password", client_ip="10.0.0.2")

    # A successful login resets the counter for this username+IP.
    await auth_service.login(db, redis, user.username, password, client_ip="10.0.0.2")
    assert redis.store.get(auth_service._login_rate_limit_key(user.username, "10.0.0.2")) is None


@pytest.mark.anyio
async def test_login_rate_limit_is_scoped_per_username_and_ip(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, password = _make_user(db)
    fake_repo = FakeRefreshSessionRepository()
    monkeypatch.setattr(auth_service, "auth_refresh_session_repository", fake_repo)
    monkeypatch.setattr(auth_service.settings, "LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 3)
    redis = FakeAsyncRedis()

    for _ in range(3):
        with pytest.raises(HTTPException):
            await auth_service.login(db, redis, user.username, "wrong-password", client_ip="10.0.0.3")

    # A different client IP has an independent counter and can still log in.
    access_token, _, _ = await auth_service.login(
        db, redis, user.username, password, client_ip="10.0.0.4"
    )
    assert access_token.access_token
