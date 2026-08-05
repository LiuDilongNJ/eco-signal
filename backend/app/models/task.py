"""
Task models for the ecoSignal application.
"""
from datetime import datetime as dt_type
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, SQLModel

if TYPE_CHECKING:
    pass


class Task(SQLModel, table=True):
    """User-assigned review/annotation task."""
    __tablename__ = "task"
    
    task_id: int = Field(default=None, primary_key=True)
    type: str = Field(max_length=50)
    media_id: Optional[int] = Field(
        default=None, 
        foreign_key="media.media_id", 
        ondelete="CASCADE",
        index=True
    )
    annotation_id: Optional[int] = Field(
        default=None, 
        foreign_key="annotation.annotation_id", 
        ondelete="CASCADE",
        index=True
    )
    assigner_id: int = Field(
        foreign_key="user.user_id", 
        ondelete="CASCADE",
        index=True
    )
    assignee_id: int = Field(
        foreign_key="user.user_id", 
        ondelete="CASCADE",
        index=True
    )
    status: str = Field(default="assigned", max_length=50)
    comment: Optional[str] = Field(default=None, max_length=1000)
    datetime: Optional[dt_type] = Field(default=None)
