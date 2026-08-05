"""
Utility functions for the application.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

import jwt
from jwt.exceptions import InvalidTokenError

from app.core import security
from app.core.config import settings


def generate_password_reset_token(email: str) -> str:
    """Generate a password reset token for the given email."""
    delta = timedelta(hours=settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS)
    now = datetime.now(timezone.utc)
    expires = now + delta
    exp = expires.timestamp()
    encoded_jwt = jwt.encode(
        {"exp": exp, "nbf": now, "sub": email},
        settings.SECRET_KEY,
        algorithm=security.ALGORITHM,
    )
    return encoded_jwt


def verify_password_reset_token(token: str) -> str | None:
    """Verify a password reset token and return the email if valid."""
    try:
        decoded_token = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        return str(decoded_token["sub"])
    except InvalidTokenError:
        return None


def parse_uuid(value: str | None) -> UUID | None:
    """Try to parse a string as UUID; return None if invalid or empty."""
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, AttributeError):
        return None


def parse_range(value: str | None) -> tuple[float | None, float | None]:
    """Parse a 'min,max' string into a (lo, hi) float tuple.

    Returns (None, None) if the input is empty, lacks a comma, or cannot be parsed.
    Either bound may be None when only one side is provided (e.g. ',5' or '2,').
    """
    if not value or "," not in value:
        return None, None
    parts = value.split(",", 1)
    try:
        lo = float(parts[0]) if parts[0].strip() else None
        hi = float(parts[1]) if parts[1].strip() else None
        return lo, hi
    except ValueError:
        return None, None


def validate_optional_http_url(value: str | None) -> str | None:
    """Normalize an optional absolute HTTP(S) URL or raise ValueError."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("URL must be a string")

    normalized = value.strip()
    if not normalized:
        return None
    if any(char.isspace() or ord(char) < 32 for char in normalized):
        raise ValueError("URL must not contain whitespace or control characters")

    try:
        parsed = urlsplit(normalized)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL must have a valid host and port") from exc

    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL must use http:// or https://")
    if not host:
        raise ValueError("URL must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL must not include credentials")
    if port is not None and not 0 < port <= 65535:
        raise ValueError("URL must have a valid port")
    return normalized


def validate_required_http_url(value: str | None) -> str:
    """Normalize a required absolute HTTP(S) URL or raise ValueError."""
    normalized = validate_optional_http_url(value)
    if normalized is None:
        raise ValueError("URL is required")
    return normalized
