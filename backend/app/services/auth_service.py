import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock

import jwt
from fastapi import HTTPException, status
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlmodel import Session

from app.core import security
from app.core.config import settings
from app.core.security import get_password_hash
from app.models import User
from app.repositories import auth_refresh_session_repository, user_repository
from app.schemas import RefreshTokenPayload, Token
from app.schemas.response import ApiResponse
from app.utils import verify_password_reset_token

logger = logging.getLogger(__name__)
AUTH_REASON_HEADER = "X-Auth-Reason"

_refresh_rate_lock = Lock()
_refresh_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


def _log_refresh_rejected(
    reason: str,
    *,
    sub: str | None = None,
    jti: str | None = None,
    family_id: str | None = None,
    client_ip: str | None = None,
) -> None:
    """Structured log for refresh 401s so production incidents can be diagnosed."""
    logger.warning(
        "refresh_token_rejected reason=%s sub=%s jti=%s family_id=%s client_ip=%s",
        reason,
        sub,
        jti,
        family_id,
        client_ip,
    )


def _access_token_ttl() -> timedelta:
    return timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)


def _refresh_token_ttl() -> timedelta:
    return timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)


def _session_absolute_ttl() -> timedelta | None:
    minutes = settings.AUTH_SESSION_ABSOLUTE_EXPIRE_MINUTES
    if minutes <= 0:
        return None
    return timedelta(minutes=minutes)


def _enforce_refresh_rate_limit(user_id: str, client_ip: str | None) -> None:
    now_ts = datetime.now(timezone.utc).timestamp()
    key = f"{user_id}:{client_ip or 'unknown'}"
    with _refresh_rate_lock:
        bucket = _refresh_rate_buckets[key]
        while bucket and now_ts - bucket[0] > settings.REFRESH_RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= settings.REFRESH_RATE_LIMIT_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many refresh attempts. Please retry later.",
            )
        bucket.append(now_ts)


def _login_rate_limit_key(username: str, client_ip: str | None) -> str:
    return f"login_fail:{username}:{client_ip or 'unknown'}"


async def _enforce_login_rate_limit(
    redis: Redis, username: str, client_ip: str | None
) -> None:
    """Reject login when failed attempts for this username+IP exceed the window limit."""
    raw = await redis.get(_login_rate_limit_key(username, client_ip))
    if raw is None:
        return
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode()
    if int(raw) >= settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please retry later.",
        )


async def _register_failed_login(
    redis: Redis, username: str, client_ip: str | None
) -> None:
    """Count a failed attempt and arm the expiry window on the first failure."""
    key = _login_rate_limit_key(username, client_ip)
    attempts = await redis.incr(key)
    if attempts == 1:
        await redis.expire(key, settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS)


async def _clear_login_rate_limit(
    redis: Redis, username: str, client_ip: str | None
) -> None:
    await redis.delete(_login_rate_limit_key(username, client_ip))


def _build_access_token(user_id: int, family_id: str) -> Token:
    return Token(
        access_token=security.create_access_token(
            user_id,
            expires_delta=_access_token_ttl(),
            family_id=family_id,
        ),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        session_idle_timeout_seconds=settings.auth_session_idle_timeout_seconds,
    )


async def _revoke_family_and_raise(
    redis: Redis,
    family_id: str,
    family_expires_at: datetime | None,
    detail: str,
    *,
    reason: str | None = None,
) -> None:
    """Revoke an entire token family then raise HTTP 401."""
    await auth_refresh_session_repository.revoke_family(
        redis, family_id, family_expires_at=family_expires_at
    )
    headers = {"WWW-Authenticate": "Bearer"}
    if reason:
        headers[AUTH_REASON_HEADER] = reason
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers=headers,
    )


async def validate_session_activity(
    redis: Redis,
    family_id: str | None,
    *,
    user_id: str | None = None,
) -> None:
    """Validate and extend the current session family's sliding inactivity window."""
    timeout_seconds = settings.auth_session_idle_timeout_seconds
    if timeout_seconds <= 0:
        return
    if not family_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        activity_state = await auth_refresh_session_repository.touch_family_activity(
            redis,
            family_id,
            timeout_seconds=timeout_seconds,
        )
        if activity_state == "active":
            return
        if activity_state == "revoked":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session is no longer active. Please login again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        logger.warning(
            "auth_session_rejected reason=idle_timeout user_id=%s family_id=%s",
            user_id,
            family_id,
        )
        await auth_refresh_session_repository.revoke_family(redis, family_id)
    except HTTPException:
        raise
    except RedisError as exc:
        logger.exception("auth_session_validation_failed family_id=%s", family_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable.",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session expired due to inactivity. Please login again.",
        headers={
            "WWW-Authenticate": "Bearer",
            AUTH_REASON_HEADER: "idle_timeout",
        },
    )


async def initialize_session_activity(redis: Redis, family_id: str) -> None:
    """Create the inactivity window for a new session family when enabled."""
    timeout_seconds = settings.auth_session_idle_timeout_seconds
    if timeout_seconds <= 0:
        return
    try:
        await auth_refresh_session_repository.initialize_family_activity(
            redis,
            family_id,
            timeout_seconds=timeout_seconds,
        )
    except RedisError as exc:
        logger.exception("auth_session_initialization_failed family_id=%s", family_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable.",
        ) from exc


async def _issue_refresh_token(
    redis: Redis,
    *,
    user_id: int,
    family_id: str,
    family_expires_at: datetime | None,
    parent_jti: str | None,
    client_ip: str | None,
    user_agent: str | None,
) -> tuple[str, str, int]:
    """Return (refresh_token, jti, max_age_seconds)."""
    jti = security.new_token_id()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expires_at = now + _refresh_token_ttl()
    if family_expires_at is not None:
        expires_at = min(expires_at, family_expires_at)
    if expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please login again.",
        )
    refresh_token = security.create_refresh_token(
        subject=user_id,
        expires_delta=expires_at - now,
        jti=jti,
        family_id=family_id,
    )
    await auth_refresh_session_repository.create_session(
        redis,
        jti=jti,
        user_id=user_id,
        token_hash=security.token_fingerprint(refresh_token),
        family_id=family_id,
        family_expires_at=family_expires_at,
        parent_jti=parent_jti,
        expires_at=expires_at,
        created_ip=client_ip,
        created_user_agent=user_agent,
    )
    return refresh_token, jti, int((expires_at - now).total_seconds())


def _decode_refresh_token(refresh_token: str, verify_exp: bool = True) -> RefreshTokenPayload:
    payload = jwt.decode(
        refresh_token,
        settings.SECRET_KEY,
        algorithms=[security.ALGORITHM],
        options={"verify_exp": verify_exp},
    )
    token_payload = RefreshTokenPayload(**payload)
    if token_payload.type != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    return token_payload


async def login(
    session: Session,
    redis: Redis,
    username: str,
    password: str,
    *,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[Token, str, int]:
    """Return (access_token, refresh_token, refresh_max_age_seconds)."""
    await _enforce_login_rate_limit(redis, username, client_ip)
    user = user_repository.authenticate_by_username(session=session, username=username, password=password)
    if not user:
        await _register_failed_login(redis, username, client_ip)
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    if not user.active:
        raise HTTPException(status_code=400, detail="Inactive user")

    await _clear_login_rate_limit(redis, username, client_ip)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    absolute_ttl = _session_absolute_ttl()
    family_id = security.new_token_id()
    refresh_token, _, refresh_max_age = await _issue_refresh_token(
        redis,
        user_id=user.user_id,
        family_id=family_id,
        family_expires_at=now + absolute_ttl if absolute_ttl is not None else None,
        parent_jti=None,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    await initialize_session_activity(redis, family_id)
    return _build_access_token(user.user_id, family_id), refresh_token, refresh_max_age


async def refresh_access_token(
    session: Session,
    redis: Redis,
    refresh_token: str,
    *,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[Token, str, int]:
    """Rotate refresh token and issue a new access token. Returns (access_token, refresh_token, refresh_max_age_seconds)."""
    try:
        token_payload = _decode_refresh_token(refresh_token)
    except ExpiredSignatureError:
        try:
            expired_payload = _decode_refresh_token(refresh_token, verify_exp=False)
            existing = await auth_refresh_session_repository.get_session_by_jti(redis, expired_payload.jti)
            if existing:
                await auth_refresh_session_repository.revoke_session(redis, expired_payload.jti)
        except Exception:
            pass
        _log_refresh_rejected("token_signature_expired", client_ip=client_ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")
    except (InvalidTokenError, ValidationError, ValueError):
        _log_refresh_rejected("token_decode_failed", client_ip=client_ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    _enforce_refresh_rate_limit(token_payload.sub, client_ip)

    # presented_session is used for fingerprint check regardless of grace-period chain following
    presented_session = await auth_refresh_session_repository.get_session_by_jti(redis, token_payload.jti)
    if not presented_session:
        _log_refresh_rejected(
            "session_not_found",
            sub=token_payload.sub,
            jti=token_payload.jti,
            family_id=token_payload.family_id,
            client_ip=client_ip,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    absolute_expiry_enabled = _session_absolute_ttl() is not None
    family_id = presented_session["family_id"]
    family_expires_at = presented_session["family_expires_at"] if absolute_expiry_enabled else None

    if await auth_refresh_session_repository.is_family_revoked(redis, family_id):
        _log_refresh_rejected(
            "family_already_revoked",
            sub=token_payload.sub,
            jti=token_payload.jti,
            family_id=family_id,
            client_ip=client_ip,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token reuse detected")

    await validate_session_activity(redis, family_id, user_id=token_payload.sub)

    # Resolve the active session: if the presented token was recently rotated (concurrent
    # refresh or a retry after a lost response), follow the replacement chain rather than
    # treating it as a replay attack.
    active_session = presented_session
    replayed_within_grace = presented_session["revoked_at"] is not None
    if replayed_within_grace:
        active_session = await auth_refresh_session_repository.resolve_replacement_session(
            redis, presented_session, grace_seconds=settings.REFRESH_GRACE_PERIOD_SECONDS
        )
        if active_session is None:
            _log_refresh_rejected(
                "reuse_outside_grace_period",
                sub=token_payload.sub,
                jti=token_payload.jti,
                family_id=family_id,
                client_ip=client_ip,
            )
            await _revoke_family_and_raise(redis, family_id, family_expires_at, "Refresh token reuse detected")
        family_id = active_session["family_id"]
        family_expires_at = active_session["family_expires_at"] if absolute_expiry_enabled else None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if family_expires_at is not None and family_expires_at <= now:
        _log_refresh_rejected(
            "session_absolute_expired",
            sub=token_payload.sub,
            jti=token_payload.jti,
            family_id=family_id,
            client_ip=client_ip,
        )
        await _revoke_family_and_raise(redis, family_id, family_expires_at, "Session expired. Please login again.")

    if active_session["expires_at"] <= now:
        await auth_refresh_session_repository.revoke_session(redis, active_session["jti"])
        _log_refresh_rejected(
            "refresh_token_expired",
            sub=token_payload.sub,
            jti=token_payload.jti,
            family_id=family_id,
            client_ip=client_ip,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    if family_id != token_payload.family_id or str(active_session["user_id"]) != token_payload.sub:
        _log_refresh_rejected(
            "payload_session_mismatch",
            sub=token_payload.sub,
            jti=token_payload.jti,
            family_id=family_id,
            client_ip=client_ip,
        )
        await _revoke_family_and_raise(redis, family_id, family_expires_at, "Invalid refresh token")

    # Fingerprint is checked against the PRESENTED token's session hash (not the replacement)
    if not security.verify_token_fingerprint(refresh_token, presented_session["token_hash"]):
        _log_refresh_rejected(
            "token_fingerprint_mismatch",
            sub=token_payload.sub,
            jti=token_payload.jti,
            family_id=family_id,
            client_ip=client_ip,
        )
        await _revoke_family_and_raise(redis, family_id, family_expires_at, "Refresh token reuse detected")

    user: User | None = session.get(User, active_session["user_id"])
    if not user or not user.active:
        _log_refresh_rejected(
            "user_inactive",
            sub=token_payload.sub,
            jti=token_payload.jti,
            family_id=family_id,
            client_ip=client_ip,
        )
        await _revoke_family_and_raise(redis, family_id, family_expires_at, "Inactive user")

    # Idempotent replay: a rotated token presented within the grace window gets the SAME
    # replacement cookie that was issued for it, instead of rotating again. This keeps
    # concurrent tabs / retried requests converging on one token and avoids Set-Cookie races.
    if replayed_within_grace and active_session.get("parent_jti"):
        cached_token = await auth_refresh_session_repository.get_replacement_token(
            redis, active_session["parent_jti"]
        )
        if cached_token and security.verify_token_fingerprint(cached_token, active_session["token_hash"]):
            max_age = int((active_session["expires_at"] - now).total_seconds())
            if max_age > 0:
                return _build_access_token(user.user_id, family_id), cached_token, max_age

    new_refresh_token, replacement_jti, refresh_max_age = await _issue_refresh_token(
        redis,
        user_id=user.user_id,
        family_id=family_id,
        family_expires_at=family_expires_at,
        parent_jti=active_session["jti"],
        client_ip=client_ip,
        user_agent=user_agent,
    )
    await auth_refresh_session_repository.cache_replacement_token(
        redis,
        active_session["jti"],
        new_refresh_token,
        grace_seconds=settings.REFRESH_GRACE_PERIOD_SECONDS,
    )
    await auth_refresh_session_repository.revoke_session(
        redis, active_session["jti"], replaced_by_jti=replacement_jti
    )
    return _build_access_token(user.user_id, family_id), new_refresh_token, refresh_max_age


async def logout(
    redis: Redis,
    refresh_token: str | None,
    *,
    revoke_family: bool = True,
) -> ApiResponse:
    """Revoke refresh token (or family) and return logout response."""
    if not refresh_token:
        return ApiResponse(message="logged out")
    try:
        token_payload = _decode_refresh_token(refresh_token, verify_exp=False)
    except Exception:
        return ApiResponse(message="logged out")

    token_session = await auth_refresh_session_repository.get_session_by_jti(redis, token_payload.jti)
    if token_session:
        if revoke_family:
            await auth_refresh_session_repository.revoke_family(
                redis, token_session["family_id"], family_expires_at=token_session["family_expires_at"]
            )
        else:
            await auth_refresh_session_repository.revoke_session(redis, token_payload.jti)

    return ApiResponse(message="logged out")


async def reset_password(
    session: Session, redis: Redis, token: str, new_password: str
) -> ApiResponse:
    """Reset user password using reset token."""
    email = verify_password_reset_token(token=token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid token")

    user = user_repository.get_by_email(session=session, email=email)
    if not user:
        raise HTTPException(status_code=404, detail="The user with this email does not exist in the system.")
    if not user.active:
        raise HTTPException(status_code=400, detail="Inactive user")

    user.password = get_password_hash(password=new_password)
    await auth_refresh_session_repository.revoke_user_sessions(redis, user.user_id)
    session.add(user)
    session.commit()
    return ApiResponse(message="Password updated successfully")
