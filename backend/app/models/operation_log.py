"""
Operation log model.

This module contains the OperationLog model for tracking system actions.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.user import User


class OperationLog(SQLModel, table=True):
    """System operation log for auditing."""
    __tablename__ = "operation_log"
    
    log_id: int = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(
        default=None,
        foreign_key="user.user_id",
        ondelete="SET NULL",
        index=True
    )
    action: str = Field(max_length=50, index=True)
    resource_type: str = Field(max_length=100, index=True)
    resource_id: Optional[str] = Field(default=None, max_length=100, index=True)
    description: Optional[str] = Field(default=None)
    req_ip: Optional[str] = Field(default=None, max_length=50)
    req_endpoint: Optional[str] = Field(default=None, max_length=255)
    payload: Optional[Any] = Field(default=None, sa_column=Column(JSON))
    status_code: int = Field(default=200)
    creation_date: datetime = Field(default_factory=datetime.utcnow, index=True)
    
    # Relationships
    user: Optional["User"] = Relationship(back_populates="operation_logs")
