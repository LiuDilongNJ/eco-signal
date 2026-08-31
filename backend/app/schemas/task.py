from datetime import datetime
from typing import Any, Optional

from pydantic import ConfigDict, Field, field_validator
from sqlmodel import SQLModel

from app.enums.task import AssignmentTaskType
from app.schemas.capability import RowCapabilities


class AssignableUserPublic(SQLModel):
    """Schema for a user who can be assigned a task for a media."""
    user_id: int = Field(..., gt=0)
    name: Optional[str] = None
    username: str
    task_count: int = 0  # Number of existing tasks already assigned to this user for this media

    model_config = ConfigDict(from_attributes=True)


class TaskPublic(SQLModel):
    """Schema for Task public response."""
    task_id: int = Field(..., gt=0)
    type: str = Field(..., max_length=50)
    media_id: Optional[int] = Field(None, gt=0)
    media_type: Optional[str] = None
    annotation_id: Optional[int] = Field(None, gt=0)
    assigner_id: int = Field(..., gt=0)
    assignee_id: int = Field(..., gt=0)
    assigner_name: Optional[str] = None
    assignee_name: Optional[str] = None
    status: str = Field(..., max_length=50)
    comment: Optional[str] = Field(None, max_length=1000)
    datetime: Optional[str] = None
    capabilities: RowCapabilities = Field(default_factory=RowCapabilities)

    @field_validator("datetime", mode="before")
    @classmethod
    def serialize_datetime(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return str(value)

    model_config = ConfigDict(from_attributes=True)


class TaskAssignmentItem(SQLModel):
    """Single assignment item: one user and an optional comment."""
    user_id: int = Field(..., gt=0, description="ID of the user to assign the task to")
    comment: Optional[str] = Field(None, max_length=1000, description="Optional assignment comment")


class TaskListItem(TaskPublic):
    """Schema for Task list read, includes extra resolved fields."""
    media_name: Optional[str] = None


class TaskAssignmentRequest(SQLModel):
    """Request body for assigning tasks to multiple users for a media."""
    type: str = Field(AssignmentTaskType.MEDIA.value, max_length=50, description="Task type: 'media' or 'annotation'")
    annotation_ids: list[int] | None = Field(
        None, description="Annotation IDs for annotation-type tasks (required when type='annotation')"
    )
    assignments: list[TaskAssignmentItem] = Field(..., min_length=1, description="List of user assignments")

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {task_type.value for task_type in AssignmentTaskType}
        if normalized not in allowed:
            raise ValueError("type must be 'media' or 'annotation'")
        return normalized


class TaskAssignmentResult(SQLModel):
    assigned_count: int = Field(ge=0)
