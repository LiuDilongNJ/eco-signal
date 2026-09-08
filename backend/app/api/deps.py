from collections.abc import AsyncGenerator, Generator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlmodel import Session

from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.models import User
from app.repositories import permission_repository
from app.schemas import TokenPayload
from app.services import authorization_service, permission_service
from app.services.auth_service import validate_session_activity
from app.services.authorization_policy import AuthorizationAction
from app.workers.publisher import TaskPublisher

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth-tokens"
)

reusable_oauth2_optional = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth-tokens",
    auto_error=False
)


def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


async def get_redis_client() -> AsyncGenerator[Redis, None]:
    """Get Redis client for refresh sessions and transient import state."""
    redis = Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD or None,
        decode_responses=False,
    )
    try:
        yield redis
    finally:
        await redis.aclose()


async def get_task_publisher() -> AsyncGenerator[TaskPublisher, None]:
    publisher = TaskPublisher()
    try:
        yield publisher
    finally:
        await publisher.close()


SessionDep = Annotated[Session, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis_client)]
TaskPublisherDep = Annotated[TaskPublisher, Depends(get_task_publisher)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]
TokenDepOptional = Annotated[str | None, Depends(reusable_oauth2_optional)]


async def get_current_user(
    session: SessionDep,
    redis: RedisDep,
    token: TokenDep,
) -> User:
    """Get current authenticated user."""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
        if token_data.type and token_data.type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except (InvalidTokenError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await validate_session_activity(redis, token_data.family_id, user_id=token_data.sub)
    user = session.get(User, token_data.sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user



async def get_current_user_optional(
    session: SessionDep,
    redis: RedisDep,
    token: TokenDepOptional,
) -> User | None:
    """Get current user if authenticated, else None."""
    if not token:
        return None
    return await get_current_user(session, redis, token)


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    """Check if current user is an administrator."""
    if not permission_service.is_admin(current_user):
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


def get_current_active_manager(
    session: SessionDep,
    current_user: CurrentUser,
) -> User:
    """
    Check if current user is an admin OR has write permission on at least
    one project or collection (i.e. acts as a project/collection manager).

    Use this dependency for endpoints that should be accessible to
    project/collection managers, not just system admins.
    """
    if permission_service.is_admin(current_user):
        return current_user

    # Check project-level write permission
    project_ids = permission_repository.get_project_ids_with_write_permission(
        session, current_user.user_id
    )
    if project_ids:
        return current_user

    # Check collection-level write permission
    collection_ids = permission_repository.get_accessible_collection_ids(
        session, current_user.user_id, "collection", "write"
    )
    if collection_ids:
        return current_user

    raise HTTPException(
        status_code=403,
        detail="Permission required: write access on at least one project or collection",
    )


class ProjectAuthorization:
    """Require one project-scoped business action at the route boundary."""

    def __init__(self, action: AuthorizationAction):
        self.action = action

    def __call__(
        self,
        request: Request,
        session: SessionDep,
        current_user: CurrentUser,
    ) -> User:
        raw_project_id = request.path_params.get("project_id") or request.query_params.get("project_id")
        if raw_project_id is None:
            raise HTTPException(status_code=400, detail="Missing required parameter: project_id (path or query)")
        try:
            project_id = int(raw_project_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid project ID") from exc
        authorization_service.evaluator(session, current_user, project_id).require(self.action)
        return current_user


CanWriteProject = Depends(
    ProjectAuthorization(AuthorizationAction.PROJECT_EDIT)
)

ActiveManager = Annotated[User, Depends(get_current_active_manager)]
ActiveAdmin = Annotated[User, Depends(get_current_active_superuser)]
