"""
Global operation log middleware.
"""
import json
import logging
from functools import lru_cache
from typing import Any, Optional
from urllib.parse import parse_qsl

import jwt
from fastapi import Request
from sqlalchemy.engine import Engine
from sqlmodel import Session
from sqlmodel import create_engine
from starlette.background import BackgroundTask

from app.core.config import settings
from app.core.request import get_client_ip
from app.core.security import ALGORITHM
from app.services.operation_log_service import operation_log_service

logger = logging.getLogger(__name__)

_MAX_LOG_BODY_BYTES = 64 * 1024
_SENSITIVE_KEYS = {
    "password",
    "new_password",
    "current_password",
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "secret_key",
    "authorization",
}

# Paths whose first segment maps to a custom action instead of the HTTP method default
_PATH_ACTION_OVERRIDES = {
    "login": "login",
    "refresh": "login",
}

# Map HTTP method to action name
_ACTION_MAP = {
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}


@lru_cache(maxsize=8)
def _get_operation_log_engine(database_uri: str) -> Engine:
    """Build a cached engine bound to the current database URI."""
    return create_engine(
        database_uri,
        pool_size=settings.OPERATION_LOG_DB_POOL_SIZE,
        max_overflow=settings.OPERATION_LOG_DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
    )


def _extract_user_id(request: Request) -> Optional[int]:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        return int(sub) if sub else None
    except Exception:
        return None


def _parse_resource_info(path: str) -> tuple[str, Optional[str]]:
    """Parse resource type and ID from API path.

    /api/v1/projects/123  -> ("projects", "123")
    /api/v1/users         -> ("users", None)
    """
    prefix = settings.API_V1_STR
    if path.startswith(prefix):
        path = path[len(prefix):]

    parts = [p for p in path.split("/") if p]
    if not parts:
        return "system", None

    resource_type = parts[0]
    resource_id = parts[1] if len(parts) > 1 else None
    if resource_id and "?" in resource_id:
        resource_id = resource_id.split("?")[0]

    return resource_type, resource_id


def _resolve_action(method: str, resource_type: str, resource_id: str | None) -> str:
    if resource_type == "auth-token-refreshes" and method == "POST":
        return "refresh"
    if resource_type == "auth-tokens" and method == "POST" and resource_id is None:
        return "login"
    if resource_type == "auth-tokens" and method == "DELETE" and resource_id == "current":
        return "logout"
    return _PATH_ACTION_OVERRIDES.get(resource_type) or _ACTION_MAP[method]


def _restore_request_body(request: Request, body: bytes) -> None:
    consumed = False

    async def receive() -> dict[str, Any]:
        nonlocal consumed
        if consumed:
            return {"type": "http.request", "body": b"", "more_body": False}
        consumed = True
        return {"type": "http.request", "body": body, "more_body": False}

    request._receive = receive


def _mask_sensitive_payload(data: Any) -> Any:
    if isinstance(data, dict):
        masked: dict[str, Any] = {}
        for key, value in data.items():
            if str(key).lower() in _SENSITIVE_KEYS:
                masked[key] = "***"
            else:
                masked[key] = _mask_sensitive_payload(value)
        return masked
    if isinstance(data, list):
        return [_mask_sensitive_payload(item) for item in data]
    return data


def _parse_form_payload(body_text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in parse_qsl(body_text, keep_blank_values=True):
        if key in payload:
            existing = payload[key]
            if isinstance(existing, list):
                existing.append(value)
            else:
                payload[key] = [existing, value]
        else:
            payload[key] = value
    return payload


async def _extract_payload(request: Request) -> Any:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type.startswith("multipart/form-data"):
        return {"_content_type": content_type, "_omitted": "multipart payload not logged"}

    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > _MAX_LOG_BODY_BYTES:
        return {
            "_content_type": content_type or "unknown",
            "_omitted": f"payload too large ({content_length} bytes)",
        }

    body = await request.body()
    _restore_request_body(request, body)

    if not body:
        return None

    if len(body) > _MAX_LOG_BODY_BYTES:
        return {
            "_content_type": content_type or "unknown",
            "_omitted": f"payload too large ({len(body)} bytes)",
        }

    if content_type in {"application/json", "text/json"}:
        try:
            return _mask_sensitive_payload(json.loads(body))
        except json.JSONDecodeError:
            return {"_content_type": content_type, "_raw": body.decode("utf-8", errors="replace")}

    if content_type == "application/x-www-form-urlencoded":
        return _mask_sensitive_payload(
            _parse_form_payload(body.decode("utf-8", errors="replace"))
        )

    try:
        return {"_content_type": content_type or "text/plain", "_raw": body.decode("utf-8")}
    except UnicodeDecodeError:
        return {"_content_type": content_type or "application/octet-stream", "_omitted": "binary payload not logged"}


def _save_operation_log(
    user_id: Optional[int],
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    req_ip: str,
    req_endpoint: str,
    payload: Any,
    status_code: int,
) -> None:
    try:
        database_uri = str(settings.sqlalchemy_database_uri)
        with Session(_get_operation_log_engine(database_uri)) as session:
            operation_log_service.log_operation(
                session,
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                description=f"{action.capitalize()} {resource_type}",
                req_ip=req_ip,
                req_endpoint=req_endpoint,
                payload=payload,
                status_code=status_code,
            )
    except Exception as e:
        logger.error(f"Failed to save operation log: {e}")


async def operation_log_middleware(request: Request, call_next):
    if request.method not in _ACTION_MAP:
        return await call_next(request)

    payload = await _extract_payload(request)
    response = await call_next(request)

    if 200 <= response.status_code < 400:
        resource_type, resource_id = _parse_resource_info(request.url.path)

        action = _resolve_action(request.method, resource_type, resource_id)
        user_id = _extract_user_id(request)
        req_ip = get_client_ip(request) or ""
        req_endpoint = f"{request.method} {request.url.path}"

        task = BackgroundTask(
            _save_operation_log,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            req_ip=req_ip,
            req_endpoint=req_endpoint,
            payload=payload,
            status_code=response.status_code,
        )

        if not (hasattr(response, "background") and response.background is not None):
            response.background = task

    return response
