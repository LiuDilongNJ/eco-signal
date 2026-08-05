"""Persistent collection bundle export records."""

import uuid as uuid_lib
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Column
from sqlmodel import Field, SQLModel


class CollectionBundleExport(SQLModel, table=True):
    """Tracks an asynchronously generated collection bundle."""

    __tablename__ = "collection_bundle_export"

    export_id: uuid_lib.UUID = Field(default_factory=uuid_lib.uuid4, primary_key=True)
    project_id: int = Field(foreign_key="project.project_id", ondelete="CASCADE", index=True)
    collection_id: int = Field(foreign_key="collection.collection_id", ondelete="CASCADE", index=True)
    user_id: int = Field(foreign_key="user.user_id", ondelete="CASCADE", index=True)
    queue_id: int = Field(foreign_key="queue.queue_id", ondelete="CASCADE", unique=True, index=True)
    status: str = Field(default="queued", max_length=20, index=True)
    filename: str | None = Field(default=None, max_length=250)
    path: str | None = Field(default=None, max_length=500)
    size_b: int | None = Field(default=None, sa_column=Column(BigInteger))
    counts: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    warnings: list[str] | None = Field(default=None, sa_column=Column(JSON))
    error: str | None = Field(default=None)
    creation_date: datetime = Field(default_factory=datetime.utcnow, index=True)
    completion_date: datetime | None = Field(default=None)
    expires_at: datetime | None = Field(default=None, index=True)
