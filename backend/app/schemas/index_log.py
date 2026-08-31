from datetime import datetime
from typing import Any, Optional

from pydantic import field_serializer
from sqlmodel import Field, SQLModel

from app.models.index import IndexLogBase
from app.schemas.capability import RowCapabilities


class IndexLogRead(IndexLogBase):
    """Schema for reading IndexLog, includes joined names."""
    log_id: int
    user_name: Optional[str] = None
    media_name: Optional[str] = None
    index_name: Optional[str] = None
    capabilities: RowCapabilities = Field(default_factory=RowCapabilities)

    @field_serializer("creation_date")
    @classmethod
    def serialize_creation_date(cls, value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")


class IndexLogDeleteItem(SQLModel):
    """Structured delete identity for one index log group."""

    log_id: int
    media_id: int
    index_id: int


class IndexLogCreateRequest(SQLModel):
    """Persist one confirmed acoustic index result group."""

    project_id: int
    media_id: int
    index_id: int
    version: str
    min_time: str | None = None
    max_time: str | None = None
    min_frequency: str | None = None
    max_frequency: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)


class IndexLogCreateResponse(SQLModel):
    """Stored acoustic index group summary."""

    log_id: int
    stored_count: int
