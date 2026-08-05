"""
Index database models.

This module contains IndexType and IndexLog models for acoustic indices.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.media import Media


class IndexType(SQLModel, table=True):
    """Acoustic index types (ACI, NDSI, BI, etc.) with their parameters."""
    __tablename__ = "index_type"
    
    index_id: int = Field(default=None, primary_key=True)
    name: Optional[str] = Field(default=None, max_length=100)
    param: Optional[Any] = Field(default=None, sa_column=Column(JSON))
    description: Optional[str] = Field(default=None, max_length=255)
    url: Optional[str] = Field(default=None, max_length=100)
    
    # Relationships
    index_logs: list["IndexLog"] = Relationship(back_populates="index_type")


class IndexLogBase(SQLModel):
    media_id: int = Field(
        foreign_key="media.media_id",
        ondelete="CASCADE",
        index=True
    )
    user_id: int = Field(
        foreign_key="user.user_id",
        ondelete="CASCADE"
    )
    index_id: int = Field(
        foreign_key="index_type.index_id",
        ondelete="CASCADE"
    )
    version: Optional[str] = Field(default=None, max_length=100)
    min_time: Optional[str] = Field(default=None, max_length=100)
    max_time: Optional[str] = Field(default=None, max_length=100)
    min_frequency: Optional[str] = Field(default=None, max_length=100)
    max_frequency: Optional[str] = Field(default=None, max_length=100)
    variable_type: Optional[str] = Field(default=None, max_length=100)
    variable_order: int
    variable_name: Optional[str] = Field(default=None, max_length=100)
    variable_value: Optional[str] = Field(default=None, max_length=100)
    creation_date: datetime = Field(default_factory=datetime.utcnow)


class IndexLog(IndexLogBase, table=True):
    """Computed acoustic indices for soundscape analysis (audio media only)."""
    __tablename__ = "index_log"

    log_id: int = Field(default=None, primary_key=True)

    # Relationships
    media: Optional["Media"] = Relationship(back_populates="index_logs")
    index_type: Optional[IndexType] = Relationship(back_populates="index_logs")

