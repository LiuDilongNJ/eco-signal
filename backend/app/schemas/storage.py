"""Read models for monitored filesystem capacity."""

from typing import Literal

from pydantic import Field
from sqlmodel import SQLModel

StorageHealth = Literal["healthy", "warning", "critical", "unavailable"]


class FilesystemStatus(SQLModel):
    scope: Literal["container_root", "media"]
    path: str
    available: bool
    total_bytes: int | None = Field(default=None, ge=0)
    used_bytes: int | None = Field(default=None, ge=0)
    free_bytes: int | None = Field(default=None, ge=0)
    used_percent: float | None = Field(default=None, ge=0, le=100)
    status: StorageHealth


class StorageStatus(SQLModel):
    checked_at: str
    status: StorageHealth
    warning_percent: float = 80.0
    critical_percent: float = 90.0
    filesystems: list[FilesystemStatus]
