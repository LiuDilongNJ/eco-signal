import json
from datetime import datetime, timezone
from typing import Any, Literal

from redis.asyncio import Redis

_SESSION_PREFIX = "auth:rt"
_FAMILY_PREFIX = "auth:rt_family"
_USER_PREFIX = "auth:rt_user"
_REPLACEMENT_TOKEN_PREFIX = "auth:rt_replacement"
_REPLACEMENT_CHAIN_MAX_DEPTH = 5

_TOUCH_FAMILY_ACTIVITY_SCRIPT = """
local revoked_key = KEYS[1]
local activity_key = KEYS[2]
local timeout_seconds = tonumber(ARGV[1])

if redis.call('EXISTS', revoked_key) == 1 then
    return -1
end
if redis.call('EXISTS', activity_key) == 0 then
    return 0
end
redis.call('SET', activity_key, '1', 'EX', timeout_seconds)
return 1
"""


def _session_key(jti: str) -> str:
    return f"{_SESSION_PREFIX}:{jti}"


def _replacement_token_key(parent_jti: str) -> str:
    return f"{_REPLACEMENT_TOKEN_PREFIX}:{parent_jti}"


def _family_tokens_key(family_id: str) -> str:
    return f"{_FAMILY_PREFIX}:{family_id}:tokens"


def _family_revoked_key(family_id: str) -> str:
    return f"{_FAMILY_PREFIX}:{family_id}:revoked"


def _user_families_key(user_id: int) -> str:
    return f"{_USER_PREFIX}:{user_id}:families"


def _family_activity_key(family_id: str) -> str:
    return f"{_FAMILY_PREFIX}:{family_id}:activity"


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ttl_seconds(until: datetime) -> int:
    seconds = int((until - _now_utc_naive()).total_seconds())
    return max(seconds, 1)


def _loads_session(value: bytes | str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    data = json.loads(value)
    data["expires_at"] = datetime.fromisoformat(data["expires_at"])
    if data["family_expires_at"] is not None:
        data["family_expires_at"] = datetime.fromisoformat(data["family_expires_at"])
    if data.get("revoked_at"):
        data["revoked_at"] = datetime.fromisoformat(data["revoked_at"])
    return data


def _dumps_session(data: dict[str, Any]) -> str:
    serializable = dict(data)
    serializable["expires_at"] = serializable["expires_at"].isoformat()
    family_expires_at = serializable["family_expires_at"]
    serializable["family_expires_at"] = (
        family_expires_at.isoformat() if isinstance(family_expires_at, datetime) else None
    )
    revoked_at = serializable.get("revoked_at")
    if isinstance(revoked_at, datetime):
        serializable["revoked_at"] = revoked_at.isoformat()
    return json.dumps(serializable)


class AuthRefreshSessionRepository:
    async def initialize_family_activity(
        self, redis: Redis, family_id: str, *, timeout_seconds: int
    ) -> None:
        """Start the sliding inactivity window for a newly authenticated family."""
        if timeout_seconds <= 0:
            return
        await redis.set(
            _family_activity_key(family_id),
            "1",
            ex=timeout_seconds,
        )

    async def touch_family_activity(
        self, redis: Redis, family_id: str, *, timeout_seconds: int
    ) -> Literal["active", "expired", "revoked"]:
        """Atomically validate and extend a session family's inactivity window."""
        if timeout_seconds <= 0:
            return "active"
        result = await redis.eval(
            _TOUCH_FAMILY_ACTIVITY_SCRIPT,
            2,
            _family_revoked_key(family_id),
            _family_activity_key(family_id),
            timeout_seconds,
        )
        return {1: "active", 0: "expired", -1: "revoked"}[int(result)]

    async def create_session(
        self,
        redis: Redis,
        *,
        jti: str,
        user_id: int,
        token_hash: str,
        family_id: str,
        parent_jti: str | None,
        expires_at: datetime,
        family_expires_at: datetime | None,
        created_ip: str | None = None,
        created_user_agent: str | None = None,
    ) -> None:
        session_data = {
            "jti": jti,
            "user_id": user_id,
            "token_hash": token_hash,
            "family_id": family_id,
            "parent_jti": parent_jti,
            "replaced_by_jti": None,
            "expires_at": expires_at,
            "family_expires_at": family_expires_at,
            "revoked_at": None,
            "created_at": _now_utc_naive().isoformat(),
            "created_ip": created_ip,
            "created_user_agent": created_user_agent,
        }
        family_ttl = _ttl_seconds(family_expires_at or expires_at)
        await redis.set(_session_key(jti), _dumps_session(session_data), ex=_ttl_seconds(expires_at))
        await redis.sadd(_family_tokens_key(family_id), jti)
        await redis.expire(_family_tokens_key(family_id), family_ttl)
        await redis.sadd(_user_families_key(user_id), family_id)
        await redis.expire(_user_families_key(user_id), family_ttl)

    async def get_session_by_jti(self, redis: Redis, jti: str) -> dict[str, Any] | None:
        return _loads_session(await redis.get(_session_key(jti)))

    async def revoke_session(
        self,
        redis: Redis,
        jti: str,
        *,
        replaced_by_jti: str | None = None,
    ) -> None:
        key = _session_key(jti)
        session_data = _loads_session(await redis.get(key))
        if not session_data:
            return
        if session_data.get("revoked_at") is None:
            session_data["revoked_at"] = _now_utc_naive()
        if replaced_by_jti:
            session_data["replaced_by_jti"] = replaced_by_jti
        ttl = await redis.ttl(key)
        if ttl is None or ttl < 1:
            ttl = 1
        await redis.set(key, _dumps_session(session_data), ex=ttl)

    async def is_family_revoked(self, redis: Redis, family_id: str) -> bool:
        return bool(await redis.exists(_family_revoked_key(family_id)))

    async def revoke_family(
        self, redis: Redis, family_id: str, *, family_expires_at: datetime | None = None
    ) -> None:
        token_ids = await redis.smembers(_family_tokens_key(family_id))
        if family_expires_at is None:
            expires_at_values: list[datetime] = []
            for token_id in token_ids:
                jti = token_id.decode("utf-8") if isinstance(token_id, bytes) else str(token_id)
                session_data = await self.get_session_by_jti(redis, jti)
                if session_data:
                    expires_at_values.append(session_data["expires_at"])
            family_expires_at = max(expires_at_values, default=_now_utc_naive())
        await redis.set(_family_revoked_key(family_id), "1", ex=_ttl_seconds(family_expires_at))
        for token_id in token_ids:
            jti = token_id.decode("utf-8") if isinstance(token_id, bytes) else str(token_id)
            await self.revoke_session(redis, jti)
        await redis.delete(_family_activity_key(family_id))

    async def revoke_user_sessions(self, redis: Redis, user_id: int) -> None:
        families = await redis.smembers(_user_families_key(user_id))
        for family in families:
            family_id = family.decode("utf-8") if isinstance(family, bytes) else str(family)
            await self.revoke_family(redis, family_id)

    async def cache_replacement_token(
        self,
        redis: Redis,
        parent_jti: str,
        refresh_token: str,
        *,
        grace_seconds: int,
    ) -> None:
        """Cache the raw replacement token for idempotent refresh within the grace window.

        A retried/concurrent request presenting the rotated parent token gets the same
        replacement cookie instead of triggering another rotation.
        """
        if grace_seconds <= 0:
            return
        await redis.set(_replacement_token_key(parent_jti), refresh_token, ex=grace_seconds)

    async def get_replacement_token(self, redis: Redis, parent_jti: str) -> str | None:
        value = await redis.get(_replacement_token_key(parent_jti))
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    async def resolve_replacement_session(
        self,
        redis: Redis,
        session: dict,
        *,
        grace_seconds: int = 60,
    ) -> dict | None:
        """Follow replaced_by_jti chain to find the current valid session.

        Used for concurrent-refresh tolerance: if a token was rotated within the grace
        window, subsequent requests carrying the old token follow the chain instead of
        triggering family revocation. Returns None when grace period is disabled,
        exceeded, the chain is broken, or max depth is reached.
        """
        if grace_seconds <= 0:
            return None

        now = _now_utc_naive()
        current = session
        for _ in range(_REPLACEMENT_CHAIN_MAX_DEPTH):
            revoked_at = current["revoked_at"]
            if revoked_at is None or (now - revoked_at).total_seconds() > grace_seconds:
                return None

            replacement_jti = current.get("replaced_by_jti")
            if not replacement_jti:
                return None

            current = await self.get_session_by_jti(redis, replacement_jti)
            if not current:
                return None

            if current["revoked_at"] is None:
                return current

        return None


auth_refresh_session_repository = AuthRefreshSessionRepository()
