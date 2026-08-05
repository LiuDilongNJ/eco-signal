"""
Read-only model for expanded user permissions.

`user_effective_permissions` is the canonical access-check view. Stored
permission editing still writes `user_permission` directly.
"""
from typing import Optional

from sqlmodel import Field, SQLModel


class UserEffectivePermission(SQLModel, table=True):
    """
    Expanded permission row for either a project or project-local collection path.

    For project scope, collection_id is NULL and resource_type is project.
    For project_collection scope, collection_id is present and resource_type is
    collection/audio/site/annotation/review.
    """
    __tablename__ = "user_effective_permissions"

    user_id: int = Field(primary_key=True)
    project_id: int = Field(primary_key=True)
    collection_id: Optional[int] = Field(default=None, primary_key=True)
    scope_type: str = Field(primary_key=True, max_length=50)
    resource_type: str = Field(primary_key=True, max_length=50)
    action: str = Field(primary_key=True, max_length=10)
