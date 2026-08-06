"""
Project database models.

This module contains Project, ProjectContributor, and ProjectCollection models.
"""
import uuid as uuid_lib
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.collection import Collection
    from app.models.permission import UserPermission
    from app.models.site import SiteProject


class ProjectBase(SQLModel):
    """Base properties for Project."""
    name: str = Field(max_length=100)
    url: str = Field(default="", max_length=255)
    picture_id: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None)
    description_short: Optional[str] = Field(default=None)
    doi: Optional[str] = Field(default=None, max_length=255)
    public: bool = Field(default=True)
    active: bool = Field(default=True)


class Project(ProjectBase, table=True):
    """Research projects containing multiple collections."""
    __tablename__ = "project"
    
    project_id: int = Field(default=None, primary_key=True)
    uuid: uuid_lib.UUID = Field(
        default_factory=uuid_lib.uuid4,
        unique=True,
        index=True
    )
    creator_id: int = Field(foreign_key="user.user_id", ondelete="RESTRICT")
    creation_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    creator: Optional["User"] = Relationship(
        back_populates="created_projects",
        sa_relationship_kwargs={"foreign_keys": "[Project.creator_id]"}
    )
    contributors: list["ProjectContributor"] = Relationship(back_populates="project")
    project_collections: list["ProjectCollection"] = Relationship(back_populates="project")
    site_projects: list["SiteProject"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    user_permissions: list["UserPermission"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class ProjectContributor(SQLModel, table=True):
    """Project contributors for proper attribution."""
    __tablename__ = "project_contributor"
    
    project_id: int = Field(
        foreign_key="project.project_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    user_id: int = Field(
        foreign_key="user.user_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    contribution_role: Optional[str] = Field(default=None, max_length=100)
    added_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    project: Optional[Project] = Relationship(back_populates="contributors")
    user: Optional["User"] = Relationship(back_populates="project_contributions")


class ProjectCollection(SQLModel, table=True):
    """Many-to-many: Collections can belong to multiple projects."""
    __tablename__ = "project_collection"
    
    project_id: int = Field(
        foreign_key="project.project_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    collection_id: int = Field(
        foreign_key="collection.collection_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    added_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    project: Optional[Project] = Relationship(back_populates="project_collections")
    collection: Optional["Collection"] = Relationship(back_populates="project_collections")
