from datetime import datetime
from typing import Optional

from pydantic import field_serializer
from sqlmodel import Field, SQLModel


class ReviewCreate(SQLModel):
    project_id: int = Field(gt=0)
    annotation_id: int = Field(gt=0)
    annotation_review_status_id: int = Field(gt=0)
    taxon_id: Optional[int] = Field(default=None, gt=0)
    note: Optional[str] = Field(default=None, max_length=200)


class ReviewUpdate(SQLModel):
    annotation_review_status_id: Optional[int] = Field(default=None, gt=0)
    taxon_id: Optional[int] = Field(default=None, gt=0)
    note: Optional[str] = Field(default=None, max_length=200)


class ReviewRead(SQLModel):
    """
    Schema for returning annotation review details in list API.
    Includes fields from related tables (Media, User, Status, Taxon).
    """
    annotation_id: int
    reviewer_id: int
    annotation_review_status_id: int
    taxon_id: Optional[int] = None
    note: Optional[str] = None
    creation_date: datetime
    
    # Joined fields
    media_name: Optional[str] = None
    media_type: str
    reviewer_name: str
    status_name: str
    taxon_name: Optional[str] = None

    @field_serializer("creation_date")
    @classmethod
    def serialize_creation_date(cls, value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")
