"""
Application configuration settings.
"""
import secrets
import warnings
from typing import Annotated, Any, Literal

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    # Default pagination limit
    DEFAULT_PAGE_LIMIT: int = 15

    # File upload size limits (bytes)
    MAX_IMAGE_SIZE: int = 10 * 1024 * 1024       # 10 MB
    MAX_CHUNK_SIZE: int = 8 * 1024 * 1024         # 8 MB
    SECRET_KEY: str = secrets.token_urlsafe(32)
    # 7 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    # 60 minutes * 24 hours * 30 days = 30 days
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30
    # <= 0 disables absolute session expiry; refresh tokens still expire and rotate.
    AUTH_SESSION_ABSOLUTE_EXPIRE_MINUTES: int = 0
    # Sliding inactivity timeout for authenticated sessions. It is disabled in local development.
    AUTH_SESSION_IDLE_EXPIRE_MINUTES: int = 30
    AUTH_REFRESH_COOKIE_NAME: str = "refresh_token"
    AUTH_REFRESH_COOKIE_PATH: str = "/api/v1"
    AUTH_REFRESH_COOKIE_SECURE: bool = False
    AUTH_REFRESH_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    REFRESH_RATE_LIMIT_WINDOW_SECONDS: int = 60
    REFRESH_RATE_LIMIT_MAX_ATTEMPTS: int = 20
    # Login brute-force protection: max failed attempts per username+IP within the window.
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS: int = 10
    # Grace window for concurrent refresh: within this many seconds, a rotated token
    # is allowed to reuse the cached replacement (idempotent refresh) or follow the
    # replacement chain instead of triggering family revocation.
    # Set to 0 to disable (strict reuse detection).
    REFRESH_GRACE_PERIOD_SECONDS: int = 300
    DOMAIN: str = "localhost"
    FRONTEND_PORT: int = 80
    ENABLE_HTTPS: bool = False
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    APP_VERSION: str = "1.0"
    MEDIA_ROOT: str = "/app/sounds"
    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.public_origin.rstrip("/")
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def public_origin(self) -> str:
        scheme = "https" if self.ENABLE_HTTPS else "http"
        default_port = 443 if self.ENABLE_HTTPS else 80
        if self.FRONTEND_PORT == default_port:
            return f"{scheme}://{self.DOMAIN}"
        return f"{scheme}://{self.DOMAIN}:{self.FRONTEND_PORT}"

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None
    SENTRY_ENABLED: bool = True
    SENTRY_ENABLE_IN_LOCAL: bool = False
    SENTRY_ENABLE_LOGS: bool = False
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0
    SENTRY_PROFILE_SESSION_SAMPLE_RATE: float = 0.0
    SENTRY_PROFILE_LIFECYCLE: str = "trace"
    SENTRY_SEND_DEFAULT_PII: bool = False
    METRICS_ENABLED: bool = True
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    # Redis 配置
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""

    # RabbitMQ worker configuration
    RABBITMQ_HOST: str = "localhost"
    RABBITMQ_PORT: int = 5673
    RABBITMQ_USER: str = "ecosignal"
    RABBITMQ_PASSWORD: str = "ecosignal"
    RABBITMQ_VHOST: str = "/"
    WORKER_PREFETCH_COUNT: int = 1
    WORKER_RETRY_MAX_TRIES: int = 5
    WORKER_JOB_TIMEOUT: int = 3600
    WORKER_QUEUE: str = "all"
    DB_POOL_SIZE: int = 4
    DB_MAX_OVERFLOW: int = 2
    DB_POOL_TIMEOUT: int = 10
    DB_POOL_RECYCLE: int = 1800
    OPERATION_LOG_DB_POOL_SIZE: int = 2
    OPERATION_LOG_DB_MAX_OVERFLOW: int = 1
    GUNICORN_MAX_REQUESTS: int = 1000
    GUNICORN_MAX_REQUESTS_JITTER: int = 100

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_database_uri(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:  # noqa: N802
        """Database URI entrypoint required by the migration runtime."""
        return self.sqlalchemy_database_uri

    # Password reset token expiry
    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    # Test user for development
    EMAIL_TEST_USER: EmailStr = "test@example.com"
    
    # First superuser credentials
    FIRST_SUPERUSER: str
    FIRST_SUPERUSER_PASSWORD: str

    ADMIN_ROLE_NAME: str = "Administrator"

    @property
    def auth_session_idle_timeout_seconds(self) -> int:
        """Return the effective sliding inactivity timeout for this environment."""
        if self.ENVIRONMENT == "local" or self.AUTH_SESSION_IDLE_EXPIRE_MINUTES <= 0:
            return 0
        return self.AUTH_SESSION_IDLE_EXPIRE_MINUTES * 60

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


settings = Settings()  # type: ignore
