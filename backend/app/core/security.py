import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


ALGORITHM = "HS256"


def create_access_token(subject: str | Any, expires_delta: timedelta) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {"exp": expire, "sub": str(subject), "type": "access"}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(
    subject: str | Any,
    expires_delta: timedelta,
    jti: str,
    family_id: str,
) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "jti": jti,
        "family_id": family_id,
        "type": "refresh",
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def new_token_id() -> str:
    """Generate a collision-resistant token identifier."""
    return uuid4().hex


def token_fingerprint(token: str) -> str:
    """Hash token before persisting it server-side."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token_fingerprint(token: str, expected_hash: str) -> bool:
    """Constant-time comparison for hashed token validation."""
    return hmac.compare_digest(token_fingerprint(token), expected_hash)


def random_csrf_token() -> str:
    """Generate CSRF token for double-submit protection if needed."""
    return secrets.token_urlsafe(32)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against PHP-compatible hash (base64 encoded bcrypt)."""
    try:
        decoded_hash = base64.b64decode(hashed_password).decode("utf-8")
        return pwd_context.verify(plain_password, decoded_hash)
    except Exception:
        try:
            return pwd_context.verify(plain_password, hashed_password)
        except Exception:
            return False


def get_password_hash(password: str) -> str:
    """Hash password using PHP-compatible format (bcrypt + base64 encoding)."""
    bcrypt_hash = pwd_context.hash(password)
    encoded = base64.b64encode(bcrypt_hash.encode("utf-8")).decode("utf-8")
    return encoded
