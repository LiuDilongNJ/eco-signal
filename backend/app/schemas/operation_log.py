"""
Operation log schemas.
"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class OperationLogBase(BaseModel):
    """Base fields for operation log."""
    action: str = Field(..., max_length=50)
    resource_type: str = Field(..., max_length=100)
    resource_id: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    req_ip: Optional[str] = Field(None, max_length=50)
    req_endpoint: Optional[str] = Field(None, max_length=255)
    payload: Optional[Any] = None
    status_code: int = 200


class OperationLogCreate(OperationLogBase):
    """Schema for creating an operation log."""
    user_id: Optional[int] = None


class OperationLogRead(OperationLogBase):
    """Schema for reading an operation log."""
    log_id: int
    user_id: Optional[int] = None
    creation_date: datetime
    
    # We might want to include username to easily display who did it
    username: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("creation_date")
    def serialize_datetime(self, dt: datetime, _info) -> str:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
