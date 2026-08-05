"""
Label database models.

This module contains Label and LabelMedia models.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.media import Media


class Label(SQLModel, table=True):
    """User-defined labels for organizing media."""
    __tablename__ = "label"
    
    label_id: int = Field(default=None, primary_key=True)
    name: str = Field(max_length=20)
    type: str = Field(default="private", max_length=20)
    creator_id: Optional[int] = Field(
        default=None,
        foreign_key="user.user_id",
        ondelete="SET NULL"
    )
    creation_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    creator: Optional["User"] = Relationship(back_populates="created_labels")
    label_media: list["LabelMedia"] = Relationship(back_populates="label")


class LabelMedia(SQLModel, table=True):
    """Many-to-many: Users applying labels to media."""
    __tablename__ = "label_media"
    
    media_id: int = Field(
        foreign_key="media.media_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    user_id: int = Field(
        foreign_key="user.user_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    label_id: int = Field(
        foreign_key="label.label_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    
    # Relationships
    media: Optional["Media"] = Relationship(back_populates="label_media")
    user: Optional["User"] = Relationship(back_populates="label_media")
    label: Optional[Label] = Relationship(back_populates="label_media")
