"""
System management database models.

This module contains Model, Queue, News, Setting, and FileUpload models.
"""
import uuid as uuid_lib
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.media import Media


class MLModel(SQLModel, table=True):
    """Machine learning models for automatic species identification."""
    __tablename__ = "model"
    
    model_id: int = Field(default=None, primary_key=True)
    name: Optional[str] = Field(default=None, max_length=100)
    model_path: Optional[str] = Field(default=None, max_length=255)
    labels_path: Optional[str] = Field(default=None, max_length=255)
    source_url: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None)
    parameter: Optional[Any] = Field(default=None, sa_column=Column(JSON))


class Queue(SQLModel, table=True):
    """Background job queue for long-running tasks."""
    __tablename__ = "queue"
    
    queue_id: int = Field(default=None, primary_key=True)
    type: str = Field(max_length=100)  # 'spectrogram', 'index', 'model_inference', etc.
    user_id: int = Field(
        foreign_key="user.user_id",
        ondelete="CASCADE",
        index=True
    )
    completed: int = Field(default=0)
    total: int = Field(default=0)
    status: int = Field(default=0, index=True)
    start_time: Optional[datetime] = Field(default=None)
    stop_time: Optional[datetime] = Field(default=None)
    error: Optional[str] = Field(default=None)
    warning: Optional[str] = Field(default=None)
    
    # Relationships
    user: Optional["User"] = Relationship(back_populates="queues")


class News(SQLModel, table=True):
    """System announcements and news items."""
    __tablename__ = "news"
    
    news_id: int = Field(default=None, primary_key=True)
    title: str = Field(max_length=100)
    content: str
    writer_id: int = Field(
        foreign_key="user.user_id",
        ondelete="CASCADE",
        index=True
    )
    creation_date: datetime = Field(default_factory=datetime.utcnow, index=True)
    
    # Relationships
    writer: Optional["User"] = Relationship(back_populates="news_items")


class Setting(SQLModel, table=True):
    """Application-wide configuration settings (key-value pairs)."""
    __tablename__ = "setting"
    
    name: str = Field(max_length=100, primary_key=True)
    value: str


class FileUpload(SQLModel, table=True):
    """Staging table for media file uploads: tracking upload status and linking to processed media."""
    __tablename__ = "file_upload"
    
    file_upload_id: int = Field(default=None, primary_key=True)
    batch_id: Optional[uuid_lib.UUID] = Field(default=None, index=True)
    path: str
    status: int = Field(default=1, index=True)  # 1=pending, 2=processing, 3=completed, 4=error, 5=duplicate/skipped
    filename: str = Field(max_length=250)
    name: str = Field(max_length=250)
    media_id: Optional[int] = Field(
        default=None,
        foreign_key="media.media_id",
        ondelete="SET NULL",
        index=True
    )
    directory: int
    uploader_id: int = Field(
        foreign_key="user.user_id",
        ondelete="RESTRICT",
        index=True
    )
    error: Optional[str] = Field(default=None)
    upload_date_time: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    uploader: Optional["User"] = Relationship(back_populates="file_uploads")
    media: Optional["Media"] = Relationship()
