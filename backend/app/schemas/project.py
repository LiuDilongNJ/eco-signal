from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import Field, computed_field, field_serializer, field_validator
from sqlmodel import SQLModel

from app.media_paths import build_media_public_url, logical_project_media_path
from app.utils import validate_optional_http_url


class ProjectCreate(SQLModel):
    """Schema for creating a new project."""
    name: str = Field(..., max_length=100, description="Project name")
    url: Optional[str] = Field(None, max_length=255, description="Project URL")
    picture_id: Optional[str] = Field(None, max_length=255, description="Picture ID")
    description: Optional[str] = Field(None, description="Full description")
    description_short: Optional[str] = Field(None, description="Short description")
    doi: Optional[str] = Field(None, max_length=255, description="DOI")
    public: bool = Field(True, description="Whether project is public")
    active: bool = Field(True, description="Whether project is active")

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: Optional[str]) -> Optional[str]:
        return validate_optional_http_url(value)


class ProjectUpdate(SQLModel):
    """Schema for updating a project (all fields optional)."""
    name: Optional[str] = Field(None, max_length=100)
    url: Optional[str] = Field(None, max_length=255)
    picture_id: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    description_short: Optional[str] = None
    doi: Optional[str] = Field(None, max_length=255)
    public: Optional[bool] = None
    active: Optional[bool] = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: Optional[str]) -> Optional[str]:
        return validate_optional_http_url(value)


class ProjectPublic(SQLModel):
    """Schema for project response data."""
    project_id: int
    uuid: UUID
    name: str
    url: str
    picture_id: Optional[str] = None
    description: Optional[str] = None
    description_short: Optional[str] = None
    doi: Optional[str] = None
    public: bool
    active: bool
    creator_id: int
    creator_name: Optional[str] = Field(default=None, description="Display name of the project creator")
    creation_date: datetime

    # Convert None to empty string for nullable string fields
    @field_serializer('picture_id', 'description', 'description_short', 'doi')
    @classmethod
    def convert_none_to_empty_string(cls, v: Optional[str]) -> str:
        return v if v is not None else ""

    # Format creation_date as standard datetime string: YYYY-MM-DD HH:MM:SS
    @field_serializer('creation_date')
    @classmethod
    def format_creation_date(cls, v: datetime) -> str:
        return v.strftime("%Y-%m-%d %H:%M:%S")

    @computed_field
    @property
    def picture_url(self) -> str:
        return build_media_public_url(logical_project_media_path(self.picture_id)) if self.picture_id else ""

    class Config:
        from_attributes = True


class ProjectCardPublic(SQLModel):
    """Schema for project card list response."""
    project_id: int
    name: str
    public: bool
    description: Optional[str] = None
    description_short: Optional[str] = None
    doi: Optional[str] = None
    url: str
    can_access: bool = False
    image_url: str = ""
    creator: Optional[str] = None
    contributors: list[str] = Field(default_factory=list)

    @field_serializer("description", "description_short", "doi", "creator")
    @classmethod
    def convert_none_to_empty_string(cls, v: Optional[str]) -> str:
        return v if v is not None else ""

    class Config:
        from_attributes = True


class ProjectDetail(ProjectPublic):
    """Schema for project detail response."""


class ProjectLinkCollectionItem(SQLModel):
    """Collection item used by project-collection link dialog."""
    collection_id: int
    name: str
    selected: bool = False
    duplicate_project_ids: list[int] = Field(default_factory=list)


class ProjectLinkCurrentProject(SQLModel):
    """Current project block for project-collection link dialog."""
    project_id: int
    project_name: str
    collections: list[ProjectLinkCollectionItem] = Field(default_factory=list)


class ProjectLinkOtherProject(SQLModel):
    """Other project block for project-collection link dialog."""
    project_id: int
    project_name: str
    collections: list[ProjectLinkCollectionItem] = Field(default_factory=list)


class ProjectCollectionLinkOptionsResponse(SQLModel):
    """Response schema for project-collection link dialog options."""
    current_project: ProjectLinkCurrentProject
    other_projects: list[ProjectLinkOtherProject] = Field(default_factory=list)
    unassigned_collections: list[ProjectLinkCollectionItem] = Field(default_factory=list)


class ProjectCollectionSyncRequest(SQLModel):
    """Request schema for full sync of project collections."""
    collection_ids: list[int] = Field(default_factory=list)
