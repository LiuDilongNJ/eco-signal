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
from app.services import permission_service
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


def get_current_user(session: SessionDep, token: TokenDep) -> User:
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



def get_current_user_optional(session: SessionDep, token: TokenDepOptional) -> User | None:
    """Get current user if authenticated, else None."""
    if not token:
        return None
    try:
        return get_current_user(session, token)
    except HTTPException:
        return None


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


# Supported scopes: map scope name to the kwarg passed to has_resource_permission()
# "collection" → collection_id=resource_id
# "project"    → project_id=resource_id
SUPPORTED_SCOPES = {"collection", "project"}



class PermissionChecker:
    """
    Universal permission checker dependency class.

    Calls permission_service.has_resource_permission() (7-step flow) so that
    the full hierarchy is respected:
      - Admin shortcut
      - Public resource access
      - Direct collection/project permission
      - project:write → collection:write inheritance
      - collection:write → sub-resource read/write inheritance
      - write → read implication

    Args:
        resource_type: Resource type for permission check (project, collection, audio, etc.)
        action: Action type (read or write)
        scope: "collection" or "project" — determines which ID kwarg is passed
               to has_resource_permission()
        path_param: Name of the path parameter containing the resource ID

    Usage:
        # Collection-scoped resource (audio, annotation, etc.)
        @router.get("/collections/{collection_id}/audio")
        def list_media(user: User = Depends(PermissionChecker("audio", "read"))):
            ...

        # Project-scoped resource
        @router.patch("/projects/{project_id}")
        def update_project(
            user: User = Depends(PermissionChecker("project", "write", scope="project", path_param="project_id"))
        ):
            ...
    """

    def __init__(
        self,
        resource_type: str,
        action: str,
        scope: str = "collection",
        path_param: str = "collection_id",
        project_param: str = "project_id",
    ):
        self.resource_type = resource_type
        self.action = action
        self.scope = scope
        self.path_param = path_param
        self.project_param = project_param

        if scope not in SUPPORTED_SCOPES:
            raise ValueError(f"Unknown scope: {scope!r}. Supported: {sorted(SUPPORTED_SCOPES)}")

    def __call__(
        self,
        request: Request,
        session: SessionDep,
        current_user: CurrentUser,
    ) -> User:
        """
        Check user permission via the full 7-step has_resource_permission() flow.

        Returns:
            Current user if permission granted

        Raises:
            HTTPException: 403 if permission denied
        """
        # Get resource ID from path or query parameters
        resource_id = request.path_params.get(self.path_param) or request.query_params.get(self.path_param)
        if resource_id is None:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required parameter: {self.path_param} (path or query)"
            )


        try:
            resource_id = int(resource_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid resource ID")

        # Build keyword args based on scope (determines how resource_id is interpreted)
        scope_kwargs: dict = {}
        if self.scope == "collection":
            project_id = request.path_params.get(self.project_param) or request.query_params.get(self.project_param)
            if project_id is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required parameter: {self.project_param} (path or query)"
                )
            try:
                project_id = int(project_id)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="Invalid project ID")

            scope_kwargs["project_id"] = project_id
            scope_kwargs["collection_id"] = resource_id
        elif self.scope == "project":
            scope_kwargs["project_id"] = resource_id

        # Full 7-step permission check (admin shortcut is inside has_resource_permission)
        if permission_service.has_resource_permission(
            session, current_user, self.resource_type, self.action,
            **scope_kwargs
        ):
            return current_user

        raise HTTPException(
            status_code=403,
            detail=f"Permission required: {self.resource_type}:{self.action}"
        )



# Collection-level permissions (direct)
CanReadCollection = Depends(PermissionChecker("collection", "read"))
CanWriteCollection = Depends(PermissionChecker("collection", "write"))

# Project-level permissions (via associated collections)
CanWriteProject = Depends(PermissionChecker("project", "write", scope="project", path_param="project_id"))

# Global manager: admin OR holds write on at least one project/collection
ActiveManager = Annotated[User, Depends(get_current_active_manager)]
ActiveAdmin = Annotated[User, Depends(get_current_active_superuser)]
