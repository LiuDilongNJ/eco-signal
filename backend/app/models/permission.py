"""
Permission database models.

This module contains Permission and UserPermission models.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.collection import Collection
    from app.models.project import Project


class Permission(SQLModel, table=True):
    """
    Resource-based permission definition.

    Each permission is uniquely identified by resource_type + action combination.
    Examples: project:read, project:manage, collection:write, audio:read
    """
    __tablename__ = "permission"

    permission_id: int = Field(default=None, primary_key=True)
    resource_type: str = Field(max_length=50, description="Resource type: project, collection, audio, site, etc.")
    action: str = Field(max_length=20, description="Action type: read, write or manage")
    name: str = Field(max_length=128, unique=True, description="Permission name, e.g. project:manage")

    # Relationships
    user_permissions: list["UserPermission"] = Relationship(back_populates="permission")


class UserPermission(SQLModel, table=True):
    """
    User permission assignment scoped to a project or a project-local collection.

    Scope rules:
    - project_id is set, collection_id is NULL  → permission applies to the project
      and is inherited by all collections currently linked to that project.
    - project_id is set, collection_id is set   → permission applies only to that
      collection under that specific project link.
    """
    __tablename__ = "user_permission"

    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(
        foreign_key="user.user_id",
        ondelete="RESTRICT",
        index=True,
    )
    permission_id: int = Field(
        foreign_key="permission.permission_id",
        ondelete="RESTRICT",
    )
    project_id: Optional[int] = Field(
        default=None,
        foreign_key="project.project_id",
        ondelete="RESTRICT",
    )
    collection_id: Optional[int] = Field(
        default=None,
        foreign_key="collection.collection_id",
        ondelete="RESTRICT",
    )
    creation_date: datetime = Field(
        sa_column=sa.Column(
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False
        )
    )

    # Relationships
    user: Optional["User"] = Relationship(back_populates="permissions")
    permission: Optional[Permission] = Relationship(back_populates="user_permissions")
    project: Optional["Project"] = Relationship(back_populates="user_permissions")
    collection: Optional["Collection"] = Relationship(back_populates="user_permissions")
