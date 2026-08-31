"""Read models for container filesystem storage status."""

from typing import Literal

from sqlmodel import SQLModel


class StorageStatus(SQLModel):
    """Capacity information for the backend container root filesystem."""

    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    used_percent: float
    status: Literal["healthy", "warning", "critical"]
