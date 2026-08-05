import uuid
from typing import Optional

from pydantic import ConfigDict
from sqlmodel import SQLModel


class FileUploadBase(SQLModel):
    """Base schema for FileUpload."""
    path: str
    filename: str
    name: str
    directory: int
    uploader_id: int
    status: int  # 1=pending, 2=processing, 3=completed, 4=error


class FileUploadCreate(FileUploadBase):
    path: str
    status: int = 1
    directory: int
    media_id: Optional[int] = None
    batch_id: Optional[uuid.UUID] = None


class FileUploadUpdate(SQLModel):
    """Schema for updating FileUpload records."""
    status: int | None = None
    media_id: int | None = None
    error: str | None = None
    
    model_config = ConfigDict(extra="forbid")
