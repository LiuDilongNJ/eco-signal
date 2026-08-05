import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import sentry_sdk

from app.core.config import settings

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
_SENTRY_MASK_KEYS = {
    "password",
    "new_password",
    "current_password",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "set-cookie",
    "secret",
    "secret_key",
}


def generate_request_id() -> str:
    return f"req_{uuid4().hex}"


def bind_request_id(request_id: str) -> Token[str | None]:
    return _request_id_ctx.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id_ctx.reset(token)


def current_request_id() -> str:
    request_id = _request_id_ctx.get()
    if request_id:
        return request_id
    return generate_request_id()


def build_meta_dict() -> dict[str, str]:
    return {
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "version": settings.APP_VERSION,
        "request_id": current_request_id(),
    }


def _mask_sensitive_data(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _SENTRY_MASK_KEYS:
                sanitized[key] = "***"
            else:
                sanitized[key] = _mask_sensitive_data(item)
        return sanitized
    if isinstance(value, list):
        return [_mask_sensitive_data(item) for item in value]
    return value


def _sentry_before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    del hint  # not used for now, keep signature for sentry callback
    return _mask_sensitive_data(event)


@contextmanager
def sentry_request_scope(request_id: str):
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("request_id", request_id)
        scope.set_extra("request_id", request_id)
        yield


def init_sentry(service_name: str) -> bool:
    if not settings.SENTRY_ENABLED:
        return False
    if not settings.SENTRY_DSN:
        return False
    if settings.ENVIRONMENT == "local" and not settings.SENTRY_ENABLE_IN_LOCAL:
        return False
    if sentry_sdk.Hub.current.client is not None:
        return True
    try:
        sentry_sdk.init(
            dsn=str(settings.SENTRY_DSN),
            environment=settings.ENVIRONMENT,
            release=settings.APP_VERSION,
            enable_tracing=settings.SENTRY_TRACES_SAMPLE_RATE > 0,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            send_default_pii=settings.SENTRY_SEND_DEFAULT_PII,
            enable_logs=settings.SENTRY_ENABLE_LOGS,
            profile_session_sample_rate=settings.SENTRY_PROFILE_SESSION_SAMPLE_RATE,
            profile_lifecycle=settings.SENTRY_PROFILE_LIFECYCLE,
            before_send=_sentry_before_send,
        )
        sentry_sdk.set_tag("service", service_name)
        return True
    except Exception:
        logger.exception("Sentry initialization failed for service=%s", service_name)
        return False
