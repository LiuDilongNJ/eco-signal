from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, field_serializer
from sqlmodel import SQLModel


class DataImportCreateRequest(SQLModel):
    """Request body for creating an offline import upload session."""

    project_id: int


class DataImportCreateResponse(SQLModel):
    """Response returned after creating an offline import upload session."""

    batch_id: str
    project_id: int
    status: str


class DataImportConflict(SQLModel):
    """Conflict entry reported during offline bundle import."""

    resource_type: str
    identifier: str
    reason: str


class DataImportWarning(SQLModel):
    """Warning entry reported during offline bundle import."""

    resource_type: str
    identifier: str
    message: str


class DataImportCounts(SQLModel):
    """Created/skipped counters grouped by resource type."""

    collections: int = 0
    project_links: int = 0
    sites: int = 0
    site_links: int = 0
    media: int = 0
    audio: int = 0
    photos: int = 0
    media_files: int = 0
    media_links: int = 0
    previews: int = 0
    annotations: int = 0
    reviews: int = 0
    labels: int = 0
    label_links: int = 0


class DataImportSummary(SQLModel):
    """Structured import result stored in the offline import context."""

    project_id: int
    collection_id: int
    collection_uuid: str
    signature_verified: bool = True
    checksum_verified: bool = True
    created_counts: DataImportCounts = Field(default_factory=DataImportCounts)
    skipped_counts: DataImportCounts = Field(default_factory=DataImportCounts)
    conflicts: list[DataImportConflict] = Field(default_factory=list)
    warnings: list[DataImportWarning] = Field(default_factory=list)
    bundle_manifest: dict[str, Any] = Field(default_factory=dict)


class DataImportStatusResponse(SQLModel):
    """Status payload exposed by GET /data-imports/{id}."""

    batch_id: str
    project_id: int
    uploader_id: int
    file_upload_id: int | None = None
    queue_id: int | None = None
    status: str
    error: str | None = None
    summary_json: dict[str, Any] | None = None
    cleanup_after: datetime | None = None
    creation_date: datetime
    update_date: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("cleanup_after", "creation_date", "update_date")
    def serialize_datetime(self, value: datetime | None, _info) -> str | None:
        if value is None:
            return None
        return value.strftime("%Y-%m-%d %H:%M:%S")
