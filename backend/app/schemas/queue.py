from datetime import datetime

from pydantic import ConfigDict, field_serializer
from sqlmodel import Field, SQLModel

from app.schemas.capability import RowCapabilities


class QueueDetail(SQLModel):
    """
    Base response for queue status.
    """
    queue_id: int
    status: str
    progress: float
    completed: int
    total: int
    error: str | None = None
    warning: str | None = None
    type: str
    message: str | None = None
    start_time: datetime | None = None
    stop_time: datetime | None = None

    @field_serializer("start_time", "stop_time")
    def serialize_datetime(self, dt: datetime | None, _info):
        if dt is None:
            return None
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class QueueListItem(QueueDetail):
    """
    Advanced queue list response with user info.
    """
    user_id: int
    username: str
    capabilities: RowCapabilities = Field(default_factory=RowCapabilities)

    model_config = ConfigDict(from_attributes=True)


class QueueDeleteRequest(SQLModel):
    queue_ids: list[int] = Field(min_length=1)


class QueueDeletionResult(SQLModel):
    deleted_ids: list[int] = Field(default_factory=list)
    cancelling_ids: list[int] = Field(default_factory=list)
    unavailable_ids: list[int] = Field(default_factory=list)
