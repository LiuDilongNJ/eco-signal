from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import field_serializer
from sqlmodel import SQLModel


class CollectionBundleExportCreate(SQLModel):
    project_id: int
    collection_id: int


class CollectionBundleExportPublic(SQLModel):
    export_id: UUID
    project_id: int
    collection_id: int
    queue_id: int
    status: str
    filename: str | None = None
    size_b: int | None = None
    counts: dict[str, Any] | None = None
    warnings: list[str] | None = None
    error: str | None = None
    creation_date: datetime
    completion_date: datetime | None = None
    expires_at: datetime | None = None

    @field_serializer("creation_date", "completion_date", "expires_at")
    def serialize_datetime(self, value: datetime | None, _info) -> str | None:
        if value is None:
            return None
        return value.strftime("%Y-%m-%d %H:%M:%S")
