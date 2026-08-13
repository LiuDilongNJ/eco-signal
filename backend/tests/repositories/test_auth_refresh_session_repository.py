from datetime import datetime, timedelta, timezone

import pytest

from app.repositories.auth_refresh_session_repository import (
    auth_refresh_session_repository,
)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.expirations: dict[str, int] = {}
        self.sets: dict[str, set[str]] = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value.encode("utf-8") if isinstance(value, str) else value
        if ex is not None:
            self.expirations[key] = ex

    async def get(self, key):
        return self.store.get(key)

    async def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    async def expire(self, key, ex):
        self.expirations[key] = ex

    async def smembers(self, key):
        return self.sets.get(key, set())

    async def ttl(self, key):
        return self.expirations.get(key, -1)

    async def delete(self, key):
        self.store.pop(key, None)

    async def eval(self, _script, _num_keys, revoked_key, activity_key, timeout_seconds):
        if revoked_key in self.store:
            return -1
        if activity_key not in self.store:
            return 0
        await self.set(activity_key, "1", ex=timeout_seconds)
        return 1


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.mark.anyio
async def test_cache_replacement_token_stores_with_grace_ttl() -> None:
    redis = FakeRedis()

    await auth_refresh_session_repository.cache_replacement_token(
        redis, "parent-jti", "raw-refresh-token", grace_seconds=300
    )

    key = "auth:rt_replacement:parent-jti"
    assert redis.store[key] == b"raw-refresh-token"
    assert redis.expirations[key] == 300


@pytest.mark.anyio
async def test_cache_replacement_token_noop_when_grace_disabled() -> None:
    redis = FakeRedis()

    await auth_refresh_session_repository.cache_replacement_token(
        redis, "parent-jti", "raw-refresh-token", grace_seconds=0
    )

    assert redis.store == {}


@pytest.mark.anyio
async def test_get_replacement_token_decodes_bytes() -> None:
    redis = FakeRedis()
    await auth_refresh_session_repository.cache_replacement_token(
        redis, "parent-jti", "raw-refresh-token", grace_seconds=60
    )

    token = await auth_refresh_session_repository.get_replacement_token(redis, "parent-jti")

    assert token == "raw-refresh-token"


@pytest.mark.anyio
async def test_get_replacement_token_returns_none_when_missing() -> None:
    redis = FakeRedis()

    token = await auth_refresh_session_repository.get_replacement_token(redis, "unknown-jti")

    assert token is None


@pytest.mark.anyio
async def test_session_roundtrip_allows_no_family_expiry() -> None:
    redis = FakeRedis()
    expires_at = _now() + timedelta(days=30)

    await auth_refresh_session_repository.create_session(
        redis,
        jti="refresh-jti",
        user_id=123,
        token_hash="hash",
        family_id="family-id",
        parent_jti=None,
        expires_at=expires_at,
        family_expires_at=None,
    )

    session = await auth_refresh_session_repository.get_session_by_jti(redis, "refresh-jti")

    assert session
    assert session["family_expires_at"] is None
    assert session["expires_at"] == expires_at
    assert redis.expirations["auth:rt_family:family-id:tokens"] > 0
    assert redis.expirations["auth:rt_user:123:families"] > 0


@pytest.mark.anyio
async def test_family_activity_initializes_and_slides() -> None:
    redis = FakeRedis()

    await auth_refresh_session_repository.initialize_family_activity(
        redis, "family-id", timeout_seconds=1800
    )
    state = await auth_refresh_session_repository.touch_family_activity(
        redis, "family-id", timeout_seconds=1800
    )

    key = "auth:rt_family:family-id:activity"
    assert state == "active"
    assert redis.expirations[key] == 1800


@pytest.mark.anyio
async def test_family_activity_reports_expired_when_key_is_missing() -> None:
    redis = FakeRedis()

    state = await auth_refresh_session_repository.touch_family_activity(
        redis, "family-id", timeout_seconds=1800
    )

    assert state == "expired"


@pytest.mark.anyio
async def test_family_activity_is_disabled_for_non_positive_timeout() -> None:
    redis = FakeRedis()

    await auth_refresh_session_repository.initialize_family_activity(
        redis, "family-id", timeout_seconds=0
    )
    state = await auth_refresh_session_repository.touch_family_activity(
        redis, "family-id", timeout_seconds=0
    )

    assert redis.store == {}
    assert state == "active"


@pytest.mark.anyio
async def test_revoke_family_removes_activity_key() -> None:
    redis = FakeRedis()
    await auth_refresh_session_repository.initialize_family_activity(
        redis, "family-id", timeout_seconds=1800
    )

    await auth_refresh_session_repository.revoke_family(redis, "family-id")

    assert "auth:rt_family:family-id:activity" not in redis.store
