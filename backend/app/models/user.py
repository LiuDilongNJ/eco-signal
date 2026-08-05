"""
User database models.

This module contains User, UserPreference, and Role models.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.permission import UserPermission
    from app.models.project import Project, ProjectContributor
    from app.models.collection import Collection, CollectionContributor
    from app.models.site import Site
    from app.models.media import Media
    from app.models.annotation import Annotation, AnnotationReview
    from app.models.system import FileUpload, Queue, News
    from app.models.label import Label, LabelMedia
    from app.models.operation_log import OperationLog


class Role(SQLModel, table=True):
    """User roles for access control."""
    __tablename__ = "role"
    
    role_id: int = Field(default=None, primary_key=True)
    name: str = Field(max_length=128, unique=True)
    
    # Relationships
    users: list["User"] = Relationship(back_populates="role")


class UserBase(SQLModel):
    """Base properties for User."""
    username: str = Field(max_length=20, unique=True, index=True)
    name: str = Field(max_length=100)
    email: str = Field(max_length=100, index=True)
    orcid: Optional[str] = Field(default=None, max_length=100)
    color: str = Field(default="#FFFFFF", max_length=7)
    active: bool = Field(default=True)


class User(UserBase, table=True):
    """System users (researchers, collaborators)."""
    __tablename__ = "user"
    
    user_id: int = Field(default=None, primary_key=True)
    role_id: int = Field(foreign_key="role.role_id")
    password: str = Field(max_length=150)
    
    role: Optional[Role] = Relationship(back_populates="users")
    preference: Optional["UserPreference"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"uselist": False, "passive_deletes": True},
    )
    
    created_projects: list["Project"] = Relationship(
        back_populates="creator",
        sa_relationship_kwargs={
            "foreign_keys": "[Project.creator_id]",
            "passive_deletes": True,
        },
    )
    project_contributions: list["ProjectContributor"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"passive_deletes": True},
    )
    created_collections: list["Collection"] = Relationship(
        back_populates="creator",
        sa_relationship_kwargs={
            "foreign_keys": "[Collection.creator_id]",
            "passive_deletes": True,
        },
    )
    collection_contributions: list["CollectionContributor"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"passive_deletes": True},
    )
    
    created_sites: list["Site"] = Relationship(
        back_populates="creator",
        sa_relationship_kwargs={"passive_deletes": True},
    )
    
    uploaded_media: list["Media"] = Relationship(
        back_populates="uploader",
        sa_relationship_kwargs={
            "foreign_keys": "[Media.uploader_id]",
            "passive_deletes": True,
        },
    )
    created_media: list["Media"] = Relationship(
        back_populates="creator",
        sa_relationship_kwargs={
            "foreign_keys": "[Media.creator_id]",
            "passive_deletes": True,
        },
    )
    
    annotations: list["Annotation"] = Relationship(
        back_populates="creator",
        sa_relationship_kwargs={"passive_deletes": True},
    )
    annotation_reviews: list["AnnotationReview"] = Relationship(
        back_populates="reviewer",
        sa_relationship_kwargs={"passive_deletes": True},
    )
    
    permissions: list["UserPermission"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"passive_deletes": True},
    )
    
    file_uploads: list["FileUpload"] = Relationship(
        back_populates="uploader",
        sa_relationship_kwargs={"passive_deletes": True},
    )
    queues: list["Queue"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"passive_deletes": True},
    )
    news_items: list["News"] = Relationship(
        back_populates="writer",
        sa_relationship_kwargs={"passive_deletes": True},
    )
    
    created_labels: list["Label"] = Relationship(
        back_populates="creator",
        sa_relationship_kwargs={"passive_deletes": True},
    )
    label_media: list["LabelMedia"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"passive_deletes": True},
    )
    
    operation_logs: list["OperationLog"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"passive_deletes": True},
    )
class UserPreference(SQLModel, table=True):
    """User-specific preferences and settings."""
    __tablename__ = "user_preference"
    
    user_id: int = Field(
        foreign_key="user.user_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    fft: int = Field(default=1024)
    theme: Optional[str] = Field(default="auto", max_length=20)
    language: Optional[str] = Field(default="en", max_length=10)
    timezone: Optional[str] = Field(default="UTC", max_length=50)
    notifications_enabled: Optional[bool] = Field(default=True)
    updated_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    user: Optional[User] = Relationship(back_populates="preference")
